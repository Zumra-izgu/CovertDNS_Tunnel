#!/usr/bin/env python3
"""
CovertDNS - Quantum-Safe DNS Tunnel
Port 53 Support - Windows/Linux/macOS
With Voice Message + Text Message Support
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

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from shared.constants import (
    DNS_PORT, FALLBACK_PORTS, BASE_DOMAIN, MAX_CHUNK_SIZE,
    MIN_DELAY_MS, MAX_DELAY_MS, ALLOWED_SENDER_IPS,
    MAX_PACKETS_PER_SECOND, BURST_SIZE, IS_WINDOWS, IS_LINUX,
    JITTER, IS_ADMIN, BYPASS_MDNS_CONFLICT, USE_RAW_SOCKET
)
from encryption.hybrid_crypto import HybridCrypto

# Voice support with try-except
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
        def __init__(self, duration: float = 1.0):
            self.SAMPLE_RATE = 8000
            self.DURATION = duration
            self.CHANNELS = 1
            
        def record(self) -> bytes:
            print(f"\n🎙️ Recording {self.DURATION} seconds of audio... Speak now!")
            
            try:
                recording = sd.rec(int(self.DURATION * self.SAMPLE_RATE),
                                  samplerate=self.SAMPLE_RATE,
                                  channels=self.CHANNELS,
                                  dtype='float32')
                sd.wait()
                
                if np.any(np.isnan(recording)) or np.any(np.isinf(recording)):
                    print("⚠️ Audio recording error, using silence")
                    recording = np.zeros((int(self.DURATION * self.SAMPLE_RATE), self.CHANNELS), dtype='float32')
                
                max_val = np.max(np.abs(recording))
                if max_val > 0.01:
                    recording = recording / max_val
                
                recording_clipped = np.clip(recording, -1.0, 1.0)
                recording_int16 = (recording_clipped * 32767).astype(np.int16)
                
                print("✅ Recording complete!")
                
                wav_buffer = io.BytesIO()
                sf.write(wav_buffer, recording_int16, self.SAMPLE_RATE, format='wav')
                wav_buffer.seek(0)
                
                return wav_buffer.getvalue()
            except Exception as e:
                print(f"❌ Recording error: {e}")
                return b""
        
        def close(self):
            pass
    
    class AudioPlayerClass:
        def __init__(self):
            pass
            
        def play(self, audio_bytes: bytes):
            print("\n🔊 Playing audio...")
            try:
                import tempfile
                import subprocess
                
                with tempfile.NamedTemporaryFile(suffix='.wav', delete=False) as tmp:
                    tmp.write(audio_bytes)
                    tmp_path = tmp.name
                
                if IS_WINDOWS:
                    os.startfile(tmp_path)
                else:
                    subprocess.call(['xdg-open', tmp_path])
                
                print(f"✅ Audio player opened for: {tmp_path}")
            except Exception as e:
                print(f"⚠️ Could not open player: {e}")
                print(f"   File saved, you can play it manually")
        
        def close(self):
            pass
    
    class VoiceMessageHandlerClass:
        @staticmethod
        def audio_to_base64(audio_bytes: bytes) -> str:
            return base64.b64encode(audio_bytes).decode('ascii')
        
        @staticmethod
        def base64_to_audio(b64_string: str) -> bytes:
            return base64.b64decode(b64_string)
        
        @staticmethod
        def save_audio(audio_bytes: bytes, folder: str = "received_voices", filename: str = None):
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
    
    AudioRecorder = AudioRecorderClass
    AudioPlayer = AudioPlayerClass
    VoiceMessageHandler = VoiceMessageHandlerClass
    VOICE_SUPPORT = True
    print("🎤 Voice support ACTIVE (sounddevice)")
    
except ImportError as e:
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


class RateLimiter:
    def __init__(self, max_packets_per_sec: int, burst_size: int):
        self.max_packets = max_packets_per_sec
        self.burst_size = burst_size
        self.packets = []
        self.lock = threading.Lock()
    
    def allow(self) -> bool:
        with self.lock:
            now = time.time()
            self.packets = [p for p in self.packets if now - p < 1.0]
            if len(self.packets) >= self.max_packets + self.burst_size:
                return False
            self.packets.append(now)
            return True


class RawSocketHandler:
    @staticmethod
    def create_raw_socket():
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


class DNSSender:
    def __init__(self, target_ip: str, recipient_public_key_b64: str = None):
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
        return self._send_message(message, is_voice=False, encrypt=encrypt)
    
    def send_voice_message(self, audio_bytes: bytes, encrypt: bool = True) -> bool:
        audio_b64 = VoiceMessageHandler.audio_to_base64(audio_bytes)
        return self._send_message(audio_b64, is_voice=True, encrypt=encrypt)
    
    def _send_message(self, data: str, is_voice: bool = False, encrypt: bool = True) -> bool:
        msg_type = "🎤 VOICE" if is_voice else "💬 TEXT"
        encrypt_status = "🔒 ENCRYPTED" if encrypt else "🔓 PLAIN"
        print(f"\n📡 Sending {msg_type} ({encrypt_status}) to {self.target_ip}:{DNS_PORT}")
        
        if encrypt and self.public_key:
            encrypted_data = HybridCrypto.encrypt_for_dns(data, self.public_key)
        else:
            encrypted_data = base64.b64encode(data.encode()).decode()
        
        if is_voice:
            final_data = f"VOICE:{encrypted_data}"
        else:
            final_data = f"TEXT:{encrypted_data}"
        
        chunks = []
        for i in range(0, len(final_data), MAX_CHUNK_SIZE):
            chunks.append(final_data[i:i + MAX_CHUNK_SIZE])
        
        chunks[0] = f"T{len(chunks):03d}" + chunks[0]
        
        print(f"✂️ Split into {len(chunks)} chunks")
        
        for i, chunk in enumerate(chunks):
            self.seq += 1
            domain = f"{self.seq:04d}.{chunk}.{BASE_DOMAIN}"
            
            if not self._send_single_query(domain, i, len(chunks)):
                return False
            
            delay = random.uniform(MIN_DELAY_MS / 1000, MAX_DELAY_MS / 1000)
            time.sleep(max(0.01, delay))
        
        print(f"\n✅ {msg_type} message sent!")
        return True
    
    def _send_single_query(self, domain: str, chunk_num: int, total: int) -> bool:
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
        self.sock.close()


class DNSReceiver:
    def __init__(self, private_key_b64: str = None):
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
        try:
            domain = self._extract_domain(data)
            if not domain or not domain.endswith(BASE_DOMAIN):
                return
            
            # Send DNS response
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
        parts = domain.split('.')
        result = b''
        for part in parts:
            result += len(part).to_bytes(1, 'big')
            result += part.encode('ascii')
        result += b'\x00'
        return result
    
    def _try_reassemble(self, client_ip: str):
        msg_data = self.messages.get(client_ip)
        if not msg_data:
            return
        
        chunks = msg_data['chunks']
        total_chunks = msg_data.get('total_chunks')
        
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
                
                # Try to decrypt if we have a key
                decrypted = None
                if self.private_key:
                    try:
                        decrypted = HybridCrypto.decrypt_from_dns(encoded, self.private_key)
                    except:
                        pass
                
                # If decryption failed or no key, try base64 decode
                if decrypted is None:
                    try:
                        decrypted = base64.b64decode(encoded).decode()
                    except:
                        decrypted = encoded
                
                # Check message type
                if decrypted.startswith("VOICE:"):
                    audio_b64 = decrypted[6:]
                    audio_bytes = base64.b64decode(audio_b64)
                    
                    # Save the audio file
                    filepath = VoiceMessageHandler.save_audio(audio_bytes)
                    
                    print(f"\n{'='*60}")
                    print(f"🎤 VOICE MESSAGE RECEIVED! [{client_ip}]")
                    print(f"{'='*60}")
                    print(f"📦 Audio size: {len(audio_bytes)} bytes")
                    print(f"💾 Saved: {filepath}")
                    print(f"🕐 Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
                    print(f"{'='*60}\n")
                    
                    # Try to play automatically
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
        self.running = False
        if self.sock:
            self.sock.close()
        print("\n🛑 DNS Receiver stopped")


def generate_keys():
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


def run_sender():
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