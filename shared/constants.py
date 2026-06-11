"""
Shared Constants for DNS Tunnel
"""

import os
import platform
import ipaddress

# DNS Configuration
DNS_PORT = 53
FALLBACK_PORTS = [5353, 5354, 5355]
BASE_DOMAIN = "covert.local"
MAX_CHUNK_SIZE = 45
MIN_CHUNK_SIZE = 20

# Timing (Anti-Detection)
MIN_DELAY_MS = 100
MAX_DELAY_MS = 800
JITTER = True

# Security - IP Whitelist (Güvenli)
# Özel ağ aralıkları + ihtiyaç duyulan spesifik IP'ler
ALLOWED_SENDER_IPS = {
    # Local
    '127.0.0.1',
    '::1',
    
    # Özel ağlar (RFC 1918)
    '10.0.0.0/8',           # 10.0.0.0 - 10.255.255.255
    '172.16.0.0/12',        # 172.16.0.0 - 172.31.255.255
    '192.168.0.0/16',       # 192.168.0.0 - 192.168.255.255
    
    # CGNAT (Carrier-grade NAT) - VPN'ler ve mobil ağlar için
    '100.64.0.0/10',        # 100.64.0.0 - 100.127.255.255
    
    # Link-local
    '169.254.0.0/16',       # Otomatik IP (DHCP yoksa)
}

# Manuel eklenen spesifik IP'ler (opsiyonel)
MANUAL_ALLOWED_IPS = [
    # '100.81.116.129',  # İhtiyaç varsa buraya ekle
]

# Birleştir
for ip in MANUAL_ALLOWED_IPS:
    ALLOWED_SENDER_IPS.add(ip)

# Rate Limiting
MAX_PACKETS_PER_SECOND = 10
BURST_SIZE = 3

# Platform detection
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MAC = platform.system() == 'Darwin'
IS_ADMIN = False

# Port 53 özel ayarları
USE_RAW_SOCKET = IS_WINDOWS
BYPASS_MDNS_CONFLICT = True

def check_admin():
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

check_admin()

# Crypto
KYBER_PUBLIC_KEY_BYTES = 1184
KYBER_CIPHERTEXT_BYTES = 1088
KYBER_SHARED_SECRET_BYTES = 32