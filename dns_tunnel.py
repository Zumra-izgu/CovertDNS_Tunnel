#!/usr/bin/env python3
"""
CovertDNS - Quantum-Safe DNS Tunnel

A post-quantum covert channel implementation that hides encrypted messages within
standard DNS query packets. This module provides both sender and receiver functionality
for DNS tunneling with Kyber-768 post-quantum key exchange and AES-256-GCM encryption.

Features:
    - DNS tunneling over port 53 (requires admin/root privileges)
    - Kyber-768 (ML-KEM) post-quantum key exchange (NIST FIPS 203)
    - AES-256-GCM authenticated encryption (NIST SP 800-38D)
    - Stealth mode with human-like delays and background DNS traffic
    - IP whitelisting for access control
    - Rate limiting to avoid detection
    - Cross-platform support (Windows, Linux, macOS)

Supported Platforms:
    - Windows (requires Administrator privileges for port 53)
    - Linux (requires sudo for port 53)
    - macOS (requires sudo for port 53)

Usage:
    python dns_tunnel.py genkeys   - Generate Kyber-768 keypair
    python dns_tunnel.py sender    - Send encrypted messages
    python dns_tunnel.py receiver  - Receive and decrypt messages

NIST Standards:
    - ML-KEM (Kyber-768): FIPS 203 (Module-Lattice-Based Key-Encapsulation Mechanism)
    - AES-256-GCM: NIST SP 800-38D (Recommendation for Block Cipher Modes of Operation)
"""

import socket
import time
import random
import base64
import json
import threading
import ipaddress
from collections import defaultdict
from datetime import datetime
from typing import List, Dict, Optional, Tuple
import os
import sys
import struct

# Add parent directory to Python path for module imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.constants import (
    DNS_PORT, FALLBACK_PORTS, BASE_DOMAIN, MAX_CHUNK_SIZE,
    MIN_DELAY_MS, MAX_DELAY_MS, ALLOWED_SENDER_IPS,
    MAX_PACKETS_PER_SECOND, BURST_SIZE, IS_WINDOWS, IS_LINUX,
    JITTER, IS_ADMIN, BYPASS_MDNS_CONFLICT, USE_RAW_SOCKET
)
from encryption.hybrid_crypto import HybridCrypto

# ============================================================================
# Stealth Module Import (Optional)
# ============================================================================
# The stealth module provides human-like delay simulation and background DNS
# traffic generation. If the module is not installed, the system falls back
# to simple random delays without any stealth features.

STEALTH_AVAILABLE = False
StealthDNSEngine = None
try:
    from stealth.traffic_simulator import StealthDNSEngine
    STEALTH_AVAILABLE = True
except ImportError:
    pass


# ============================================================================
# Rate Limiter
# ============================================================================

class RateLimiter:
    """
    Token bucket rate limiter for controlling DNS query frequency.
    
    This limiter helps avoid detection by preventing bursts of DNS queries
    that could trigger network monitoring systems. It allows a configured
    number of packets per second with a burst allowance.
    
    Attributes:
        max_packets (int): Maximum packets allowed per second.
        burst_size (int): Additional burst allowance.
        packets (list): Timestamps of recently sent packets.
        lock (threading.Lock): Thread safety lock.
    """
    
    def __init__(self, max_packets_per_sec: int, burst_size: int):
        """
        Initialize the rate limiter.
        
        Args:
            max_packets_per_sec: Maximum packets allowed per second.
            burst_size: Additional burst allowance.
        """
        self.max_packets = max_packets_per_sec
        self.burst_size = burst_size
        self.packets = []
        self.lock = threading.Lock()
    
    def allow(self) -> bool:
        """
        Check if a packet is allowed to be sent.
        
        Returns:
            bool: True if packet is allowed, False if rate limit exceeded.
        """
        with self.lock:
            now = time.time()
            # Remove packets older than 1 second
            self.packets = [p for p in self.packets if now - p < 1.0]
            
            if len(self.packets) >= self.max_packets + self.burst_size:
                return False
            
            self.packets.append(now)
            return True


# ============================================================================
# Raw Socket Handler (Windows-Specific)
# ============================================================================

class RawSocketHandler:
    """
    Raw socket handler for Windows systems to capture DNS packets.
    
    Raw sockets allow capturing packets at the network layer, which can be
    used as an alternative to binding to port 53 when the port is already
    occupied by another service (e.g., mDNS/Bonjour).
    
    Note: Administrator privileges are required for raw socket creation on Windows.
    """
    
    @staticmethod
    def create_raw_socket():
        """
        Create a raw UDP socket for packet capture.
        
        Returns:
            socket.socket: Raw socket object, or None if creation failed.
        """
        if not IS_WINDOWS:
            return None
        
        try:
            # Create raw socket with IPPROTO_UDP to capture UDP packets
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Administrator privileges are required on Windows
            if not IS_ADMIN:
                print("⚠️ Raw socket requires Administrator privileges!")
                return None
            
            return sock
        except Exception as e:
            print(f"⚠️ Raw socket creation failed: {e}")
            return None
    
    @staticmethod
    def parse_udp_packet(data: bytes) -> tuple:
        """
        Parse a raw UDP packet to extract the UDP payload.
        
        Args:
            data: Raw packet bytes including IP and UDP headers.
        
        Returns:
            tuple: (source_port, destination_port, payload) or (None, None, None) on error.
        """
        try:
            # Parse IP header (20 bytes minimum)
            ip_header = data[:20]
            iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
            
            # Calculate IP header length (IHL field in first byte)
            ip_header_len = (iph[0] & 0x0F) * 4
            
            # Parse UDP header (8 bytes)
            udp_header = data[ip_header_len:ip_header_len + 8]
            udph = struct.unpack('!HHHH', udp_header)
            
            source_port = udph[0]
            dest_port = udph[1]
            udp_len = udph[2]
            
            # Extract UDP payload (data after UDP header)
            payload = data[ip_header_len + 8:ip_header_len + udp_len]
            
            return source_port, dest_port, payload
        except Exception:
            return None, None, None


# ============================================================================
# DNS Sender
# ============================================================================

class DNSSender:
    """
    DNS tunnel sender that encapsulates encrypted messages into DNS queries.
    
    This class handles the entire sending process:
        1. Encrypt the plaintext using Kyber-768 + AES-256 hybrid encryption
        2. Convert encrypted data to Base64 for DNS compatibility
        3. Split long messages into chunks (max 45 characters per chunk)
        4. Send each chunk as a separate DNS query
        5. Apply random delays between queries for anti-detection
    
    The DNS query format is: <seq_num>.<chunk_data>.covert.local
    where seq_num is a 4-digit sequence number for reassembly ordering.
    
    Attributes:
        target_ip (str): IP address of the receiver.
        sock (socket.socket): UDP socket for sending queries.
        seq (int): Current sequence number for the next chunk.
        rate_limiter (RateLimiter): Controls packet sending frequency.
        public_key (bytes): Receiver's Kyber-768 public key for encryption.
        stealth_engine (StealthDNSEngine): Optional stealth mode engine.
    """
    
    def __init__(self, target_ip: str, recipient_public_key_b64: str = None):
        """
        Initialize the DNS sender.
        
        Args:
            target_ip: IP address of the receiver.
            recipient_public_key_b64: Base64-encoded Kyber-768 public key.
        
        Raises:
            ValueError: If the target IP address is invalid.
        """
        try:
            ipaddress.ip_address(target_ip)
        except ValueError:
            raise ValueError(f"Invalid IP address: {target_ip}")
        
        self.target_ip = target_ip
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.sock.settimeout(3)
        self.seq = 0
        self.rate_limiter = RateLimiter(MAX_PACKETS_PER_SECOND, BURST_SIZE)
        self.stealth_engine = None
        
        if recipient_public_key_b64:
            self.public_key = base64.b64decode(recipient_public_key_b64)
        else:
            self.public_key = None
        
        print(f"🔐 DNSSender initialized for {target_ip}:{DNS_PORT}")
        if self.public_key:
            print("🔒 Encryption enabled (Kyber-768 + AES-256-GCM)")
    
    def set_stealth_engine(self, engine):
        """
        Set the stealth engine for human-like delay simulation.
        
        Args:
            engine: StealthDNSEngine instance.
        """
        self.stealth_engine = engine
        print("🕵️ Stealth mode enabled for sender")
    
    def build_dns_query(self, domain: str) -> bytes:
        """
        Construct a DNS query packet for the given domain.
        
        Implements a minimal but RFC-compliant DNS query packet with:
            - Random transaction ID (for anti-detection)
            - Standard query flags (0x0100)
            - Single question section
        
        Args:
            domain: Domain name to query (e.g., "0001.test.covert.local").
        
        Returns:
            bytes: Complete DNS query packet ready for transmission.
        
        Reference:
            RFC 1035: Domain Names - Implementation and Specification
        """
        # Random transaction ID (helps avoid caching and detection)
        transaction_id = random.randint(0, 65535).to_bytes(2, 'big')
        
        # Flags: Standard query (0x0100)
        flags = (0x0100).to_bytes(2, 'big')
        
        # Counts: 1 question, 0 answer, 0 authority, 0 additional
        qdcount = (0x0001).to_bytes(2, 'big')
        ancount = (0x0000).to_bytes(2, 'big')
        nscount = (0x0000).to_bytes(2, 'big')
        arcount = (0x0000).to_bytes(2, 'big')
        
        header = transaction_id + flags + qdcount + ancount + nscount + arcount
        question = self._encode_domain_name(domain)
        
        # Query type: A record (host address)
        qtype = (0x0001).to_bytes(2, 'big')
        
        # Query class: IN (Internet)
        qclass = (0x0001).to_bytes(2, 'big')
        
        return header + question + qtype + qclass
    
    def _encode_domain_name(self, domain: str) -> bytes:
        """
        Encode a domain name into DNS wire format.
        
        DNS wire format: each label is prefixed with its length byte,
        followed by the label characters, terminated by a zero byte.
        
        Example: "covert.local" -> \x06covert\x05local\x00
        
        Args:
            domain: Domain name string (e.g., "covert.local").
        
        Returns:
            bytes: Domain name in DNS wire format.
        
        Raises:
            ValueError: If any domain label exceeds 63 characters (RFC 1035 limit).
        """
        parts = domain.split('.')
        result = b''
        for part in parts:
            if len(part) > 63:
                raise ValueError(f"Domain label too long: {part}")
            result += len(part).to_bytes(1, 'big')
            result += part.encode('ascii')
        result += b'\x00'
        return result
    
    def send_message(self, message: str) -> bool:
        """
        Send a message through the DNS tunnel.
        
        This method handles the complete message transmission process:
            1. Encrypt or encode the message
            2. Add message type prefix (TEXT: or VOICE:)
            3. Split into chunks
            4. Send each chunk as a DNS query
            5. Apply delays between queries
        
        Args:
            message: Plaintext message to send.
        
        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        print(f"\n📡 DNS Sender - Sending to {self.target_ip}:{DNS_PORT}")
        print(f"💬 Original message: {message}")
        
        # Step 1: Encrypt or encode the message
        if self.public_key:
            print("🔐 Encrypting with Kyber-768 + AES-256...")
            data_to_send = HybridCrypto.encrypt_for_dns(message, self.public_key)
        else:
            print("⚠️ No public key, sending unencrypted!")
            data_to_send = base64.b64encode(message.encode()).decode()
        
        print(f"📦 Encrypted data size: {len(data_to_send)} chars")
        
        # Step 2: Add message type prefix
        # TEXT: prefix for text messages
        final_data = f"TEXT:{data_to_send}"
        
        # Step 3: Split into chunks
        chunks = []
        for i in range(0, len(final_data), MAX_CHUNK_SIZE):
            chunks.append(final_data[i:i + MAX_CHUNK_SIZE])
        
        # Add total chunk count to the first chunk for reassembly
        chunks[0] = f"T{len(chunks):03d}" + chunks[0]
        
        print(f"✂️ Split into {len(chunks)} chunks (max {MAX_CHUNK_SIZE} chars)")
        
        # Step 4: Send each chunk as a DNS query
        for i, chunk in enumerate(chunks):
            self.seq += 1
            domain = f"{self.seq:04d}.{chunk}.{BASE_DOMAIN}"
            
            if not self._send_single_query(domain, i, len(chunks)):
                return False
            
            # Step 5: Apply delay between queries
            if self.stealth_engine and STEALTH_AVAILABLE:
                delay = self.stealth_engine.get_chunk_delay(i, len(chunks))
            else:
                delay = random.uniform(MIN_DELAY_MS / 1000, MAX_DELAY_MS / 1000)
                if JITTER:
                    delay += random.uniform(-0.03, 0.03)
            time.sleep(max(0.01, delay))
        
        print(f"\n✅ Message sent successfully!")
        return True
    
    def _send_single_query(self, domain: str, chunk_num: int, total: int) -> bool:
        """
        Send a single DNS query.
        
        Args:
            domain: Domain name for the query.
            chunk_num: Current chunk number (0-indexed).
            total: Total number of chunks.
        
        Returns:
            bool: True if sent successfully, False otherwise.
        """
        if not self.rate_limiter.allow():
            time.sleep(0.5)
        
        query = self.build_dns_query(domain)
        
        try:
            self.sock.sendto(query, (self.target_ip, DNS_PORT))
            print(f"  ✅ Chunk {chunk_num+1}/{total} sent: {domain[:50]}...")
            return True
        except socket.error as e:
            print(f"  ❌ Failed: {e}")
            return False
    
    def close(self):
        """Close the UDP socket and release resources."""
        self.sock.close()


# ============================================================================
# DNS Receiver
# ============================================================================

class DNSReceiver:
    """
    DNS tunnel receiver that reassembles and decrypts messages from DNS queries.
    
    This class handles the receiving process:
        1. Listen for incoming DNS queries on UDP port 53 (or fallback ports)
        2. Extract the domain name and parse the sequence number and chunk data
        3. Collect chunks until the expected total is reached
        4. Reassemble the complete encrypted payload
        5. Decrypt using the private key (if available)
        6. Output the plaintext message
    
    The receiver also sends DNS responses back to the sender to make the
    traffic appear as legitimate DNS exchanges.
    
    Attributes:
        sock (socket.socket): UDP socket for listening.
        raw_sock (socket.socket): Raw socket for alternative capture (Windows).
        running (bool): Flag indicating whether the receiver is active.
        messages (dict): In-progress message reassembly storage.
        whitelist (list): Allowed sender IP addresses/CIDR ranges.
        private_key (bytes): Receiver's Kyber-768 private key for decryption.
        rate_limiters (dict): Per-client rate limiters.
    """
    
    def __init__(self, private_key_b64: str = None):
        """
        Initialize the DNS receiver.
        
        Args:
            private_key_b64: Base64-encoded Kyber-768 private key.
        """
        self.sock = None
        self.raw_sock = None
        self.running = False
        self.messages: Dict[str, Dict] = {}
        self.whitelist = self._compile_whitelist(ALLOWED_SENDER_IPS)
        self.rate_limiters: Dict[str, RateLimiter] = defaultdict(
            lambda: RateLimiter(MAX_PACKETS_PER_SECOND, BURST_SIZE)
        )
        
        if private_key_b64:
            self.private_key = base64.b64decode(private_key_b64)
            print("🔓 Decryption enabled")
        else:
            self.private_key = None
            print("⚠️ No private key - decryption disabled")
        
        print(f"🔐 DNSReceiver initialized (Port {DNS_PORT} mode)")
        print(f"📋 Whitelist: {list(ALLOWED_SENDER_IPS)}")
        
        if DNS_PORT == 53 and IS_WINDOWS and not IS_ADMIN:
            print("\n⚠️⚠️⚠️ WARNING ⚠️⚠️⚠️")
            print("Port 53 requires Administrator privileges!")
            print("Please run PowerShell as Administrator and try again.")
            print("Or run 'python dns_tunnel.py receiver' in an Admin terminal.\n")
    
    def _compile_whitelist(self, patterns) -> list:
        """
        Compile whitelist patterns into IP address and network objects.
        
        Args:
            patterns: List of IP addresses or CIDR notation strings.
        
        Returns:
            list: Compiled whitelist entries as tuples (type, value).
        """
        compiled = []
        for pattern in patterns:
            if '/' in pattern:
                try:
                    network = ipaddress.ip_network(pattern, strict=False)
                    compiled.append(('network', network))
                except ValueError:
                    print(f"⚠️ Invalid CIDR: {pattern}")
            else:
                try:
                    ip = ipaddress.ip_address(pattern)
                    compiled.append(('ip', ip))
                except ValueError:
                    print(f"⚠️ Invalid IP: {pattern}")
        return compiled
    
    def _is_ip_allowed(self, ip: str) -> bool:
        """
        Check if an IP address is allowed by the whitelist.
        
        Args:
            ip: IP address string to check.
        
        Returns:
            bool: True if the IP is allowed, False otherwise.
        """
        try:
            client_ip = ipaddress.ip_address(ip)
            for type_, value in self.whitelist:
                if type_ == 'ip' and client_ip == value:
                    return True
                elif type_ == 'network' and client_ip in value:
                    return True
            return False
        except ValueError:
            return False
    
    def start(self):
        """
        Start the DNS receiver and begin listening for incoming queries.
        
        Attempts to bind to port 53 first, then falls back to alternative
        ports if the default is unavailable. On Windows with admin privileges,
        also attempts to use raw sockets as an alternative.
        """
        ports_to_try = [DNS_PORT] + FALLBACK_PORTS
        
        for port in ports_to_try:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                # Windows-specific: Try exclusive address use for port 53
                if IS_WINDOWS and port == 53:
                    try:
                        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    except Exception:
                        pass
                
                self.sock.bind(('0.0.0.0', port))
                self.running = True
                
                print(f"\n✅ DNS Receiver started on port {port}")
                
                if port == 53:
                    print("🎯 Successfully bound to port 53!")
                    if IS_WINDOWS:
                        print("⚠️ Note: May conflict with mDNS (Bonjour).")
                        print("   If issues occur: net stop dnscache")
                break
                
            except PermissionError:
                print(f"❌ Port {port} requires administrator privileges")
                if port == 53:
                    print("   → Please run as Administrator for port 53")
            except OSError as e:
                if "Address already in use" in str(e) or "Only one usage" in str(e):
                    print(f"❌ Port {port} already in use")
                    if port == 53 and BYPASS_MDNS_CONFLICT:
                        print("   → Possible mDNS conflict. Trying raw socket...")
                        if self._try_raw_socket():
                            break
                else:
                    print(f"❌ Failed to bind port {port}: {e}")
            except Exception as e:
                print(f"❌ Unexpected error on port {port}: {e}")
        else:
            print("\n❌ Could not bind to any port.")
            print("\nTroubleshooting:")
            print("1. Run as Administrator")
            print("2. Stop DNS Client service: net stop dnscache")
            print("3. Stop mDNS/Bonjour service")
            return
        
        print(f"🔒 Allowed IPs: {list(ALLOWED_SENDER_IPS)}")
        print(f"⏹ Press Ctrl+C to stop\n")
        
        while self.running:
            try:
                self.sock.settimeout(1.0)
                data, addr = self.sock.recvfrom(512)
                client_ip = addr[0]
                
                if not self.rate_limiters[client_ip].allow():
                    continue
                
                if not self._is_ip_allowed(client_ip):
                    print(f"🚫 BLOCKED: {client_ip}")
                    continue
                
                self._handle_dns_packet(data, addr)
                
            except socket.timeout:
                continue
            except KeyboardInterrupt:
                break
            except Exception as e:
                if self.running:
                    print(f"⚠️ Error: {e}")
    
    def _try_raw_socket(self) -> bool:
        """
        Attempt to use raw socket mode for port 53 capture.
        
        Returns:
            bool: True if raw socket mode was successfully activated.
        """
        try:
            if not IS_WINDOWS:
                return False
            
            self.raw_sock = RawSocketHandler.create_raw_socket()
            if not self.raw_sock:
                return False
            
            # Start raw socket listener thread
            self.running = True
            threading.Thread(target=self._raw_socket_listener, daemon=True).start()
            print("✅ Raw socket mode active for port 53")
            return True
        except Exception as e:
            print(f"❌ Raw socket failed: {e}")
            return False
    
    def _raw_socket_listener(self):
        """Raw socket listener thread for capturing packets."""
        while self.running:
            try:
                self.raw_sock.settimeout(1.0)
                data, addr = self.raw_sock.recvfrom(65535)
                
                src_port, dst_port, payload = RawSocketHandler.parse_udp_packet(data)
                
                if dst_port == DNS_PORT and payload:
                    self._handle_dns_packet(payload, addr)
                    
            except socket.timeout:
                continue
            except Exception:
                continue
    
    def _handle_dns_packet(self, data: bytes, addr: tuple):
        """
        Process an incoming DNS packet.
        
        Extracts the domain name, parses the sequence number and chunk data,
        and triggers reassembly when all chunks are received.
        
        Args:
            data: Raw DNS packet data.
            addr: Sender address tuple (ip, port).
        """
        try:
            domain = self._extract_domain(data)
            
            # Only process queries for our base domain
            if not domain or not domain.endswith(BASE_DOMAIN):
                return
            
            # Send a DNS response to make traffic appear legitimate
            try:
                response = self._build_dns_response(data)
                self.sock.sendto(response, addr)
            except Exception:
                pass
            
            parts = domain.replace(f'.{BASE_DOMAIN}', '').split('.')
            if len(parts) >= 2:
                try:
                    seq = int(parts[0])
                    chunk_data = parts[1] if len(parts) > 1 else ""
                    client_ip = addr[0]
                    
                    if client_ip not in self.messages:
                        self.messages[client_ip] = {
                            'chunks': {},
                            'total_chunks': None,
                            'last_update': time.time()
                        }
                    
                    # Extract total chunk count from first chunk
                    if chunk_data.startswith('T'):
                        try:
                            total = int(chunk_data[1:4])
                            chunk_data = chunk_data[4:]
                            self.messages[client_ip]['total_chunks'] = total
                        except ValueError:
                            pass
                    
                    self.messages[client_ip]['chunks'][seq] = chunk_data
                    self.messages[client_ip]['last_update'] = time.time()
                    print(f"  📦 Chunk {seq} received from {client_ip}")
                    
                    self._try_reassemble(client_ip)
                    
                except ValueError:
                    pass
                    
        except Exception:
            pass
    
    def _extract_domain(self, data: bytes) -> str:
        """
        Extract the domain name from a DNS query packet.
        
        Args:
            data: Raw DNS packet data.
        
        Returns:
            str: Extracted domain name, or empty string on error.
        """
        try:
            pos = 12
            domain_parts = []
            while pos < len(data):
                length = data[pos]
                if length == 0:
                    break
                if length & 0xC0:
                    # DNS compression pointer - skip for simplicity
                    break
                pos += 1
                if pos + length > len(data):
                    break
                domain_parts.append(data[pos:pos + length].decode('ascii', errors='ignore'))
                pos += length
            return '.'.join(domain_parts) if domain_parts else ""
        except Exception:
            return ""
    
    def _build_dns_response(self, query_data: bytes) -> bytes:
        """
        Build a DNS response packet for a given query.
        
        Returns a standard DNS response with an A record pointing to 127.0.0.1.
        
        Args:
            query_data: The original DNS query packet.
        
        Returns:
            bytes: DNS response packet.
        """
        transaction_id = query_data[:2]
        flags = (0x8180).to_bytes(2, 'big')  # Response, authoritative
        qdcount = query_data[4:6]
        ancount = (0x0001).to_bytes(2, 'big')  # One answer record
        nscount = (0x0000).to_bytes(2, 'big')
        arcount = (0x0000).to_bytes(2, 'big')
        
        header = transaction_id + flags + qdcount + ancount + nscount + arcount
        question = query_data[12:]
        
        # Answer section: A record pointing to 127.0.0.1
        answer = self._encode_domain_name("covert.local")
        answer += (0x0001).to_bytes(2, 'big')  # Type A
        answer += (0x0001).to_bytes(2, 'big')  # Class IN
        answer += (0x0000012c).to_bytes(4, 'big')  # TTL: 300 seconds
        answer += (0x0004).to_bytes(2, 'big')  # Data length: 4 bytes
        answer += socket.inet_aton('127.0.0.1')  # IP address
        
        return header + question + answer
    
    def _encode_domain_name(self, domain: str) -> bytes:
        """
        Encode a domain name in DNS wire format.
        
        Args:
            domain: Domain name string.
        
        Returns:
            bytes: Domain name in DNS wire format.
        """
        parts = domain.split('.')
        result = b''
        for part in parts:
            result += len(part).to_bytes(1, 'big')
            result += part.encode('ascii')
        result += b'\x00'
        return result
    
    def _try_reassemble(self, client_ip: str):
        """
        Attempt to reassemble a complete message from received chunks.
        
        When all chunks for a message have been received, this method:
            1. Concatenates the chunks in order
            2. Decrypts the result using the private key (if available)
            3. Displays the decrypted message
            4. Cleans up the stored chunks
        
        Args:
            client_ip: IP address of the sender.
        """
        msg_data = self.messages.get(client_ip)
        if not msg_data:
            return
        
        chunks = msg_data['chunks']
        total_chunks = msg_data.get('total_chunks')
        
        # Verify we have all chunks in order
        sorted_seqs = sorted(chunks.keys())
        expected = 1
        collected = []
        
        for seq in sorted_seqs:
            if seq == expected:
                collected.append(chunks[seq])
                expected += 1
            else:
                return
        
        if total_chunks and len(collected) != total_chunks:
            return
        
        if len(collected) > 0:
            try:
                encoded = ''.join(collected)
                
                # Attempt decryption if private key is available
                if self.private_key:
                    try:
                        message = HybridCrypto.decrypt_from_dns(encoded, self.private_key)
                    except Exception:
                        # Fall back to base64 decode
                        message = base64.b64decode(encoded).decode()
                else:
                    message = base64.b64decode(encoded).decode()
                
                # Remove TEXT: prefix if present
                if message.startswith("TEXT:"):
                    message = message[5:]
                
                print(f"\n{'='*60}")
                print(f"🎉 MESSAGE RECEIVED! [{client_ip}]")
                print(f"{'='*60}")
                print(f"📨 Message: {message}")
                print(f"📦 Chunks: {len(collected)}/{total_chunks or len(collected)}")
                print(f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                print(f"{'='*60}\n")
                
                del self.messages[client_ip]
                
            except Exception as e:
                print(f"  ⚠️ Reassembly error: {e}")
    
    def stop(self):
        """Stop the receiver and close all sockets."""
        self.running = False
        if self.sock:
            self.sock.close()
        if self.raw_sock:
            self.raw_sock.close()
        print("\n🛑 DNS Receiver stopped")


# ============================================================================
# Utility Functions
# ============================================================================

def generate_keys():
    """
    Generate a Kyber-768 keypair for post-quantum encryption.
    
    The generated keypair consists of a public key (1,184 bytes) for encryption
    and a private key (2,400 bytes) for decryption. Both keys are saved to
    files in Base64 format for easy distribution.
    
    Returns:
        tuple: (public_key_base64, private_key_base64)
    """
    print("=" * 60)
    print("🔑 Generating Kyber-768 Keypair")
    print("=" * 60)
    
    pub, priv = HybridCrypto.generate_keypair()
    pub_b64 = base64.b64encode(pub).decode()
    priv_b64 = base64.b64encode(priv).decode()
    
    print(f"\n📤 PUBLIC KEY (share with senders):")
    print(f"{pub_b64}\n")
    print(f"📥 PRIVATE KEY (keep secret):")
    print(f"{priv_b64}\n")
    
    with open("public_key.b64", "w") as f:
        f.write(pub_b64)
    with open("private_key.b64", "w") as f:
        f.write(priv_b64)
    
    print("💾 Keys saved to:")
    print("   - public_key.b64")
    print("   - private_key.b64")
    
    return pub_b64, priv_b64


# ============================================================================
# Command Line Interface
# ============================================================================

def run_sender():
    """Interactive sender interface."""
    print("=" * 60)
    print("🔐 Quantum-Safe DNS Sender (Port 53)")
    print("=" * 60)
    
    target = input("\n🎯 Target IP (default 127.0.0.1): ").strip()
    if not target:
        target = "127.0.0.1"
    
    message = input("💬 Message: ").strip()
    if not message:
        message = "Hello from CovertDNS on port 53!"
    
    # Stealth mode selection
    print("\n🕵️ Stealth Mode:")
    print("  1 - Normal mode (simple random delays)")
    print("  2 - Stealth mode (human-like delays + background DNS)")
    stealth_choice = input("Choice (1/2): ").strip()
    use_stealth = (stealth_choice == "2")
    
    key_file = input("📁 Public key file (default public_key.b64): ").strip()
    if not key_file:
        key_file = "public_key.b64"
    
    try:
        with open(key_file, "r") as f:
            pub_b64 = f.read().strip()
    except FileNotFoundError:
        print(f"⚠️ Key file {key_file} not found. Sending unencrypted.")
        pub_b64 = None
    
    sender = DNSSender(target, pub_b64)
    
    # Initialize stealth engine if selected
    stealth_engine = None
    if use_stealth and STEALTH_AVAILABLE:
        print("\n🕵️ Stealth intensity:")
        print("  low    - Minimal background traffic")
        print("  normal - Balanced (recommended)")
        print("  high   - Aggressive masking")
        print("  stealth- Maximum stealth")
        intensity = input("Intensity [normal]: ").strip() or "normal"
        
        stealth_engine = StealthDNSEngine()
        stealth_engine.start_stealth_mode(intensity)
        sender.set_stealth_engine(stealth_engine)
    elif use_stealth and not STEALTH_AVAILABLE:
        print("\n⚠️ Stealth module not installed!")
        print("   Using normal delays only")
    
    success = sender.send_message(message)
    
    # Stop stealth engine if active
    if stealth_engine:
        stealth_engine.stop_stealth_mode()
    
    sender.close()
    
    if success:
        print("\n✨ Message transmission complete!")
    else:
        print("\n❌ Transmission failed!")


def run_receiver():
    """Interactive receiver interface."""
    print("=" * 60)
    print("🔐 Quantum-Safe DNS Receiver (Port 53)")
    print("=" * 60)
    print("\n⚠️ Port 53 requires Administrator privileges!\n")
    
    key_file = input("📁 Private key file (default private_key.b64): ").strip()
    if not key_file:
        key_file = "private_key.b64"
    
    try:
        with open(key_file, "r") as f:
            priv_b64 = f.read().strip()
    except FileNotFoundError:
        print(f"⚠️ Key file {key_file} not found. Running without decryption.")
        priv_b64 = None
    
    receiver = DNSReceiver(priv_b64)
    try:
        receiver.start()
    except KeyboardInterrupt:
        receiver.stop()


# ============================================================================
# Main Entry Point
# ============================================================================

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1:
        if sys.argv[1] == "sender":
            run_sender()
        elif sys.argv[1] == "receiver":
            run_receiver()
        elif sys.argv[1] == "genkeys":
            generate_keys()
        else:
            print("Unknown command")
    else:
        print("=" * 60)
        print("🕵️ CovertDNS - Quantum-Safe DNS Tunnel (Port 53)")
        print("=" * 60)
        print("\nCommands:")
        print("  python dns_tunnel.py genkeys   - Generate keypair")
        print("  python dns_tunnel.py sender    - Send messages")
        print("  python dns_tunnel.py receiver  - Receive messages")
        print("\n📖 Port 53 Important Notes:")
        print("  1. Administrator/root privileges required")
        print("  2. Windows: Run PowerShell as Administrator")
        print("  3. Linux/macOS: Use sudo")
        print("\n🕵️ Stealth mode features (if module installed):")
        print("  - Human-like typing/thinking/reading delays")
        print("  - Background DNS traffic (real domains)")
        print("  - Hour-based traffic patterns")