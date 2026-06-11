"""
Database package for CovertDNS
MongoDB Atlas database manager for users, messages, keys, and connections

This module provides a complete database interface for the CovertDNS application,
handling all CRUD operations for user accounts, message persistence, cryptographic
key storage, peer-to-peer connections, and session management.

The database uses MongoDB Atlas for cloud-based storage with automatic backups,
high availability, and no local infrastructure requirements.

Collections:
    - users: User account information and authentication
    - messages: Message history with encryption metadata
    - keys: Multiple key pairs per user (for key rotation)
    - connections: Peer-to-peer connection management with mutual approval
    - sessions: User session tracking with automatic expiration
"""

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pymongo.server_api import ServerApi
from datetime import datetime
from typing import Optional, List, Dict
import os
import bcrypt
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()


class MongoDB:
    """
    MongoDB Atlas database manager for CovertDNS.
    
    This class provides a comprehensive interface for all database operations,
    including user management, message persistence, key storage, connection
    management, and session handling.
    
    The class follows the singleton pattern through the get_db() function
    to ensure a single connection pool is reused across the application.
    
    Attributes:
        client (MongoClient): MongoDB Atlas client connection
        db (Database): Reference to the selected database
        users (Collection): Users collection
        messages (Collection): Messages collection
        keys (Collection): Keys collection
        connections (Collection): Connections collection
        sessions (Collection): Sessions collection
    """
    
    def __init__(self, connection_string: str = None, db_name: str = None):
        """
        Initialize MongoDB Atlas connection.
        
        Args:
            connection_string: MongoDB Atlas connection string (from .env file)
            db_name: Database name (from .env file)
            
        Raises:
            ValueError: If MONGO_URI is not found in environment variables
        """
        
        # Get connection string from .env if not provided
        if connection_string is None:
            connection_string = os.environ.get('MONGO_URI')
        
        if db_name is None:
            db_name = os.environ.get('MONGO_DB_NAME', 'covertdns')
        
        if not connection_string:
            raise ValueError("MONGO_URI not found in environment variables!")
        
        # Connect to MongoDB Atlas with ServerApi support
        # ServerApi ensures compatibility with MongoDB Atlas API version
        self.client = MongoClient(
            connection_string,
            server_api=ServerApi(version='1', strict=True, deprecation_errors=True)
        )
        
        # Select the target database
        self.db = self.client[db_name]
        
        # Initialize collection references
        self.users = self.db['users']
        self.messages = self.db['messages']
        self.keys = self.db['keys']
        self.connections = self.db['connections']
        self.sessions = self.db['sessions']
        
        # Create indexes for optimal query performance
        self._create_indexes()
        
        print(f"✅ MongoDB Atlas connected successfully!")
        print(f"📁 Database: {db_name}")
    
    def _create_indexes(self):
        """
        Create database indexes for better query performance.
        
        Indexes are essential for:
            - Fast user lookup by username
            - Efficient message history retrieval
            - Quick key pair lookups
            - Connection status queries
            - Automatic session expiration
        
        Each index is created with appropriate uniqueness constraints
        where applicable to prevent duplicate data.
        """
        
        # ============================================================
        # Users Collection Indexes
        # ============================================================
        
        # Username must be unique - prevents duplicate accounts
        self.users.create_index('username', unique=True)
        
        # For sorting users by registration date (admin panel)
        self.users.create_index('created_at')
        
        # For key-based lookups when searching by public key
        self.users.create_index('public_key')
        
        # For filtering active/inactive users
        self.users.create_index('is_active')
        
        # ============================================================
        # Messages Collection Indexes
        # ============================================================
        
        # Compound index for fast user message history queries
        # Sorts by creation date descending (most recent first)
        self.messages.create_index([('user_id', 1), ('created_at', -1)])
        
        # For recipient-based message lookups
        self.messages.create_index([('to', 1), ('created_at', -1)])
        
        # For unread message counts and filtering
        self.messages.create_index('is_read')
        
        # For filtering by message type (text, voice, file)
        self.messages.create_index('message_type')
        
        # For filtering by stealth mode used during transmission
        self.messages.create_index('stealth_mode')
        
        # For general time-based queries and aggregations
        self.messages.create_index('created_at')
        
        # ============================================================
        # Keys Collection Indexes
        # ============================================================
        
        # For retrieving key history for a user
        self.keys.create_index([('user_id', 1), ('created_at', -1)])
        
        # For finding the currently active key pair for a user
        self.keys.create_index([('user_id', 1), ('is_active', 1)])
        
        # Ensure each user has unique key names (no duplicate "default", "work", etc.)
        self.keys.create_index([('user_id', 1), ('name', 1)], unique=True)
        
        # ============================================================
        # Connections Collection Indexes
        # ============================================================
        
        # Unique compound index prevents duplicate connection requests
        self.connections.create_index([('requester', 1), ('target', 1)], unique=True)
        
        # For finding all connections where user is requester
        self.connections.create_index('requester')
        
        # For finding all connections where user is target
        self.connections.create_index('target')
        
        # For filtering connections by status (pending, approved, rejected)
        self.connections.create_index('status')
        
        # For sorting connections by creation date
        self.connections.create_index('created_at')
        
        # ============================================================
        # Sessions Collection Indexes
        # ============================================================
        
        # TTL (Time-To-Live) index for automatic session expiration
        # Sessions are automatically deleted after 86,400 seconds (24 hours)
        self.sessions.create_index('created_at', expireAfterSeconds=86400)
        
        # For finding all sessions belonging to a user
        self.sessions.create_index('user_id')
        
        print("✅ Database indexes created")
    
    # ============================================================
    # USER OPERATIONS
    # ============================================================
    
    def create_user(self, username: str, password: str, 
                    public_key: str = None, private_key: str = None) -> bool:
        """
        Create a new user with a hashed password and optional cryptographic keys.
        
        The password is hashed using bcrypt with a randomly generated salt.
        This ensures that even if the database is compromised, passwords
        cannot be easily recovered.
        
        Args:
            username: Unique username for the new account
            password: Plain text password (will be hashed before storage)
            public_key: User's Kyber-768 public key (Base64 encoded)
            private_key: User's Kyber-768 private key (Base64 encoded)
        
        Returns:
            bool: True if user was created successfully, False if username already exists
        
        Example:
            >>> db.create_user("alice", "secure_password", pub_b64, priv_b64)
            True
        """
        try:
            # Hash the password with bcrypt (automatically generates salt)
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            
            # Create user document
            user_data = {
                'username': username,
                'password': hashed_password,
                'public_key': public_key,
                'private_key': private_key,
                'message_count': 0,
                'is_active': True,
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow(),
                'last_login': None
            }
            
            self.users.insert_one(user_data)
            print(f"✅ User created: {username}")
            return True
            
        except DuplicateKeyError:
            print(f"❌ User already exists: {username}")
            return False
    
    def get_user(self, username: str) -> Optional[Dict]:
        """
        Retrieve a user by their username.
        
        Args:
            username: Username to look up
        
        Returns:
            dict: User document with string ID, or None if not found
        
        Example:
            >>> user = db.get_user("alice")
            >>> print(user['public_key'])
        """
        user = self.users.find_one({'username': username})
        
        if user:
            return {
                'id': str(user['_id']),
                'username': user['username'],
                'password': user['password'],
                'public_key': user.get('public_key'),
                'private_key': user.get('private_key'),
                'message_count': user.get('message_count', 0),
                'is_active': user.get('is_active', True),
                'created_at': user['created_at'],
                'last_login': user.get('last_login')
            }
        return None
    
    def get_user_by_id(self, user_id: str) -> Optional[Dict]:
        """
        Retrieve a user by their MongoDB ObjectId.
        
        Args:
            user_id: MongoDB ObjectId as string
        
        Returns:
            dict: User document with string ID, or None if not found
        """
        from bson import ObjectId
        
        try:
            user = self.users.find_one({'_id': ObjectId(user_id)})
            if user:
                return {
                    'id': str(user['_id']),
                    'username': user['username'],
                    'public_key': user.get('public_key'),
                    'private_key': user.get('private_key'),
                    'message_count': user.get('message_count', 0),
                    'created_at': user['created_at']
                }
        except Exception:
            pass
        return None
    
    def verify_password(self, username: str, password: str) -> bool:
        """
        Verify a user's password against the stored hash.
        
        Args:
            username: Username to authenticate
            password: Plain text password to verify
        
        Returns:
            bool: True if password matches, False otherwise
        """
        user = self.users.find_one({'username': username})
        
        if user and 'password' in user:
            return bcrypt.checkpw(password.encode('utf-8'), user['password'])
        return False
    
    def update_user_keys(self, username: str, public_key: str, private_key: str) -> bool:
        """
        Update a user's cryptographic key pair.
        
        Args:
            username: Username whose keys to update
            public_key: New Kyber-768 public key (Base64 encoded)
            private_key: New Kyber-768 private key (Base64 encoded)
        
        Returns:
            bool: True if keys were updated successfully
        """
        result = self.users.update_one(
            {'username': username},
            {
                '$set': {
                    'public_key': public_key,
                    'private_key': private_key,
                    'updated_at': datetime.utcnow()
                }
            }
        )
        return result.modified_count > 0
    
    def update_last_login(self, username: str) -> None:
        """
        Update the last login timestamp for a user.
        
        Args:
            username: Username who just logged in
        """
        self.users.update_one(
            {'username': username},
            {'$set': {'last_login': datetime.utcnow()}}
        )
    
    def increment_message_count(self, username: str) -> None:
        """
        Increment the message count for a user.
        
        Args:
            username: Username who sent a message
        """
        self.users.update_one(
            {'username': username},
            {'$inc': {'message_count': 1}}
        )
    
    def get_all_users(self, exclude_username: str = None) -> List[str]:
        """
        Get a list of all active usernames.
        
        Args:
            exclude_username: Optional username to exclude from results
        
        Returns:
            list: List of usernames (strings)
        """
        query = {'is_active': True}
        if exclude_username:
            query['username'] = {'$ne': exclude_username}
        
        return [user['username'] for user in self.users.find(query, {'username': 1})]
    
    def delete_user(self, username: str) -> bool:
        """
        Delete a user and all associated data (cascade delete).
        
        This method removes:
            - The user document
            - All messages sent by the user
            - All key pairs belonging to the user
            - All connection requests involving the user
        
        Args:
            username: Username to delete
        
        Returns:
            bool: True if user was deleted successfully
        """
        from bson import ObjectId
        
        user = self.users.find_one({'username': username})
        if not user:
            return False
        
        user_id = user['_id']
        
        # Delete in reverse order (dependents first)
        self.users.delete_one({'username': username})
        self.messages.delete_many({'user_id': user_id})
        self.keys.delete_many({'user_id': user_id})
        self.connections.delete_many({
            '$or': [
                {'requester': username},
                {'target': username}
            ]
        })
        
        return True
    
    # ============================================================
    # MESSAGE OPERATIONS
    # ============================================================
    
    def save_message(self, user_id: str, to_ip: str, message: str,
                     encrypted: bool = True, stealth_mode: str = 'off',
                     message_type: str = 'text') -> str:
        """
        Save a sent message to the database.
        
        Args:
            user_id: Sender's user ID (ObjectId as string)
            to_ip: Target IP address where the message was sent
            message: Message content (automatically truncated to 1000 chars)
            encrypted: Whether the message was encrypted (default: True)
            stealth_mode: Stealth mode used ('off', 'low', 'normal', 'high')
            message_type: Type of message ('text', 'voice', 'file')
        
        Returns:
            str: ID of the inserted message document
        """
        from bson import ObjectId
        
        message_data = {
            'user_id': ObjectId(user_id),
            'to': to_ip,
            'message': message[:1000],  # Limit message length to 1000 characters
            'encrypted': 1 if encrypted else 0,
            'stealth_mode': stealth_mode,
            'message_type': message_type,
            'is_read': False,
            'created_at': datetime.utcnow()
        }
        
        result = self.messages.insert_one(message_data)
        
        # Increment user's message count
        self.users.update_one(
            {'_id': ObjectId(user_id)},
            {'$inc': {'message_count': 1}}
        )
        
        return str(result.inserted_id)
    
    def get_user_messages(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict]:
        """
        Get message history for a user with pagination support.
        
        Args:
            user_id: User's ObjectId as string
            limit: Maximum number of messages to return (default: 50)
            offset: Number of messages to skip for pagination (default: 0)
        
        Returns:
            list: List of message documents with string IDs
        """
        from bson import ObjectId
        
        messages = list(self.messages.find(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1).skip(offset).limit(limit))
        
        # Convert ObjectId to string for JSON serialization
        for msg in messages:
            msg['_id'] = str(msg['_id'])
            msg['user_id'] = str(msg['user_id'])
            msg['encrypted'] = bool(msg.get('encrypted', 1))
        
        return messages
    
    def get_message_count(self, user_id: str) -> int:
        """
        Get the total number of messages sent by a user.
        
        Args:
            user_id: User's ObjectId as string
        
        Returns:
            int: Total message count
        """
        from bson import ObjectId
        
        return self.messages.count_documents({'user_id': ObjectId(user_id)})
    
    def delete_old_messages(self, user_id: str, keep_count: int = 100) -> int:
        """
        Delete old messages beyond the keep_count limit.
        
        This method is useful for automatic cleanup of message history
        to prevent the database from growing indefinitely.
        
        Args:
            user_id: User's ObjectId as string
            keep_count: Number of most recent messages to keep
        
        Returns:
            int: Number of messages deleted
        """
        from bson import ObjectId
        
        # Find messages to delete (skip the most recent 'keep_count' messages)
        messages = list(self.messages.find(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1).skip(keep_count))
        
        if messages:
            ids_to_delete = [msg['_id'] for msg in messages]
            result = self.messages.delete_many({'_id': {'$in': ids_to_delete}})
            return result.deleted_count
        return 0
    
    # ============================================================
    # KEY OPERATIONS (Multiple key pairs per user)
    # ============================================================
    
    def save_key_pair(self, user_id: str, key_name: str, 
                      public_key: str, private_key: str) -> bool:
        """
        Save a new key pair for a user (for key rotation).
        
        Args:
            user_id: User's ObjectId as string
            key_name: Name for this key pair (e.g., "default", "work", "personal")
            public_key: Kyber-768 public key (Base64 encoded)
            private_key: Kyber-768 private key (Base64 encoded)
        
        Returns:
            bool: True if key pair was saved successfully
        """
        from bson import ObjectId
        
        try:
            key_data = {
                'user_id': ObjectId(user_id),
                'name': key_name,
                'public_key': public_key,
                'private_key': private_key,
                'is_active': False,
                'created_at': datetime.utcnow()
            }
            
            self.keys.insert_one(key_data)
            return True
        except DuplicateKeyError:
            return False
    
    def set_active_key(self, user_id: str, key_id: str) -> bool:
        """
        Set a specific key pair as the active one for a user.
        
        Only one key pair can be active per user at any time.
        
        Args:
            user_id: User's ObjectId as string
            key_id: ID of the key pair to activate
        
        Returns:
            bool: True if key was activated successfully
        """
        from bson import ObjectId
        
        # Deactivate all keys for this user first
        self.keys.update_many(
            {'user_id': ObjectId(user_id)},
            {'$set': {'is_active': False}}
        )
        
        # Activate the selected key
        result = self.keys.update_one(
            {'_id': ObjectId(key_id), 'user_id': ObjectId(user_id)},
            {'$set': {'is_active': True}}
        )
        
        return result.modified_count > 0
    
    def get_active_keys(self, user_id: str) -> tuple:
        """
        Get the currently active key pair for a user.
        
        If no key is marked as active, returns the most recently created key.
        
        Args:
            user_id: User's ObjectId as string
        
        Returns:
            tuple: (public_key, private_key) or (None, None) if no keys exist
        """
        from bson import ObjectId
        
        # First try to find an explicitly active key
        key = self.keys.find_one({
            'user_id': ObjectId(user_id),
            'is_active': True
        })
        
        if key:
            return key.get('public_key'), key.get('private_key')
        
        # Fall back to the most recently created key
        key = self.keys.find_one(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1)
        
        if key:
            return key.get('public_key'), key.get('private_key')
        
        return None, None
    
    # ============================================================
    # CONNECTION OPERATIONS (Mutual Approval System)
    # ============================================================
    
    def add_connection_request(self, requester: str, target: str, target_ip: str) -> bool:
        """
        Add a new connection request from requester to target.
        
        Args:
            requester: Username initiating the connection
            target: Target username
            target_ip: IP address of the target
        
        Returns:
            bool: True if request was added successfully
        """
        try:
            self.connections.insert_one({
                'requester': requester,
                'target': target,
                'target_ip': target_ip,
                'requester_approved': True,
                'target_approved': False,
                'status': 'pending',
                'created_at': datetime.utcnow(),
                'updated_at': datetime.utcnow()
            })
            return True
        except DuplicateKeyError:
            return False
    
    def get_connections(self, username: str) -> List[Dict]:
        """
        Get all connections for a user (both as requester and target).
        
        Args:
            username: Username to get connections for
        
        Returns:
            list: List of connection documents with status information
        """
        connections = list(self.connections.find({
            '$or': [
                {'requester': username},
                {'target': username}
            ]
        }).sort('created_at', -1))
        
        result = []
        for conn in connections:
            is_requester = (conn['requester'] == username)
            other_party = conn['target'] if is_requester else conn['requester']
            
            # Determine display status based on approval state
            if conn['requester_approved'] and conn['target_approved']:
                display_status = 'approved'
            elif is_requester and conn['requester_approved']:
                display_status = 'waiting_other'
            elif not is_requester and conn['target_approved']:
                display_status = 'waiting_other'
            elif not is_requester and conn['requester_approved'] and not conn['target_approved']:
                display_status = 'pending_request'
            else:
                display_status = 'pending'
            
            result.append({
                'id': str(conn['_id']),
                'name': other_party,
                'ip': conn.get('target_ip') if is_requester else None,
                'status': display_status,
                'is_requester': is_requester,
                'created_at': conn['created_at']
            })
        
        return result
    
    def approve_connection(self, connection_id: str, username: str) -> tuple:
        """
        Approve a pending connection request.
        
        Args:
            connection_id: ID of the connection to approve
            username: Username approving the request
        
        Returns:
            tuple: (success, both_approved, message)
        """
        from bson import ObjectId
        
        connection = self.connections.find_one({'_id': ObjectId(connection_id)})
        
        if not connection:
            return False, False, 'Connection not found'
        
        # Mark the appropriate party as approved
        if username == connection['requester']:
            self.connections.update_one(
                {'_id': ObjectId(connection_id)},
                {'$set': {'requester_approved': True, 'updated_at': datetime.utcnow()}}
            )
        elif username == connection['target']:
            self.connections.update_one(
                {'_id': ObjectId(connection_id)},
                {'$set': {'target_approved': True, 'updated_at': datetime.utcnow()}}
            )
        else:
            return False, False, 'Unauthorized'
        
        # Check if both parties have approved
        updated = self.connections.find_one({'_id': ObjectId(connection_id)})
        both_approved = updated['requester_approved'] and updated['target_approved']
        
        if both_approved:
            self.connections.update_one(
                {'_id': ObjectId(connection_id)},
                {'$set': {'status': 'approved'}}
            )
            return True, True, '🎉 Connection approved! You can now exchange messages.'
        else:
            return True, False, '✓ You approved this connection. Waiting for the other party to approve.'
    
    def get_approved_connections(self, username: str) -> List[Dict]:
        """
        Get all approved connections for a user.
        
        Args:
            username: Username to get approved connections for
        
        Returns:
            list: List of approved connections with peer information
        """
        connections = self.connections.find({
            '$or': [
                {'requester': username},
                {'target': username}
            ],
            'requester_approved': True,
            'target_approved': True
        })
        
        result = []
        for conn in connections:
            if conn['requester'] == username:
                other_party = conn['target']
                other_ip = conn['target_ip']
            else:
                other_party = conn['requester']
                other_ip = conn['target_ip']
            
            result.append({
                'id': str(conn['_id']),
                'name': other_party,
                'ip': other_ip
            })
        
        return result
    
    # ============================================================
    # HEALTH CHECK AND UTILITIES
    # ============================================================
    
    def health_check(self) -> bool:
        """
        Check if the database connection is healthy.
        
        Returns:
            bool: True if connection is healthy, False otherwise
        """
        try:
            self.client.admin.command('ping')
            return True
        except Exception:
            return False
    
    def get_stats(self) -> Dict:
        """
        Get database statistics including document counts.
        
        Returns:
            dict: Statistics for each collection
        """
        return {
            'users': self.users.count_documents({}),
            'messages': self.messages.count_documents({}),
            'keys': self.keys.count_documents({}),
            'connections': self.connections.count_documents({})
        }
    
    def close(self):
        """Close the MongoDB connection gracefully."""
        if self.client:
            self.client.close()
            print("🔒 MongoDB connection closed")


# ============================================================================
# Singleton Pattern for Database Access
# ============================================================================

_db_instance = None


def get_db():
    """
    Get the singleton database instance.
    
    This function ensures that only one database connection is created
    and reused throughout the application.
    
    Returns:
        MongoDB: The singleton database instance
    
    Example:
        >>> db = get_db()
        >>> user = db.get_user("alice")
    """
    global _db_instance
    if _db_instance is None:
        _db_instance = MongoDB()
    return _db_instance


def init_db():
    """
    Initialize the database and create indexes.
    
    Call this during application startup to ensure all indexes exist.
    
    Returns:
        MongoDB: The initialized database instance
    """
    db = get_db()
    db._create_indexes()
    print("✅ Database initialized")
    return db


def close_db():
    """
    Close the database connection.
    
    Call this during application shutdown to clean up resources.
    """
    global _db_instance
    if _db_instance:
        _db_instance.close()
        _db_instance = None