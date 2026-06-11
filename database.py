"""
Database package for CovertDNS
Using MongoDB Atlas
"""

from pymongo import MongoClient
from pymongo.errors import DuplicateKeyError
from pymongo.server_api import ServerApi
from datetime import datetime
from typing import Optional, List, Dict
import os
import bcrypt
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


class MongoDB:
    def __init__(self, connection_string: str = None, db_name: str = None):
        """
        Initialize MongoDB Atlas connection
        
        Args:
            connection_string: MongoDB Atlas connection string (from .env file)
            db_name: Database name (from .env file)
        """
        
        # Get connection string from .env if not provided
        if connection_string is None:
            connection_string = os.environ.get('MONGO_URI')
        
        if db_name is None:
            db_name = os.environ.get('MONGO_DB_NAME', 'covertdns')
        
        if not connection_string:
            raise ValueError("MONGO_URI not found in environment variables!")
        
        # Connect to MongoDB Atlas with ServerApi support
        self.client = MongoClient(
            connection_string,
            server_api=ServerApi(version='1', strict=True, deprecation_errors=True)
        )
        
        # Select database
        self.db = self.client[db_name]
        
        # Collections
        self.users = self.db['users']
        self.messages = self.db['messages']
        self.keys = self.db['keys']
        self.connections = self.db['connections']
        self.sessions = self.db['sessions']
        
        # Create indexes for better performance
        self._create_indexes()
        
        print(f"✅ MongoDB Atlas connected successfully!")
        print(f"📁 Database: {db_name}")
    
    def _create_indexes(self):
        """Create indexes for better query performance"""
        
        # Users collection
        self.users.create_index('username', unique=True)
        self.users.create_index('created_at')
        self.users.create_index('public_key')
        self.users.create_index('is_active')
        
        # Messages collection
        self.messages.create_index([('user_id', 1), ('created_at', -1)])
        self.messages.create_index([('to', 1), ('created_at', -1)])
        self.messages.create_index('is_read')
        self.messages.create_index('message_type')
        self.messages.create_index('stealth_mode')
        self.messages.create_index('created_at')
        
        # Keys collection
        self.keys.create_index([('user_id', 1), ('created_at', -1)])
        self.keys.create_index([('user_id', 1), ('is_active', 1)])
        self.keys.create_index([('user_id', 1), ('name', 1)], unique=True)
        
        # Connections collection
        self.connections.create_index([('requester', 1), ('target', 1)], unique=True)
        self.connections.create_index('requester')
        self.connections.create_index('target')
        self.connections.create_index('status')
        self.connections.create_index('created_at')
        
        # Sessions collection
        self.sessions.create_index('created_at', expireAfterSeconds=86400)
        self.sessions.create_index('user_id')
        
        print("✅ Database indexes created")
    
    # ============================================================
    # USER OPERATIONS
    # ============================================================
    
    def create_user(self, username: str, password: str, public_key: str = None, private_key: str = None) -> bool:
        """Create a new user with hashed password"""
        try:
            hashed_password = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())
            
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
        """Get user by username"""
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
        """Get user by ObjectId"""
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
        except:
            pass
        return None
    
    def verify_password(self, username: str, password: str) -> bool:
        """Verify user password"""
        user = self.users.find_one({'username': username})
        
        if user and 'password' in user:
            return bcrypt.checkpw(password.encode('utf-8'), user['password'])
        return False
    
    def update_user_keys(self, username: str, public_key: str, private_key: str) -> bool:
        """Update user's encryption keys"""
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
        """Update user's last login timestamp"""
        self.users.update_one(
            {'username': username},
            {'$set': {'last_login': datetime.utcnow()}}
        )
    
    def increment_message_count(self, username: str) -> None:
        """Increment user's message count"""
        self.users.update_one(
            {'username': username},
            {'$inc': {'message_count': 1}}
        )
    
    def get_all_users(self, exclude_username: str = None) -> List[str]:
        """Get all usernames, optionally excluding one"""
        query = {'is_active': True}
        if exclude_username:
            query['username'] = {'$ne': exclude_username}
        
        return [user['username'] for user in self.users.find(query, {'username': 1})]
    
    def delete_user(self, username: str) -> bool:
        """Delete a user and all associated data"""
        from bson import ObjectId
        
        user = self.users.find_one({'username': username})
        if not user:
            return False
        
        user_id = user['_id']
        
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
        """Save a sent message to database"""
        from bson import ObjectId
        
        message_data = {
            'user_id': ObjectId(user_id),
            'to': to_ip,
            'message': message[:1000],
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
        """Get message history for a user"""
        from bson import ObjectId
        
        messages = list(self.messages.find(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1).skip(offset).limit(limit))
        
        for msg in messages:
            msg['_id'] = str(msg['_id'])
            msg['user_id'] = str(msg['user_id'])
            msg['encrypted'] = bool(msg.get('encrypted', 1))
        
        return messages
    
    def get_message_count(self, user_id: str) -> int:
        """Get total message count for a user"""
        from bson import ObjectId
        
        return self.messages.count_documents({'user_id': ObjectId(user_id)})
    
    def delete_old_messages(self, user_id: str, keep_count: int = 100) -> int:
        """Delete old messages beyond keep_count"""
        from bson import ObjectId
        
        messages = list(self.messages.find(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1).skip(keep_count))
        
        if messages:
            ids_to_delete = [msg['_id'] for msg in messages]
            result = self.messages.delete_many({'_id': {'$in': ids_to_delete}})
            return result.deleted_count
        return 0
    
    # ============================================================
    # KEY OPERATIONS
    # ============================================================
    
    def save_key_pair(self, user_id: str, key_name: str, public_key: str, private_key: str) -> bool:
        """Save a key pair for a user"""
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
        """Set a specific key pair as active"""
        from bson import ObjectId
        
        self.keys.update_many(
            {'user_id': ObjectId(user_id)},
            {'$set': {'is_active': False}}
        )
        
        result = self.keys.update_one(
            {'_id': ObjectId(key_id), 'user_id': ObjectId(user_id)},
            {'$set': {'is_active': True}}
        )
        
        return result.modified_count > 0
    
    def get_active_keys(self, user_id: str) -> tuple:
        """Get active key pair for user"""
        from bson import ObjectId
        
        key = self.keys.find_one({
            'user_id': ObjectId(user_id),
            'is_active': True
        })
        
        if key:
            return key.get('public_key'), key.get('private_key')
        
        key = self.keys.find_one(
            {'user_id': ObjectId(user_id)}
        ).sort('created_at', -1)
        
        if key:
            return key.get('public_key'), key.get('private_key')
        
        return None, None
    
    # ============================================================
    # CONNECTION OPERATIONS
    # ============================================================
    
    def add_connection_request(self, requester: str, target: str, target_ip: str) -> bool:
        """Add a new connection request"""
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
        """Get all connections for a user"""
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
        """Approve a connection request"""
        from bson import ObjectId
        
        connection = self.connections.find_one({'_id': ObjectId(connection_id)})
        
        if not connection:
            return False, False, 'Connection not found'
        
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
        
        updated = self.connections.find_one({'_id': ObjectId(connection_id)})
        both_approved = updated['requester_approved'] and updated['target_approved']
        
        if both_approved:
            self.connections.update_one(
                {'_id': ObjectId(connection_id)},
                {'$set': {'status': 'approved'}}
            )
            return True, True, '🎉 Connection approved!'
        else:
            return True, False, '✓ Waiting for the other party to approve.'
    
    def get_approved_connections(self, username: str) -> List[Dict]:
        """Get all approved connections for a user"""
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
    # HEALTH CHECK
    # ============================================================
    
    def health_check(self) -> bool:
        """Check if database is connected"""
        try:
            self.client.admin.command('ping')
            return True
        except:
            return False
    
    def get_stats(self) -> Dict:
        """Get database statistics"""
        return {
            'users': self.users.count_documents({}),
            'messages': self.messages.count_documents({}),
            'keys': self.keys.count_documents({}),
            'connections': self.connections.count_documents({})
        }
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            print("🔒 MongoDB connection closed")


# Singleton instance
_db_instance = None


def get_db():
    """Get database singleton instance"""
    global _db_instance
    if _db_instance is None:
        _db_instance = MongoDB()
    return _db_instance


def init_db():
    """Initialize database and create indexes"""
    db = get_db()
    db._create_indexes()
    print("✅ Database initialized")
    return db


def close_db():
    """Close database connection"""
    global _db_instance
    if _db_instance:
        _db_instance.close()
        _db_instance = None