#!/usr/bin/env python3
"""
CovertDNS - Quantum-Safe DNS Tunnel
Port 53 Support - Windows/Linux/macOS
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


class RateLimiter:
    """Rate limiting for anti-detection"""
    
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
    """Windows için raw socket handler (port 53 için)"""
    
    @staticmethod
    def create_raw_socket():
        """Raw socket oluştur (Windows'ta port 53 dinlemek için)"""
        if not IS_WINDOWS:
            return None
        
        try:
            # IP header include etmek için raw socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_UDP)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            
            # Windows'ta raw socket için admin gerekir
            if not IS_ADMIN:
                print("⚠️ Raw socket için Administrator yetkisi gerekli!")
                return None
            
            return sock
        except Exception as e:
            print(f"⚠️ Raw socket oluşturulamadı: {e}")
            return None
    
    @staticmethod
    def parse_udp_packet(data: bytes) -> tuple:
        """Raw socket'ten gelen UDP paketini parse et"""
        try:
            # IP header (20 bytes minimum)
            ip_header = data[:20]
            iph = struct.unpack('!BBHHHBBH4s4s', ip_header)
            
            # IP header length
            ip_header_len = (iph[0] & 0x0F) * 4
            
            # UDP header (8 bytes)
            udp_header = data[ip_header_len:ip_header_len + 8]
            udph = struct.unpack('!HHHH', udp_header)
            
            source_port = udph[0]
            dest_port = udph[1]
            udp_len = udph[2]
            
            # UDP payload
            payload = data[ip_header_len + 8:ip_header_len + udp_len]
            
            return source_port, dest_port, payload
        except Exception as e:
            return None, None, None


class DNSSender:
    """Quantum-safe DNS tunnel sender - Port 53 desteği ile"""
    
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
            print("🔒 Encryption enabled (Kyber-768 + AES-256-GCM)")
    
    def build_dns_query(self, domain: str) -> bytes:
        """Build DNS query packet (RFC 1035 compliant)"""
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
    
    def send_message(self, message: str) -> bool:
        print(f"\n📡 DNS Sender - Sending to {self.target_ip}:{DNS_PORT}")
        print(f"💬 Original message: {message}")
        
        if self.public_key:
            print("🔐 Encrypting with Kyber-768 + AES-256...")
            data_to_send = HybridCrypto.encrypt_for_dns(message, self.public_key)
        else:
            print("⚠️ No public key, sending unencrypted!")
            data_to_send = base64.b64encode(message.encode()).decode()
        
        print(f"📦 Encrypted data size: {len(data_to_send)} chars")
        
        chunks = []
        for i in range(0, len(data_to_send), MAX_CHUNK_SIZE):
            chunks.append(data_to_send[i:i + MAX_CHUNK_SIZE])
        
        chunks[0] = f"T{len(chunks):03d}" + chunks[0]
        
        print(f"✂️ Split into {len(chunks)} chunks (max {MAX_CHUNK_SIZE} chars)")
        
        for i, chunk in enumerate(chunks):
            self.seq += 1
            domain = f"{self.seq:04d}.{chunk}.{BASE_DOMAIN}"
            
            if not self._send_single_query(domain, i, len(chunks)):
                return False
            
            delay = random.uniform(MIN_DELAY_MS / 1000, MAX_DELAY_MS / 1000)
            if JITTER:
                delay += random.uniform(-0.03, 0.03)
            time.sleep(max(0.01, delay))
        
        print(f"\n✅ Message sent successfully!")
        return True
    
    def _send_single_query(self, domain: str, chunk_num: int, total: int) -> bool:
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
        self.sock.close()


class DNSReceiver:
    """Quantum-safe DNS tunnel receiver - Port 53 desteği ile"""
    
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
            print("⚠️ No private key - decryption disabled")
        
        print(f"🔐 DNSReceiver initialized (Port {DNS_PORT} mode)")
        print(f"📋 Whitelist: {list(ALLOWED_SENDER_IPS)}")
        
        if DNS_PORT == 53 and IS_WINDOWS and not IS_ADMIN:
            print("\n⚠️⚠️⚠️ UYARI ⚠️⚠️⚠️")
            print("Port 53 kullanmak için Administrator yetkisi gerekir!")
            print("Lütfen PowerShell'i Administrator olarak çalıştırın ve tekrar deneyin.")
            print("veya 'python dns_tunnel.py receiver' komutunu Admin terminalde çalıştırın.\n")
    
    def _compile_whitelist(self, patterns) -> list:
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
        """Start listening on DNS port 53"""
        
        # Önce UDP socket dene
        ports_to_try = [DNS_PORT] + FALLBACK_PORTS
        
        for port in ports_to_try:
            try:
                self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                
                # Windows'ta SO_EXCLUSIVEADDRUSE dene (port 53 için)
                if IS_WINDOWS and port == 53:
                    try:
                        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
                    except:
                        pass
                
                self.sock.bind(('0.0.0.0', port))
                self.running = True
                
                print(f"\n✅ DNS Receiver started on port {port}")
                
                if port == 53:
                    print("🎯 Port 53 başarıyla bağlandı!")
                    if IS_WINDOWS:
                        print("⚠️ Not: mDNS (Bonjour) ile çakışma olabilir.")
                        print("   Eğer sorun yaşarsanız: net stop dnscache")
                break
                
            except PermissionError:
                print(f"❌ Port {port} requires administrator privileges")
                if port == 53:
                    print("   → Port 53 için lütfen Administrator olarak çalıştırın")
            except OSError as e:
                if "Address already in use" in str(e) or "Only one usage" in str(e):
                    print(f"❌ Port {port} already in use")
                    if port == 53 and BYPASS_MDNS_CONFLICT:
                        print("   → mDNS çakışması olabilir. Raw socket deneniyor...")
                        if self._try_raw_socket():
                            break
                else:
                    print(f"❌ Failed to bind port {port}: {e}")
            except Exception as e:
                print(f"❌ Unexpected error on port {port}: {e}")
        else:
            print("\n❌ Could not bind to any port.")
            print("\nÇözüm önerileri:")
            print("1. Administrator olarak çalıştırın")
            print("2. DNS Client servisini durdurun: net stop dnscache")
            print("3. mDNS/Bonjour servisini durdurun")
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
        """Raw socket ile port 53'ü dinlemeyi dene"""
        try:
            if not IS_WINDOWS:
                return False
            
            self.raw_sock = RawSocketHandler.create_raw_socket()
            if not self.raw_sock:
                return False
            
            # Raw socket ile dinleme thread'i başlat
            self.running = True
            threading.Thread(target=self._raw_socket_listener, daemon=True).start()
            print("✅ Raw socket mode active for port 53")
            return True
        except Exception as e:
            print(f"❌ Raw socket failed: {e}")
            return False
    
    def _raw_socket_listener(self):
        """Raw socket ile paket dinle"""
        while self.running:
            try:
                self.raw_sock.settimeout(1.0)
                data, addr = self.raw_sock.recvfrom(65535)
                
                src_port, dst_port, payload = RawSocketHandler.parse_udp_packet(data)
                
                if dst_port == DNS_PORT and payload:
                    self._handle_dns_packet(payload, addr)
                    
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    pass
    
    def _handle_dns_packet(self, data: bytes, addr: tuple):
        """DNS paketini işle"""
        try:
            domain = self._extract_domain(data)
            
            # Sadece bizim domain'imize ait sorguları işle
            if not domain or not domain.endswith(BASE_DOMAIN):
                return
            
            # DNS cevabı gönder (legitimate görünmesi için)
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
                        self.messages[client_ip] = {
                            'chunks': {},
                            'total_chunks': None,
                            'last_update': time.time()
                        }
                    
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
                    
        except Exception as e:
            pass
    
    def _extract_domain(self, data: bytes) -> str:
        """DNS sorgusundan domain adını çıkar"""
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
        """DNS cevabı oluştur"""
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
                
                if self.private_key:
                    message = HybridCrypto.decrypt_from_dns(encoded, self.private_key)
                else:
                    message = base64.b64decode(encoded).decode()
                
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
        self.running = False
        if self.sock:
            self.sock.close()
        if self.raw_sock:
            self.raw_sock.close()
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
    print("🔐 Quantum-Safe DNS Sender (Port 53)")
    print("=" * 60)
    
    target = input("\n🎯 Target IP (default 127.0.0.1): ").strip()
    if not target:
        target = "127.0.0.1"
    
    message = input("💬 Message: ").strip()
    if not message:
        message = "Hello from CovertDNS on port 53!"
    
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
    success = sender.send_message(message)
    sender.close()
    
    if success:
        print("\n✨ Message transmission complete!")
    else:
        print("\n❌ Transmission failed!")


def run_receiver():
    print("=" * 60)
    print("🔐 Quantum-Safe DNS Receiver (Port 53)")
    print("=" * 60)
    print("\n⚠️ Port 53 için Administrator yetkisi gerekir!\n")
    
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
        print("\n📖 Port 53 için önemli notlar:")
        print("  1. Administrator/root yetkisi gerekir")
        print("  2. Windows'ta: PowerShell'i Administrator olarak açın")
        print("  3. Linux/Mac'te: sudo kullanın")