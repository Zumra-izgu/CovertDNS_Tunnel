#!/usr/bin/env python3
"""
CovertDNS - Web Sender with MongoDB
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dns_tunnel import DNSSender, generate_keys
from config import get_config
from database import get_db, init_db
from models import User

# Load configuration
Config = get_config()

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Stealth module
STEALTH_AVAILABLE = False
try:
    from stealth.traffic_simulator import StealthDNSEngine
    STEALTH_AVAILABLE = True
    logger.info("Stealth module loaded")
except ImportError:
    logger.info("Stealth module not available")

# Flask App
app = Flask(__name__)
app.config['SECRET_KEY'] = Config.SECRET_KEY
app.config['SESSION_TYPE'] = 'filesystem'

socketio = SocketIO(app, cors_allowed_origins="*")

# Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.session_protection = "strong"


@login_manager.user_loader
def load_user(user_id):
    return User.get(user_id)


# Get database instance
db = get_db()

# Global state
is_sending = {}
current_stealth_mode = {}


# ============================================================
# ROUTES
# ============================================================
@app.route('/')
@login_required
def index():
    return render_template('index.html')


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        user_data = db.get_user(username)
        
        if user_data and db.verify_password(username, password):
            user = User(user_data)
            login_user(user)
            db.update_last_login(username)
            logger.info(f"User {username} logged in")
            return redirect(url_for('index'))
        else:
            return render_template('login.html', error='Invalid username or password')
    
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        confirm_password = request.form.get('confirm_password')
        
        if password != confirm_password:
            return render_template('register.html', error='Passwords do not match')
        
        if db.get_user(username):
            return render_template('register.html', error='Username already exists')
        
        # Generate initial keys for user
        pub_b64, priv_b64 = generate_keys()
        
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
    username = current_user.username
    logout_user()
    logger.info(f"User {username} logged out")
    return redirect(url_for('login'))


@app.route('/api/keys/get', methods=['GET'])
@login_required
def api_get_keys():
    """Get current user's keys"""
    user_data = db.get_user(current_user.username)
    return jsonify({
        'public': user_data.get('public_key') or '',
        'private': user_data.get('private_key') or ''
    })


@app.route('/api/keys/generate', methods=['POST'])
@login_required
def api_generate_keys():
    """Generate new keys for current user"""
    try:
        pub_b64, priv_b64 = generate_keys()
        
        db.update_user_keys(current_user.username, pub_b64, priv_b64)
        
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
    """Load existing keys for current user"""
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
    """Get message history for current user"""
    try:
        messages = db.get_user_messages(current_user.id, limit=50)
        
        # Format messages for display
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
        logger.error(f"History error: {e}")
        return jsonify({'sent': []})


@app.route('/api/sender/send', methods=['POST'])
@login_required
def api_send_message():
    global is_sending
    
    # Get current user info
    user_id = current_user.id
    username = current_user.username
    
    data = request.json
    target_ip = data.get('target_ip', '127.0.0.1')
    message = data.get('message', '')
    encrypt = data.get('encrypt', True)
    public_key_b64 = data.get('public_key', None)
    stealth_mode = data.get('stealth_mode', current_stealth_mode.get(user_id, 'off'))
    
    if not message:
        return jsonify({'success': False, 'error': 'No message'})
    
    if is_sending.get(user_id, False):
        return jsonify({'success': False, 'error': 'Already sending'})
    
    def send_in_background():
        is_sending[user_id] = True
        try:
            sender = DNSSender(target_ip, public_key_b64 if public_key_b64 else None)
            
            # Setup stealth mode
            stealth_engine = None
            if stealth_mode != 'off' and STEALTH_AVAILABLE:
                stealth_engine = StealthDNSEngine()
                stealth_engine.start_stealth_mode(stealth_mode)
                sender.set_stealth_engine(stealth_engine)
            
            # Progress tracking
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
            
            # Send message
            success = sender.send_message(message)
            
            # Cleanup
            if stealth_engine:
                stealth_engine.stop_stealth_mode()
            sender.close()
            
            if success:
                # Save to database using username
                db.save_message(user_id, target_ip, message, encrypt, stealth_mode)
                db.increment_message_count(username)
                
                # Emit to client
                socketio.emit('message_sent', {
                    'to': target_ip,
                    'message': message[:100]
                }, room=user_id)
                
                # Emit history update
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
    
    thread = threading.Thread(target=send_in_background)
    thread.start()
    
    return jsonify({'success': True})


@app.route('/api/status', methods=['GET'])
@login_required
def api_get_status():
    message_count = db.get_message_count(current_user.id)
    
    return jsonify({
        'port': Config.DNS_PORT,
        'domain': Config.DNS_BASE_DOMAIN,
        'chunk_size': Config.DNS_MAX_CHUNK_SIZE,
        'sent_count': message_count,
        'stealth_available': STEALTH_AVAILABLE,
        'username': current_user.username
    })


@socketio.on('connect')
def handle_connect():
    if current_user.is_authenticated:
        user_id = str(current_user.id)
        join_room(user_id)
        logger.info(f"User {current_user.username} connected")
        
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
        
        # Send history on connect
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
    if current_user.is_authenticated:
        leave_room(str(current_user.id))
        logger.info(f"User {current_user.username} disconnected")


if __name__ == '__main__':
    for folder in ['templates', 'static/css', 'static/js']:
        if not os.path.exists(folder):
            os.makedirs(folder)
    
    print("=" * 60)
    print("🌐 CovertDNS - Web Sender with MongoDB")
    print("=" * 60)
    print(f"\n📍 Web UI: http://{Config.HOST}:{Config.PORT}")
    print(f"📍 Database: {Config.MONGO_DB_NAME}")
    print(f"📍 DNS Port: {Config.DNS_PORT}")
    print("\n⚠️ FIRST:")
    print("   1. Make sure MongoDB Atlas is configured in .env")
    print("   2. Register a new account")
    print("   3. Open a SEPARATE terminal as Administrator")
    print("   4. Run: python dns_tunnel.py receiver")
    print("   5. When prompted, paste the PRIVATE KEY from your account")
    print("\n🚀 Ready! Open browser to http://localhost:5000\n")
    
    socketio.run(
        app,
        host=Config.HOST,
        port=Config.PORT,
        debug=False,
        use_reloader=False
    )