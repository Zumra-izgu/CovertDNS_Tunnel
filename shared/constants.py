"""
Shared Constants for DNS Tunnel

This module defines all configuration constants used throughout the CovertDNS
application. These settings control DNS tunneling behavior, anti-detection
parameters, security policies, and platform-specific handling.

All constants are defined in a single location to facilitate easy configuration
and maintain consistency across the codebase. Users can modify these values to
adjust the system's behavior for different deployment scenarios.

Configuration Categories:
    - DNS Configuration: Port settings, domain names, chunk sizes
    - Timing/Anti-Detection: Delay parameters for traffic obfuscation
    - Security: IP whitelisting and access control
    - Rate Limiting: Packet rate controls to avoid detection
    - Platform Detection: OS-specific handling flags
    - Cryptography: Key size constants for Kyber-768
"""

import os
import platform
import sys

# ============================================================================
# DNS Configuration
# ============================================================================

# Primary DNS port (requires administrator/root privileges)
DNS_PORT = 53

# Alternative ports to try if the primary port is unavailable
# These ports do not require special privileges and can be used for testing
FALLBACK_PORTS = [5353, 5354, 5355]

# Base domain name for DNS tunneling queries
# All tunneled messages are sent as subdomains of this domain
BASE_DOMAIN = "covert.local"

# Maximum chunk size for DNS query labels
# DNS labels are limited to 63 characters per RFC 1035; we use 45 for safety
MAX_CHUNK_SIZE = 45

# Minimum chunk size (used for randomized chunk sizes in stealth mode)
MIN_CHUNK_SIZE = 20

# ============================================================================
# Timing / Anti-Detection Parameters
# ============================================================================

# Minimum delay between DNS queries (milliseconds)
# Random delays help avoid pattern-based detection
MIN_DELAY_MS = 100

# Maximum delay between DNS queries (milliseconds)
MAX_DELAY_MS = 800

# Add random jitter to delays to appear more human-like
# When enabled, delays are randomly varied within a small range
JITTER = True

# ============================================================================
# Security / IP Whitelist
# ============================================================================

# Allowed sender IP addresses and CIDR ranges
# Only packets from these IP addresses will be processed by the receiver
ALLOWED_SENDER_IPS = {
    '127.0.0.1',           # Localhost (default for testing)
    '0.0.0.0',             # Allow all IPs (use with caution - testing only)
    '::1',                 # Localhost IPv6
    '192.168.1.0/24',      # Local network subnet (CIDR notation)
}

# ============================================================================
# Rate Limiting
# ============================================================================

# Maximum number of DNS queries allowed per second
# Helps prevent detection by limiting packet bursts
MAX_PACKETS_PER_SECOND = 10

# Burst size allowance for rate limiting
# Allows short bursts above the per-second limit
BURST_SIZE = 3

# ============================================================================
# Platform Detection
# ============================================================================

# Detect the operating system for platform-specific code paths
IS_WINDOWS = platform.system() == 'Windows'
IS_LINUX = platform.system() == 'Linux'
IS_MAC = platform.system() == 'Darwin'

# Flag indicating whether the process has administrator/root privileges
IS_ADMIN = False

# ============================================================================
# Port 53 Specific Settings
# ============================================================================

# Whether to attempt raw socket creation on Windows (requires admin)
# Raw sockets can be used as an alternative when port 53 is occupied
USE_RAW_SOCKET = IS_WINDOWS

# Whether to attempt bypassing mDNS/Bonjour port 53 conflicts
# When True, the system will try to use raw sockets if port binding fails
BYPASS_MDNS_CONFLICT = True

# ============================================================================
# Admin Privilege Check
# ============================================================================

def check_admin():
    """
    Check if the current process has administrator/root privileges.
    
    On Windows, this uses ctypes to call IsUserAnAdmin().
    On Unix-like systems (Linux/macOS), it checks if the effective UID is 0.
    
    Returns:
        bool: True if running with administrator/root privileges, False otherwise.
    
    The result is stored in the global IS_ADMIN variable for use throughout
    the application. This affects port 53 binding and raw socket creation.
    """
    global IS_ADMIN
    if IS_WINDOWS:
        try:
            import ctypes
            IS_ADMIN = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception:
            IS_ADMIN = False
    else:
        IS_ADMIN = os.geteuid() == 0
    return IS_ADMIN

# Perform admin check on module load
check_admin()

# ============================================================================
# Cryptography Constants (Kyber-768 / ML-KEM)
# ============================================================================

# Kyber-768 public key size (bytes)
# NIST FIPS 203 standard: ML-KEM-768 public key size
KYBER_PUBLIC_KEY_BYTES = 1184

# Kyber-768 ciphertext size (bytes)
# NIST FIPS 203 standard: ML-KEM-768 ciphertext size
KYBER_CIPHERTEXT_BYTES = 1088

# Kyber-768 shared secret size (bytes)
# After SHA-256 hashing, produces 32-byte key suitable for AES-256
KYBER_SHARED_SECRET_BYTES = 32