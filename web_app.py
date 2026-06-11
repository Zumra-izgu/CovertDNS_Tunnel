#!/usr/bin/env python3
"""
CovertDNS - Web Sender Application

A Flask-based web interface for sending post-quantum encrypted messages through DNS tunnels.
This application provides a user-friendly dashboard for managing Kyber-768 keys, composing
messages, and monitoring transmission progress.

Features:
    - User authentication (login/registration) with bcrypt password hashing
    - Kyber-768 key generation and management
    - Stealth mode configuration for anti-detection
    - Real-time message sending with progress tracking
    - Persistent message history stored in MongoDB Atlas
    - WebSocket communication for live updates

Database:
    Uses MongoDB Atlas for storing user accounts, cryptographic keys, and message history.
    All connections are managed through a singleton pattern to ensure efficient resource usage.

Security:
    - Passwords are hashed using bcrypt before storage
    - Cryptographic keys are stored as Base64-encoded strings
    - Session management via Flask-Login with strong session protection
    - All sensitive configuration loaded from .env file

Usage:
    python web_app.py
    Then open browser to http://localhost:5000

Dependencies:
    Flask, Flask-SocketIO, Flask-Login, PyMongo, bcrypt, python-dotenv
"""

import threading
import time
import base64
import os
import sys
import logging
from datetime import datetime
from flask import Flask, render_template, request, jsonify, redirect, url_for, session
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_login import LoginManager, login_user, login_required, logout_user, current_user

# Add parent directory to Python path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dns_tunnel import DNSSender, generate_keys
from config import get_config
from database import get_db, init_db
from models import User

# ============================================================================
# Application Configuration
# ============================================================================

# Load configuration from .env file
Config = get_config()

# Configure logging for both console and file output
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# Stealth Module (Optional)
# ============================================================================

STEALTH_AVAILABLE = False
try:
    from stealth.traffic_simulator import StealthDNSEngine
    STEALTH_AVAILABLE = True
    logger.info("Stealth module loaded successfully")
except ImportError:
    logger.info("Stealth module not available - continuing with normal delays")

# ============================================================================
# Flask Application Initialization
# ============================================================================

app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'

# SocketIO for real-time WebSocket communication
socketio = SocketIO(app, cors_allowed_origins="*")

# Flask-Login for user session management
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"


@login_manager.user_loader
def load_user(user_id):
    """
    Load a user from the database by their ID.
    
    This callback is used by Flask-Login to reload the user object from the
    user ID stored in the session. It is called on each request for authenticated
    users to restore the user object.
    
    Args:
        user_id (str): MongoDB ObjectId as a string.
    
    Returns:
        User or None: User object if found, None otherwise.
    """
    return User.get(user_id)


# ============================================================================
# Database Initialization
# ============================================================================

# Get the singleton database instance
db = get_db()

# ============================================================================
# Application State
# ============================================================================

# Track which users are currently sending messages (prevents concurrent sends)
is_sending = {}

# Store each user's current stealth mode preference
current_stealth_mode = {}


# ============================================================================
# Web Routes
# ============================================================================

@app.route('/')
@login_required
def index():
    """
    Main dashboard page.
    
    Displays the message composition interface, key management panel,
    stealth mode controls, and message history.
    
    Returns:
        str: Rendered index.html template.
    """
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    """
    User login page and authentication endpoint.
    
    GET: Display the login form.
    POST: Authenticate user credentials and start a session.
    
    Returns:
        str: Rendered login.html template on GET or failed login.
        redirect: Redirect to dashboard on successful login.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        # Retrieve user from database
        user_data = db.get_user(username)
        
        # Verify credentials
        if user_data and db.verify_password(username, password):
            user = User(user_data)
            login_user(user)
            db.update_last_login(username)
            logger.info(f"User {username} logged in successfully")
            return redirect(url_for('index'))
        else:
            logger.warning(f"Failed login attempt for username: {username}")
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    """
    User registration page and account creation endpoint.
    
    GET: Display the registration form.
    POST: Create a new user account with generated Kyber-768 keys.
    
    The registration process:
        1. Validate password confirmation
        2. Check for existing username
        3. Generate Kyber-768 keypair
        4. Create user document in database
        5. Automatically log in the new user
    
    Returns:
        str: Rendered register.html template on GET or failed registration.
        redirect: Redirect to dashboard on successful registration.
    """
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        # Validate password confirmation
        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match')
        
        # Check for existing user
        if db.get_user(username):
            return render_template('register.html', error='Username already exists')
        
        # Generate Kyber-768 keypair for the new user
        pub_b64, priv_b64 = generate_keys()
        
        # Create user in database
        success = db.create_user(username, password, pub_b64, priv_b64)
        
        if success:
            user_data = db.get_user(username)
            user = User(user_data)
            login_user(user)
            logger.info(f"New user registered: {username}")
            return redirect(url_for('index'))
        else:
            return render_template('register.html', error='Registration failed')
    
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    """
    User logout endpoint.
    
    Terminates the user's session and redirects to the login page.
    
    Returns:
        redirect: Redirect to login page.
    """
    username = current_user.username
    logout_user()
    logger.info(f"User {username} logged out")
    return redirect(url_for('login'))


# ============================================================================
# API Endpoints
# ============================================================================

@app.route('/api/keys/get', methods=['GET'])
@login_required
def api_get_keys():
    """
    Retrieve the current user's cryptographic keys.
    
    Returns:
        json: Object containing public_key and private_key (Base64 encoded).
    """
    user_data = db.get_user(current_user.username)
    return jsonify({
        'public': user_data.get('public_key') or '',
        'private': user_data.get('private_key') or ''
    })


@app.route('/api/keys/generate', methods=['POST'])
@login_required
def api_generate_keys():
    """
    Generate a new Kyber-768 keypair for the current user.
    
    The existing keys are overwritten. This operation cannot be undone.
    
    Returns:
        json: Success status and the new keys (Base64 encoded).
    """
    try:
        pub_b64, priv_b64 = generate_keys()
        
        db.update_user_keys(current_user.username, pub_b64, priv_b64)
        
        # Notify the client via WebSocket
        socketio.emit('keys_updated', {
            'public': pub_b64[:100] + '...',
            'private': priv_b64[:100] + '...'
        }, room=str(current_user.id))
        
        logger.info(f"User {current_user.username} generated new keys")
        return jsonify({'success': True, 'public': pub_b64, 'private': priv_b64})
    except Exception as e:
        logger.error(f"Key generation error: {e}")
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/keys/load', methods=['POST'])
@login_required
def api_load_keys():
    """
    Load the current user's existing keys from the database.
    
    Returns:
        json: Success status and the loaded keys (truncated for display).
    """
    user_data = db.get_user(current_user.username)
    pub_b64 = user_data.get('public_key', '')
    priv_b64 = user_data.get('private_key', '')
    
    socketio.emit('keys_updated', {
        'public': (pub_b64[:100] + '...') if pub_b64 else 'Not loaded',
        'private': (priv_b64[:100] + '...') if priv_b64 else 'Not loaded'
    }, room=str(current_user.id))
    
    return jsonify({'success': True, 'public': pub_b64, 'private': priv_b64})


@app.route('/api/history', methods=['GET'])
@login_required
def api_get_history():
    """
    Retrieve the user's message history.
    
    Returns the 50 most recent messages sent by the user, ordered by
    creation date (newest first).
    
    Returns:
        json: Object containing 'sent' array of message objects.
    """
    try:
        messages = db.get_user_messages(current_user.id, limit=50)
        
        # Format messages for JSON serialization
        formatted_messages = []
        for m in messages:
            formatted_messages.append({
                'to': m.get('to', 'unknown'),
                'message': m.get('message', ''),
                'time': m.get('created_at').strftime('%Y-%m-%d %H:%M:%S') if m.get('created_at') else datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
                'encrypted': bool(m.get('encrypted', True)),
                'stealth': m.get('stealth_mode', 'off')
            })
        
        return jsonify({'sent': formatted_messages})
    except Exception as e:
        logger.error(f"History retrieval error: {e}")
        return jsonify({'sent': []})


@app.route('/api/sender/send', methods=['POST'])
@login_required
def api_send_message():
    """
    Send a message through the DNS tunnel.
    
    This endpoint initiates an asynchronous message sending process. The
    message is encrypted (if a public key is provided), split into chunks,
    and sent as DNS queries to the target IP address.
    
    Request JSON body:
        - target_ip (str): Receiver's IP address
        - message (str): Plaintext message to send
        - encrypt (bool): Whether to encrypt the message
        - public_key (str, optional): Receiver's Kyber-768 public key
        - stealth_mode (str): 'off', 'low', 'normal', or 'high'
    
    Returns:
        json: Success status (the actual sending happens asynchronously).
    """
    global is_sending
    
    user_id = current_user.id
    username = current_user.username
    
    data = request.json
    target_ip = data.get('target_ip', '127.0.0.1')
    message = data.get('message', '')
    encrypt = data.get('encrypt', True)
    public_key_b64 = data.get('public_key', None)
    stealth_mode = data.get('stealth_mode', current_stealth_mode.get(user_id, 'off'))
    
    # Validate input
    if not message:
        return jsonify({'success': False, 'error': 'No message provided'})
    
    if is_sending.get(user_id, False):
        return jsonify({'success': False, 'error': 'Already sending a message'})
    
    def send_in_background():
        """
        Background thread function for asynchronous message sending.
        
        Handles the actual DNS tunneling process and reports progress
        and results via WebSocket events.
        """
        is_sending[user_id] = True
        try:
            # Create the DNS sender
            sender = DNSSender(target_ip, public_key_b64 if public_key_b64 else None)
            
            # Setup stealth mode if requested
            stealth_engine = None
            if stealth_mode != 'off' and STEALTH_AVAILABLE:
                stealth_engine = StealthDNSEngine()
                stealth_engine.start_stealth_mode(stealth_mode)
                sender.set_stealth_engine(stealth_engine)
            
            # Monkey-patch the _send_single_query method to report progress
            original_send = sender._send_single_query
            total_chunks = 0
            
            def progress_send(domain, chunk_num, total):
                nonlocal total_chunks
                total_chunks = total
                socketio.emit('send_progress', {
                    'chunk': chunk_num + 1,
                    'total': total,
                    'percent': ((chunk_num + 1) / total) * 100
                }, room=user_id)
                return original_send(domain, chunk_num, total)
            
            sender._send_single_query = progress_send
            
            # Send the message
            success = sender.send_message(message)
            
            # Cleanup
            if stealth_engine:
                stealth_engine.stop_stealth_mode()
            sender.close()
            
            if success:
                # Save to database
                db.save_message(user_id, target_ip, message, encrypt, stealth_mode)
                db.increment_message_count(username)
                
                # Notify client
                socketio.emit('message_sent', {
                    'to': target_ip,
                    'message': message[:100]
                }, room=user_id)
                socketio.emit('history_update', {}, room=user_id)
                
                logger.info(f"Message sent by {username} to {target_ip}")
            else:
                socketio.emit('error', {'message': 'Send failed'}, room=user_id)
                logger.warning(f"Send failed for {username}")
                
        except Exception as e:
            logger.error(f"Send error: {e}")
            socketio.emit('error', {'message': str(e)}, room=user_id)
        finally:
            is_sending[user_id] = False
            socketio.emit('send_complete', {}, room=user_id)
    
    # Start the background thread
    thread = threading.Thread(target=send_in_background)
    thread.start()
    
    return jsonify({'success': True})


@app.route('/api/status', methods=['GET'])
@login_required
def api_get_status():
    """
    Get current application status and user statistics.
    
    Returns:
        json: System status including DNS configuration, message count,
              stealth availability, and username.
    """
    message_count = db.get_message_count(current_user.id)
    
    return jsonify({
        'port': Config.DNS_PORT,
        'domain': Config.DNS_BASE_DOMAIN,
        'chunk_size': Config.DNS_MAX_CHUNK_SIZE,
        'sent_count': message_count,
        'stealth_available': STEALTH_AVAILABLE,
        'username': current_user.username
    })


# ============================================================================
# WebSocket Event Handlers
# ============================================================================

@socketio.on('connect')
def handle_connect():
    """
    Handle new WebSocket connections.
    
    When a client connects, this function:
        1. Adds the client to a room named after their user ID
        2. Sends the user's current keys
        3. Sends the current stealth mode status
        4. Sends the message history
    
    This enables real-time updates for the client without polling.
    """
    if current_user.is_authenticated:
        user_id = str(current_user.id)
        join_room(user_id)
        logger.info(f"User {current_user.username} connected via WebSocket")
        
        # Load user's keys
        user_data = db.get_user(current_user.username)
        pub_key = user_data.get('public_key', '')
        priv_key = user_data.get('private_key', '')
        
        emit('keys_updated', {
            'public': (pub_key[:100] + '...') if pub_key else '-',
            'private': (priv_key[:100] + '...') if priv_key else '-'
        })
        emit('stealth_status', {
            'mode': current_stealth_mode.get(user_id, 'off'),
            'available': STEALTH_AVAILABLE
        })
        
        # Send message history
        try:
            messages = db.get_user_messages(current_user.id, limit=50)
            formatted = []
            for m in messages:
                formatted.append({
                    'to': m.get('to', 'unknown'),
                    'message': m.get('message', ''),
                    'time': m.get('created_at').strftime('%Y-%m-%d %H:%M:%S') if m.get('created_at') else '',
                    'encrypted': bool(m.get('encrypted', True)),
                    'stealth': m.get('stealth_mode', 'off')
                })
            emit('history_data', {'sent': formatted})
        except Exception as e:
            logger.error(f"History send error: {e}")


@socketio.on('set_stealth_mode')
def handle_set_stealth_mode(data):
    """
    Update the user's stealth mode preference.
    
    Args:
        data (dict): Contains 'mode' key with value 'off', 'low', 'normal', or 'high'.
    
    The new mode is stored in memory and will be used for future messages.
    """
    if current_user.is_authenticated:
        mode = data.get('mode', 'off')
        current_stealth_mode[str(current_user.id)] = mode
        emit('stealth_status', {
            'mode': mode,
            'available': STEALTH_AVAILABLE
        }, room=str(current_user.id))
        logger.debug(f"User {current_user.username} set stealth mode to {mode}")


@socketio.on('disconnect')
def handle_disconnect():
    """
    Handle WebSocket disconnections.
    
    Removes the client from their user room and logs the disconnection.
    """
    if current_user.is_authenticated:
        leave_room(str(current_user.id))
        logger.info(f"User {current_user.username} disconnected from WebSocket")


# ============================================================================
# Application Entry Point
# ============================================================================

if __name__ == '__main__':
    # Create required directories if they don't exist
    for folder in ['templates', 'static/css', 'static/js']:
        if not os.path.exists(folder):
            os.makedirs(folder)
    
    # Initialize database indexes
    init_db()
    
    print("=" * 60)
    print("🌐 CovertDNS - Web Sender Application")
    print("=" * 60)
    print(f"\n📍 Web UI: http://{Config.HOST}:{Config.PORT}")
    print(f"📍 Database: {Config.MONGO_DB_NAME}")
    print(f"📍 DNS Port: {Config.DNS_PORT}")
    print(f"📍 Chunk Size: {Config.DNS_MAX_CHUNK_SIZE} characters")
    print("\n⚠️ FIRST TIME SETUP:")
    print("   1. Make sure MongoDB Atlas is configured in .env file")
    print("   2. Register a new account at http://localhost:5000/register")
    print("   3. Open a SEPARATE terminal as Administrator")
    print("   4. Run: python dns_tunnel.py receiver")
    print("   5. When prompted, paste the PRIVATE KEY from your account")
    print("\n🚀 Ready! Open your browser to http://localhost:5000\n")
    
    # Start the Flask-SocketIO server
    socketio.run(
        app,
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        use_reloader=False
    )