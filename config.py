"""
Configuration Module for CovertDNS
"""

import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(env_path)


class Config:
    """Configuration from .env"""
    
    # Flask
    SECRET_KEY = os.getenv('FLASK_SECRET_KEY', 'covertdns-secret-key')
    HOST = os.getenv('FLASK_HOST', '127.0.0.1')  # 0.0.0.0 yerine 127.0.0.1
    PORT = int(os.getenv('FLASK_PORT', 5000))
    
    # MongoDB (from .env)
    MONGO_URI = os.getenv('MONGO_URI')
    MONGO_DB_NAME = os.getenv('MONGO_DB_NAME', 'covertdns')
    
    # DNS Tunnel
    DNS_PORT = int(os.getenv('DNS_PORT', 53))
    DNS_BASE_DOMAIN = os.getenv('DNS_BASE_DOMAIN', 'covert.local')
    DNS_MAX_CHUNK_SIZE = int(os.getenv('DNS_MAX_CHUNK_SIZE', 45))


def get_config():
    return Config