#!/usr/bin/env python3
"""
CovertDNS - Quantum-Safe DNS Tunnel

A post-quantum covert channel implementation that hides encrypted messages within
standard DNS query packets. The system uses Kyber-768 (ML-KEM) for post-quantum
key exchange and AES-256-GCM for hybrid encryption, providing security against
both classical and quantum adversaries.

Supported Platforms: Windows, Linux, macOS
Port Support: 53 (requires administrator/root privileges) with fallback ports
Features: Text messages, voice messages, stealth mode, rate limiting, whitelisting

NIST Standards:
    - ML-KEM (Kyber-768): FIPS 203 (Module-Lattice-Based Key-Encapsulation Mechanism)
    - AES-256-GCM: NIST SP 800-38D
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
# Voice Support Module (Optional)
# ============================================================================
# Voice support is conditionally imported. If the required libraries are not
# installed, the system falls back to dummy implementations that silently
# ignore voice-related operations. This allows the core DNS tunneling
# functionality to work even without audio dependencies.

VOICE_SUPPORT = False
AudioRecorder = None
AudioPlayer = None
VoiceMessageHandler = None

try:
    import sounddevice as sd
    import soundfile as sf
    import numpy as np
    import io
    
    class AudioRecorderClass:
        """
        Audio recorder using sounddevice library.
        
        Captures audio from the default microphone and returns it as a WAV
        byte stream. The audio is normalized, clipped, and converted to 16-bit
        PCM format for compatibility with standard audio players.
        
        Attributes:
            SAMPLE_RATE (int): Sampling rate in Hz (8000 Hz for voice quality)
            DURATION (float): Recording duration in seconds
            CHANNELS (int): Number of audio channels (1 = mono)
        """
        
        def __init__(self, duration: float = 1.0):
            """
            Initialize the audio recorder.
            
            Args:
                duration: Recording length in seconds (default: 1.0)
            """
            self.SAMPLE_RATE = 8000
            self.DURATION = duration
            self.CHANNELS = 1
            
        def record(self) -> bytes:
            """
            Record audio from the default microphone.
            
            Returns:
                bytes: WAV audio data as a byte string, or empty bytes on failure.
            """
            print(f"\n🎙️ Recording {self.DURATION} seconds of audio... Speak now!")
            
            try:
                # Record audio as 32-bit floating point samples
                recording = sd.rec(int(self.DURATION * self.SAMPLE_RATE),
                                  samplerate=self.SAMPLE_RATE,
                                  channels=self.CHANNELS,
                                  dtype='float32')
                sd.wait()
                
                # Handle invalid recordings (NaN or infinite values)
                if np.any(np.isnan(recording)) or np.any(np.isinf(recording)):
                    print("⚠️ Audio recording error, using silence")
                    recording = np.zeros((int(self.DURATION * self.SAMPLE_RATE), self.CHANNELS), dtype='float32')
                
                # Normalize audio to prevent clipping
                max_val = np.max(np.abs(recording))
                if max_val > 0.01:
                    recording = recording / max_val
                
                # Clip to [-1.0, 1.0] range and convert to 16-bit integer
                recording_clipped = np.clip(recording, -1.0, 1.0)
                recording_int16 = (recording_clipped * 32767).astype(np.int16)
                
                print("✅ Recording complete!")
                
                # Write to WAV format in memory
                wav_buffer = io.BytesIO()
                sf.write(wav_buffer, recording_int16, self.SAMPLE_RATE, format='wav')
                wav_buffer.seek(0)
                
                return wav_buffer.getvalue()
            except Exception as e:
                print(f"❌ Recording error: {e}")
                return b""
        
        def close(self):
            """Release audio resources."""
            pass
    
    class AudioPlayerClass:
        """
        Audio player for playing received voice messages.
        
        Uses the system's default audio player to open WAV files. On Windows,
        this uses os.startfile(); on Linux/macOS, it uses xdg-open.
        """
        
        def __init__(self):
            pass
            
        def play(self, audio_bytes: bytes):
            """
            Play audio from WAV byte data.
            
            Args:
                audio_bytes: WAV audio data as a byte string.
            """
            print("\n🔊 Playing audio...")
            try:
                import tempfile
                import subprocess
                
                # Write audio to a temporary file
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                
                # Open with default system audio player
                if IS_WINDOWS:
                    os.startfile(tmp_path)
                else:
                    subprocess.call(['xdg-open', tmp_path])
                
                print(f"✅ Audio player opened for: {tmp_path}")
            except Exception as e:
                print(f"⚠️ Could not open player: {e}")
                print(f"   File saved, you can play it manually")
        
        def close(self):
            """Release audio resources."""
            pass
    
    class VoiceMessageHandlerClass:
        """
        Voice message utility class for encoding, decoding, and saving audio.
        """
        
        @staticmethod
        def audio_to_base64(audio_bytes: bytes) -> str:
            """
            Convert audio bytes to Base64 string for DNS transmission.
            
            Args:
                audio_bytes: Raw WAV audio bytes.
            
            Returns:
                str: Base64-encoded audio data.
            """
            return base64.b64encode(audio_bytes).decode('ascii')
        
        @staticmethod
        def base64_to_audio(b64_string: str) -> bytes:
            """
            Convert Base64 string back to audio bytes.
            
            Args:
                b64_string: Base64-encoded audio data.
            
            Returns:
                bytes: Raw WAV audio bytes.
            """
            return base64.b64decode(b64_string)
        
        @staticmethod
        def save_audio(audio_bytes: bytes, folder: str = "received_voices", filename: str = None):
            """
            Save received audio to a WAV file.
            
            Args:
                audio_bytes: Raw WAV audio bytes.
                folder: Directory to save the audio file.
                filename: Optional custom filename (auto-generated if None).
            
            Returns:
                str: Path to the saved audio file.
            """
            # Create folder if it doesn't exist
            if not os.path.exists(folder):
                os.makedirs(folder)
                print(f"📁 Created folder: {folder}")
            
            if filename is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"voice_{timestamp}.wav"
            
            filepath = os.path.join(folder, filename)
            
            with open(filepath, 'wb') as f:
                f.write(audio_bytes)
            
            print(f"💾 Audio saved: {os.path.abspath(filepath)}")
            print(f"📦 File size: {len(audio_bytes)} bytes")
            return filepath
    
    # Assign the real implementations
    AudioRecorder = AudioRecorderClass
    AudioPlayer = AudioPlayerClass
    VoiceMessageHandler = VoiceMessageHandlerClass
    VOICE_SUPPORT = True
    print("🎤 Voice support ACTIVE (sounddevice)")
    
except ImportError as e:
    # Fallback to dummy implementations if voice libraries are not installed
    print(f"⚠️ Voice support DISABLED: {e}")
    print(f"   For voice messages: pip install sounddevice soundfile numpy")
    
    class DummyAudioRecorder:
        def __init__(self, duration=1.0): pass
        def record(self): return b""
        def close(self): pass
    
    class DummyAudioPlayer:
        def play(self, audio_bytes): pass
        def close(self): pass
    
    class DummyVoiceMessageHandler:
        @staticmethod
        def audio_to_base64(audio_bytes): return base64.b64encode(audio_bytes).decode()
        @staticmethod
        def base64_to_audio(b64_string): return base64.b64decode(b64_string)
        @staticmethod
        def save_audio(audio_bytes, folder="received_voices", filename=None):
            if not os.path.exists(folder):
                os.makedirs(folder)
            if filename is None:
                timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
                filename = f"voice_{timestamp}.wav"
            filepath = os.path.join(folder, filename)
            with open(filepath, 'wb') as f:
                f.write(audio_bytes)
            print(f"💾 Audio saved: {os.path.abspath(filepath)}")
            return filepath
    
    AudioRecorder = DummyAudioRecorder
    AudioPlayer = DummyAudioPlayer
    VoiceMessageHandler = DummyVoiceMessageHandler


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
# Raw Socket Handler (Windows)
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
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            if not IS_ADMIN:
                return None
            return sock
        except Exception:
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
            ip_header = data[:20]
            iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
            ip_header_len = (iph[0] & 0x0F) * 4
            udp_header = data[ip_header_len:ip_header_len + 8]
            udph = struct.unpack('!HHHH', udp_header)
            dest_port = udph[1]
            udp_len = udph[2]
            payload = data[ip_header_len + 8:ip_header_len + udp_len]
            return None, dest_port, payload
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
    """
    
    def __init__(self, target_ip: str, recipient_public_key_b64: str = None):
        """
        Initialize the DNS sender.
        
        Args:
            target_ip: IP address of the receiver.
            recipient_public_key_b64: Base64-encoded Kyber-768 public key.
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
        
        if recipient_public_key_b64:
            self.public_key = base64.b64decode(recipient_public_key_b64)
        else:
            self.public_key = None
        
        print(f"🔐 DNSSender initialized for {target_ip}:{DNS_PORT}")
        if self.public_key:
            print("🔒 Encryption enabled")
        else:
            print("🔓 Encryption DISABLED")
    
    def build_dns_query(self, domain: str) -> bytes:
        """
        Construct a DNS query packet for the given domain.
        
        Implements a minimal but RFC-compliant DNS query packet with:
            - Random transaction ID (for anti-detection)
            - Standard query flags
            - Single question section
        
        Args:
            domain: Domain name to query (e.g., "0001.test.covert.local").
        
        Returns:
            bytes: Complete DNS query packet ready for transmission.
        """
        transaction_id = random.randint(0, 65535).to_bytes(2, 'big')
        flags = (0x0100).to_bytes(2, 'big')
        qdcount = (0x0001).to_bytes(2, 'big')
        ancount = (0x0000).to_bytes(2, 'big')
        nscount = (0x0000).to_bytes(2, 'big')
        arcount = (0x0000).to_bytes(2, 'big')
        header = transaction_id + flags + qdcount + ancount + nscount + arcount
        question = self._encode_domain_name(domain)
        qtype = (0x0001).to_bytes(2, 'big')
        qclass = (0x0001).to_bytes(2, 'big')
        return header + question + qtype + qclass
    
    def _encode_domain_name(self, domain: str) -> bytes:
        """
        Encode a domain name into DNS wire format.
        
        DNS wire format: each label is prefixed with its length byte,
        followed by the label characters, terminated by a zero byte.
        
        Args:
            domain: Domain name string (e.g., "covert.local").
        
        Returns:
            bytes: Domain name in DNS wire format.
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
    
    def send_text_message(self, message: str, encrypt: bool = True) -> bool:
        """
        Send a text message through the DNS tunnel.
        
        Args:
            message: Plaintext message to send.
            encrypt: Whether to encrypt the message (default: True).
        
        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        return self._send_message(message, is_voice=False, encrypt=encrypt)
    
    def send_voice_message(self, audio_bytes: bytes, encrypt: bool = True) -> bool:
        """
        Send a voice message through the DNS tunnel.
        
        Args:
            audio_bytes: WAV audio data as bytes.
            encrypt: Whether to encrypt the message (default: True).
        
        Returns:
            bool: True if the message was sent successfully, False otherwise.
        """
        audio_b64 = VoiceMessageHandler.audio_to_base64(audio_bytes)
        return self._send_message(audio_b64, is_voice=True, encrypt=encrypt)
    
    def _send_message(self, data: str, is_voice: bool = False, encrypt: bool = True) -> bool:
        """
        Internal method for sending messages through the DNS tunnel.
        
        Args:
            data: Message data (plaintext or Base64-encoded voice).
            is_voice: Whether this is a voice message.
            encrypt: Whether to encrypt the message.
        
        Returns:
            bool: True if sent successfully, False otherwise.
        """
        msg_type = "🎤 VOICE" if is_voice else "💬 TEXT"
        encrypt_status = "🔒 ENCRYPTED" if encrypt else "🔓 PLAIN"
        print(f"\n📡 Sending {msg_type} ({encrypt_status}) to {self.target_ip}:{DNS_PORT}")
        
        # Step 1: Encrypt or encode the data
        if encrypt and self.public_key:
            encrypted_data = HybridCrypto.encrypt_for_dns(data, self.public_key)
        else:
            encrypted_data = base64.b64encode(data.encode()).decode()
        
        # Step 2: Add message type prefix
        if is_voice:
            final_data = f"VOICE:{encrypted_data}"
        else:
            final_data = f"TEXT:{encrypted_data}"
        
        # Step 3: Split into chunks
        chunks = []
        for i in range(0, len(final_data), MAX_CHUNK_SIZE):
            chunks.append(final_data[i:i + MAX_CHUNK_SIZE])
        
        # Add total chunk count to the first chunk for reassembly
        chunks[0] = f"T{len(chunks):03d}" + chunks[0]
        
        print(f"✂️ Split into {len(chunks)} chunks")
        
        # Step 4: Send each chunk as a DNS query
        for i, chunk in enumerate(chunks):
            self.seq += 1
            domain = f"{self.seq:04d}.{chunk}.{BASE_DOMAIN}"
            
            if not self._send_single_query(domain, i, len(chunks)):
                return False
            
            # Add random delay between queries for anti-detection
            delay = random.uniform(MIN_DELAY_MS / 1000, MAX_DELAY_MS / 1000)
            time.sleep(max(0.01, delay))
        
        print(f"\n✅ {msg_type} message sent!")
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
            print(f"  ✅ Chunk {chunk_num+1}/{total} sent")
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
        running (bool): Flag indicating whether the receiver is active.
        messages (dict): In-progress message reassembly storage.
        whitelist (list): Allowed sender IP addresses/CIDR ranges.
        private_key (bytes): Receiver's Kyber-768 private key for decryption.
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
            print("⚠️ No private key - plain text only")
        
        print(f"🔐 DNSReceiver initialized (Port {DNS_PORT})")
        print(f"📋 Whitelist: {list(ALLOWED_SENDER_IPS)}")
    
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
                    pass
            else:
                try:
                    ip = ipaddress.ip_address(pattern)
                    compiled.append(('ip', ip))
                except ValueError:
                    pass
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
        also attempts to free port 53 by stopping conflicting services.
        """
        ports_to_try = [DNS_PORT] + FALLBACK_PORTS
        
        for port in ports_to_try:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                self.sock.bind(('0.0.0.0', port))
                self.running = True
                print(f"\n✅ DNS Receiver started on port {port}")
                break
            except Exception as e:
                print(f"❌ Port {port}: {e}")
        else:
            print("\n❌ Could not bind to any port.")
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
            if not domain or not domain.endswith(BASE_DOMAIN):
                return
            
            # Send a DNS response to make traffic appear legitimate
            try:
                response = self._build_dns_response(data)
                self.sock.sendto(response, addr)
            except:
                pass
            
            parts = domain.replace(f'.{BASE_DOMAIN}', '').split('.')
            if len(parts) >= 2:
                try:
                    seq = int(parts[0])
                    chunk_data = parts[1] if len(parts) > 1 else ""
                    client_ip = addr[0]
                    
                    if client_ip not in self.messages:
                        self.messages[client_ip] = {'chunks': {}, 'total_chunks': None}
                    
                    # Extract total chunk count from first chunk
                    if chunk_data.startswith('T'):
                        try:
                            total = int(chunk_data[1:4])
                            chunk_data = chunk_data[4:]
                            self.messages[client_ip]['total_chunks'] = total
                        except ValueError:
                            pass
                    
                    self.messages[client_ip]['chunks'][seq] = chunk_data
                    received = len(self.messages[client_ip]['chunks'])
                    total = self.messages[client_ip]['total_chunks'] or '?'
                    print(f"  📦 Chunk {seq} received ({received}/{total})")
                    
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
        flags = (0x8180).to_bytes(2, 'big')
        qdcount = query_data[4:6]
        ancount = (0x0001).to_bytes(2, 'big')
        nscount = (0x0000).to_bytes(2, 'big')
        arcount = (0x0000).to_bytes(2, 'big')
        header = transaction_id + flags + qdcount + ancount + nscount + arcount
        question = query_data[12:]
        
        answer = self._encode_domain_name("covert.local")
        answer += (0x0001).to_bytes(2, 'big')
        answer += (0x0001).to_bytes(2, 'big')
        answer += (0x0000012c).to_bytes(4, 'big')
        answer += (0x0004).to_bytes(2, 'big')
        answer += socket.inet_aton('127.0.0.1')
        
        return header + question + answer
    
    def _encode_domain_name(self, domain: str) -> bytes:
        """
        Encode a domain name into DNS wire format.
        
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
                
                # Attempt decryption with private key
                decrypted = None
                if self.private_key:
                    try:
                        decrypted = HybridCrypto.decrypt_from_dns(encoded, self.private_key)
                    except:
                        pass
                
                # Fall back to base64 decode if decryption fails
                if decrypted is None:
                    try:
                        decrypted = base64.b64decode(encoded).decode()
                    except:
                        decrypted = encoded
                
                # Determine message type and handle accordingly
                if decrypted.startswith("VOICE:"):
                    audio_b64 = decrypted[6:]
                    audio_bytes = base64.b64decode(audio_b64)
                    filepath = VoiceMessageHandler.save_audio(audio_bytes)
                    
                    print(f"\n{'='*60}")
                    print(f"🎤 VOICE MESSAGE RECEIVED! [{client_ip}]")
                    print(f"{'='*60}")
                    print(f"📦 Audio size: {len(audio_bytes)} bytes")
                    print(f"💾 Saved: {filepath}")
                    print(f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{'='*60}\n")
                    
                    if VOICE_SUPPORT:
                        try:
                            player = AudioPlayer()
                            player.play(audio_bytes)
                            player.close()
                        except Exception as e:
                            print(f"⚠️ Auto-play failed: {e}")
                            print(f"   You can play the file manually: {filepath}")
                    
                elif decrypted.startswith("TEXT:"):
                    text_content = decrypted[5:]
                    print(f"\n{'='*60}")
                    print(f"📝 TEXT MESSAGE RECEIVED! [{client_ip}]")
                    print(f"{'='*60}")
                    print(f"📨 Message: {text_content}")
                    print(f"📦 Chunks: {len(collected)}/{total_chunks or len(collected)}")
                    print(f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{'='*60}\n")
                    
                else:
                    print(f"\n📝 MESSAGE: {decrypted}\n")
                
                del self.messages[client_ip]
                
            except Exception as e:
                print(f"  ❌ Reassembly error: {e}")
    
    def stop(self):
        """Stop the receiver and close all sockets."""
        self.running = False
        if self.sock:
            self.sock.close()
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
    print("🔐 Quantum-Safe DNS Sender")
    print("=" * 60)
    
    target = input("\n🎯 Target IP (default 127.0.0.1): ").strip()
    if not target:
        target = "127.0.0.1"
    
    print("\n📝 Message type:")
    print("  1 - Text message")
    print("  2 - Voice message (1 second - fast)")
    print("  3 - Voice message (5 seconds - normal)")
    
    choice = input("\nChoice (1/2/3): ").strip()
    
    print("\n🔐 Encryption:")
    print("  1 - Encrypted (Kyber-768 + AES-256)")
    print("  2 - Plain (base64 only - faster)")
    
    encrypt_choice = input("\nChoice (1/2): ").strip()
    use_encryption = (encrypt_choice == "1")
    
    pub_b64 = None
    if use_encryption:
        key_file = input("\n📁 Public key file (default public_key.b64): ").strip()
        if not key_file:
            key_file = "public_key.b64"
        try:
            with open(key_file, "r") as f:
                pub_b64 = f.read().strip()
                print("🔑 Public key loaded")
        except FileNotFoundError:
            print(f"⚠️ Key file not found, sending unencrypted")
            use_encryption = False
    
    sender = DNSSender(target, pub_b64 if use_encryption else None)
    success = False
    
    if choice in ["2", "3"]:
        if not VOICE_SUPPORT:
            print("\n❌ Voice support not installed!")
            print("   Install: pip install sounddevice soundfile numpy")
            sender.close()
            return
        
        duration = 1.0 if choice == "2" else 5.0
        print(f"\n🎤 Recording {duration} seconds...")
        print("📌 Make sure your microphone is working!")
        
        recorder = AudioRecorder(duration=duration)
        audio_bytes = recorder.record()
        recorder.close()
        
        if audio_bytes and len(audio_bytes) > 0:
            print(f"📊 Recorded: {len(audio_bytes)} bytes")
            success = sender.send_voice_message(audio_bytes, encrypt=use_encryption)
        else:
            print("❌ Recording failed!")
    else:
        message = input("\n💬 Message: ").strip()
        if not message:
            message = "Hello from CovertDNS!"
        success = sender.send_text_message(message, encrypt=use_encryption)
    
    sender.close()
    
    if success:
        print("\n✨ Transmission complete!")
    else:
        print("\n❌ Transmission failed!")


def run_receiver():
    """Interactive receiver interface."""
    print("=" * 60)
    print("🔐 Quantum-Safe DNS Receiver")
    print("=" * 60)
    print("\n⚠️ Administrator privileges required for port 53!\n")
    
    key_file = input("📁 Private key file (default private_key.b64, ENTER=plain mode): ").strip()
    if not key_file:
        key_file = "private_key.b64"
    
    priv_b64 = None
    try:
        with open(key_file, "r") as f:
            priv_b64 = f.read().strip()
            print("🔑 Private key loaded")
    except FileNotFoundError:
        print(f"⚠️ No private key - plain text only")
    
    if VOICE_SUPPORT:
        print("\n🎤 Voice support ACTIVE")
        print("   Voice messages will be saved to: received_voices/ folder")
    else:
        print("\n⚠️ Voice support DISABLED")
    
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
        print("🕵️ CovertDNS - Quantum-Safe DNS Tunnel")
        print("=" * 60)
        print("\nCommands:")
        print("  python dns_tunnel.py genkeys   - Generate keypair")
        print("  python dns_tunnel.py sender    - Send text or voice message")
        print("  python dns_tunnel.py receiver  - Receive messages")
        print("\n📖 Important Notes:")
        print("  1. Administrator/root privileges required for port 53")
        print("  2. Voice files are saved in 'received_voices' folder")
        print("\n🎤 Voice messages require:")
        print("  pip install sounddevice soundfile numpy")