"""
User Model for Flask-Login
"""

from flask_login import UserMixin
from database import get_db


class User(UserMixin):
    """User class for Flask-Login"""
    
    def __init__(self, user_data):
        self.id = user_data['id']
        self.username = user_data['username']
        self.public_key = user_data.get('public_key')
        self.private_key = user_data.get('private_key')
        self.message_count = user_data.get('message_count', 0)
        self.created_at = user_data.get('created_at')
    
    @staticmethod
    def get(user_id):
        """Get user by ID"""
        db = get_db()
        user_data = db.get_user_by_id(user_id)
        return User(user_data) if user_data else None
    
    @staticmethod
    def get_by_username(username):
        """Get user by username"""
        db = get_db()
        user_data = db.get_user(username)
        return User(user_data) if user_data else None
    
    def to_dict(self):
        """Convert user to dictionary"""
        return {
            'id': self.id,
            'username': self.username,
            'public_key': self.public_key[:100] + '...' if self.public_key else None,
            'message_count': self.message_count,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }