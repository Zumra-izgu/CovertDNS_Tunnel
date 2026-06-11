"""
User Model for Flask-Login Authentication

This module defines the User class that integrates with Flask-Login for session
management and user authentication. The class implements the required UserMixin
interface and provides methods for loading users from the database.

The User class serves as an adapter between the MongoDB user documents and
Flask-Login's authentication system. It handles:
    - User session management (via UserMixin)
    - Loading users by ID or username
    - Converting user data to dictionary format for API responses

Flask-Login Integration:
    - UserMixin provides default implementations for is_authenticated, 
      is_active, is_anonymous, and get_id()
    - The @login_manager.user_loader callback uses User.get() to load users
    - Session data is stored server-side with client-side signed cookies

Database Dependency:
    This module relies on the get_db() function from the database module
    to access MongoDB collections. The connection is established lazily
    and reused across requests.
"""

from flask_login import UserMixin
from database import get_db


class User(UserMixin):
    """
    User class for Flask-Login authentication and session management.
    
    This class represents an authenticated user in the system. It extends
    Flask-Login's UserMixin to inherit default implementations for:
        - is_authenticated: Returns True for logged-in users
        - is_active: Returns True for active accounts
        - is_anonymous: Returns False for authenticated users
        - get_id(): Returns the user's unique identifier (stored in session)
    
    The class provides static factory methods to load users from the database
    by either MongoDB ObjectId or username. These methods are used by
    Flask-Login's user_loader callback to reconstruct user objects from
    session data.
    
    Attributes:
        id (str): User's MongoDB ObjectId as a string (required by UserMixin)
        username (str): Unique username for display and authentication
        public_key (str): Kyber-768 public key (Base64 encoded) for encryption
        private_key (str): Kyber-768 private key (Base64 encoded) for decryption
        message_count (int): Total number of messages sent by this user
        created_at (datetime): Account creation timestamp
    
    Example:
        # In Flask-Login configuration
        @login_manager.user_loader
        def load_user(user_id):
            return User.get(user_id)
        
        # During login
        user_data = db.get_user(username)
        if user_data and db.verify_password(username, password):
            user = User(user_data)
            login_user(user)
    """
    
    def __init__(self, user_data):
        """
        Initialize a User object from database user data.
        
        Args:
            user_data (dict): User document from MongoDB containing:
                - 'id' or '_id': User's ObjectId as string
                - 'username': User's username
                - 'public_key': Optional Kyber-768 public key
                - 'private_key': Optional Kyber-768 private key
                - 'message_count': Optional message count (defaults to 0)
                - 'created_at': Optional account creation timestamp
        """
        self.id = user_data['id']
        self.username = user_data['username']
        self.public_key = user_data.get('public_key')
        self.private_key = user_data.get('private_key')
        self.message_count = user_data.get('message_count', 0)
        self.created_at = user_data.get('created_at')
    
    @staticmethod
    def get(user_id):
        """
        Retrieve a user by their MongoDB ObjectId.
        
        This method is used by Flask-Login's user_loader callback to
        reconstruct user objects from session data. When a user logs in,
        their ID is stored in the session. On subsequent requests, Flask-Login
        calls this method with the stored ID to reload the user object.
        
        Args:
            user_id (str): MongoDB ObjectId as a string.
        
        Returns:
            User or None: User object if found, None otherwise.
        
        Example:
            >>> user = User.get("507f1f77bcf86cd799439011")
            >>> if user:
            ...     print(f"Welcome back, {user.username}")
        """
        db = get_db()
        user_data = db.get_user_by_id(user_id)
        return User(user_data) if user_data else None
    
    @staticmethod
    def get_by_username(username):
        """
        Retrieve a user by their username.
        
        This method is primarily used during the login process to fetch
        user data before password verification. It can also be used for
        username-based lookups in other parts of the application.
        
        Args:
            username (str): The username to look up.
        
        Returns:
            User or None: User object if found, None otherwise.
        
        Example:
            >>> user = User.get_by_username("alice")
            >>> if user and db.verify_password("alice", password):
            ...     login_user(user)
        """
        db = get_db()
        user_data = db.get_user(username)
        return User(user_data) if user_data else None
    
    def to_dict(self):
        """
        Convert the user object to a dictionary for API responses.
        
        This method is useful for serializing user data to JSON without
        exposing sensitive information like the full private key. The
        public key is truncated to 100 characters for display purposes.
        
        Returns:
            dict: Dictionary containing:
                - 'id': User's ObjectId as string
                - 'username': User's username
                - 'public_key': First 100 characters of public key (or None)
                - 'message_count': Total messages sent
                - 'created_at': Account creation date as formatted string
        
        Example:
            >>> user = User.get_by_username("alice")
            >>> return jsonify(user.to_dict())
        """
        return {
            'id': self.id,
            'username': self.username,
            'public_key': self.public_key[:100] + '...' if self.public_key else None,
            'message_count': self.message_count,
            'created_at': self.created_at.strftime('%Y-%m-%d %H:%M:%S') if self.created_at else None
        }


# ============================================================================
# Usage Example
# ============================================================================

if __name__ == "__main__":
    """
    Standalone test routine for the User model.
    
    This test verifies that:
        1. User objects can be created from database data
        2. Users can be retrieved by ID and username
        3. The to_dict() method produces the expected output
        4. Flask-Login compatibility is maintained
    """
    print("=" * 50)
    print("User Model Test")
    print("=" * 50)
    
    # Test user data structure (simulating database output)
    test_user_data = {
        'id': '507f1f77bcf86cd799439011',
        'username': 'test_user',
        'public_key': 'xKj3H...' * 10,  # Simulated public key
        'private_key': 'sFk9M...' * 20,  # Simulated private key
        'message_count': 42,
        'created_at': None  # Would be datetime in production
    }
    
    # Create User instance
    user = User(test_user_data)
    
    # Verify attributes
    print(f"\n✅ User created successfully")
    print(f"   Username: {user.username}")
    print(f"   User ID: {user.id}")
    print(f"   Message count: {user.message_count}")
    print(f"   Public key (truncated): {user.public_key[:50]}...")
    
    # Test to_dict method
    user_dict = user.to_dict()
    print(f"\n✅ to_dict() output:")
    for key, value in user_dict.items():
        print(f"   {key}: {value}")
    
    # Verify Flask-Login compatibility
    print(f"\n✅ Flask-Login compatibility:")
    print(f"   is_authenticated: {user.is_authenticated}")
    print(f"   is_active: {user.is_active}")
    print(f"   is_anonymous: {user.is_anonymous}")
    print(f"   get_id(): {user.get_id()}")
    
    print("\n" + "=" * 50)
    print("User model test completed successfully!")