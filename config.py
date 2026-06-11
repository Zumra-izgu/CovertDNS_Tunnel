"""
Configuration Module for CovertDNS

This module loads environment variables from a .env file and provides
a centralized configuration class for the entire application. All
settings are accessed through the Config class, ensuring consistency
across different modules.

Security Note:
    - Sensitive information (passwords, keys) should never be hardcoded
    - Always use .env files for development and environment variables for production
    - The .env file must NOT be committed to version control

Usage Example:
    from config import get_config
    
    config = get_config()
    print(f"Server running on {config.HOST}:{config.PORT}")
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# ============================================================================
# Environment Variable Loading
# ============================================================================

# Locate and load the .env file from the parent directory
# This file contains all sensitive configuration values
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


class Config:
    """
    Application configuration loaded from environment variables.
    
    All configuration values have sensible defaults, but can be overridden
    by setting environment variables or adding them to the .env file.
    
    Configuration Categories:
        - Flask: Web server settings
        - MongoDB: Database connection settings
        - DNS Tunnel: Covert channel parameters
    """
    
    # ========================================================================
    # Flask Web Server Configuration
    # ========================================================================
    
    # Secret key for session management and CSRF protection
    # Should be a long, random string in production
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'covertdns-secret-key')
    
    # Host address to bind the web server to
    # - '127.0.0.1': Only accessible from localhost (recommended for development)
    # - '0.0.0.0': Accessible from any network interface (use with caution)
    HOST = os.getenv('FLASK_HOST', '127.0.0.1')
    
    # Port number for the web server (default: 5000)
    PORT = int(os.getenv('FLASK_PORT', 5000))
    
    # ========================================================================
    # MongoDB Database Configuration
    # ========================================================================
    
    # MongoDB connection string
    # Format for local: mongodb://localhost:27017/
    # Format for Atlas: mongodb+srv://username:password@cluster.xxxxx.mongodb.net/
    # Must be set in .env file
    MONGO_URI = os.getenv('MONGO_URI')
    
    # Name of the database to use within the MongoDB instance
    MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'covertdns')
    
    # ========================================================================
    # DNS Tunnel Configuration
    # ========================================================================
    
    # UDP port for DNS communication
    # Port 53 is the standard DNS port and requires administrator privileges
    # Alternative ports (e.g., 5353) can be used for testing without admin rights
    DNS_PORT = int(os.getenv('DNS_PORT', 53))
    
    # Base domain name for tunneling queries
    # All covert messages are sent as subdomains of this domain
    # Format: <seq>.<chunk>.<base_domain>
    DNS_BASE_DOMAIN = os.getenv('DNS_BASE_DOMAIN', 'covert.local')
    
    # Maximum size of each DNS query label in characters
    # DNS labels are limited to 63 characters per RFC 1035;
    # Using 45 provides a safety margin for encoding overhead
    DNS_MAX_CHUNK_SIZE = int(os.getenv('DNS_MAX_CHUNK_SIZE', 45))


def get_config():
    """
    Get the application configuration instance.
    
    Returns:
        Config: The configuration class with all settings loaded.
    
    Example:
        >>> config = get_config()
        >>> print(config.DNS_PORT)
        53
    """
    return Config


# ============================================================================
# Configuration Validation
# ============================================================================

def validate_config():
    """
    Validate critical configuration values.
    
    Checks for required settings and warns about potential issues.
    Call this during application startup to ensure everything is configured
    correctly.
    
    Returns:
        bool: True if configuration is valid, False otherwise.
    """
    config = get_config()
    valid = True
    
    # Check MongoDB connection string (required)
    if not config.MONGO_URI:
        print("⚠️ WARNING: MONGO_URI not set in .env file!")
        print("   MongoDB functionality will not work.")
        valid = False
    
    # Validate port range
    if config.PORT < 1 or config.PORT > 65535:
        print(f"❌ ERROR: Invalid PORT value: {config.PORT}")
        valid = False
    
    # Validate DNS port
    if config.DNS_PORT < 1 or config.DNS_PORT > 65535:
        print(f"❌ ERROR: Invalid DNS_PORT value: {config.DNS_PORT}")
        valid = False
    
    # Validate chunk size
    if config.DNS_MAX_CHUNK_SIZE < 1 or config.DNS_MAX_CHUNK_SIZE > 63:
        print(f"⚠️ WARNING: DNS_MAX_CHUNK_SIZE should be between 1 and 63 (RFC 1035)")
        print(f"   Current value: {config.DNS_MAX_CHUNK_SIZE}")
    
    if valid:
        print("✅ Configuration validation passed")
    
    return valid


if __name__ == "__main__":
    """
    Standalone test routine for configuration loading.
    
    This test verifies that:
        1. The .env file is loaded correctly
        2. All configuration values are properly parsed
        3. Critical settings are present
    """
    print("=" * 50)
    print("Configuration Module Test")
    print("=" * 50)
    
    config = get_config()
    
    print("\n📋 Loaded Configuration:")
    print(f"   Flask Host: {config.HOST}")
    print(f"   Flask Port: {config.PORT}")
    print(f"   MongoDB URI: {'[SET]' if config.MONGO_URI else '[NOT SET]'}")
    print(f"   MongoDB Database: {config.MONGO_DB_NAME}")
    print(f"   DNS Port: {config.DNS_PORT}")
    print(f"   DNS Base Domain: {config.DNS_BASE_DOMAIN}")
    print(f"   DNS Max Chunk Size: {config.DNS_MAX_CHUNK_SIZE}")
    
    print("\n" + "=" * 50)
    validate_config()