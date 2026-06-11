"""
Shared Constants for DNS Tunnel - Port 53 Support
"""

import os
import platform
import sys

# DNS Configuration - PORT 53 KULLANIMI
DNS_PORT = 53
FALLBACK_PORTS = [5353, 5354, 5355]  # 53 tutmazsa dene
BASE_DOMAIN = "covert.local"
MAX_CHUNK_SIZE = 45
MIN_CHUNK_SIZE = 20

# Timing (Anti-Detection)
MIN_DELAY_MS = 100
MAX_DELAY_MS = 800
JITTER = True

# Security - Özelleştirilebilir
ALLOWED_SENDER_IPS = {
    '127.0.0.1',
    '0.0.0.0',
    '::1',
    '192.168.1.0/24',
}

# Rate Limiting
MAX_PACKETS_PER_SECOND = 10
BURST_SIZE = 3

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MAC = platform.system() == 'Darwin'
IS_ADMIN = False

# Port 53 özel ayarları
USE_RAW_SOCKET = IS_WINDOWS  # Windows'ta raw socket dene
BYPASS_MDNS_CONFLICT = True   # mDNS çakışmasını dene

def check_admin():
    """Administrator yetkisi kontrolü"""
    global IS_ADMIN
    if IS_WINDOWS:
        try:
            import ctypes
            IS_ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except:
            IS_ADMIN = False
    else:
        IS_ADMIN = os.geteuid() == 0
    return IS_ADMIN

# Admin kontrolü
check_admin()

# Crypto
KYBER_PUBLIC_KEY_BYTES = 1184
KYBER_CIPHERTEXT_BYTES = 1088
KYBER_SHARED_SECRET_BYTES = 32