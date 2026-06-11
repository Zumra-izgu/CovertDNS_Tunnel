"""
CovertDNS - Unit Tests
"""

import base64
import json
import unittest
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from encryption.aes_cipher import AESCipher
from encryption.kyber_kem import KyberKEM
from encryption.hybrid_crypto import HybridCrypto
from dns_tunnel import DNSSender, DNSReceiver


class TestEncryption(unittest.TestCase):
    """Test encryption modules"""
    
    def test_aes_round_trip(self):
        key = b"a" * 32
        plaintext = "Merhaba Dünya! 🚀"
        
        encrypted = AESCipher.encrypt_to_json(plaintext, key)
        decrypted = AESCipher.decrypt_from_json(encrypted, key)
        
        self.assertEqual(plaintext, decrypted)
    
    def test_kyber_kem(self):
        pub, priv = KyberKEM.generate_keypair()
        cipher, ss1 = KyberKEM.encapsulate(pub)
        ss2 = KyberKEM.decapsulate(cipher, priv)
        
        self.assertEqual(ss1, ss2)
        self.assertEqual(len(ss1), 32)
    
    def test_hybrid_crypto(self):
        pub, priv = HybridCrypto.generate_keypair()
        plaintext = "Secret message with Kyber-768 + AES-256! 🔐"
        
        encrypted = HybridCrypto.encrypt_message(plaintext, pub)
        decrypted = HybridCrypto.decrypt_message(encrypted, priv)
        
        self.assertEqual(plaintext, decrypted)
    
    def test_hybrid_dns_format(self):
        pub, priv = HybridCrypto.generate_keypair()
        plaintext = "DNS tunnel test"
        
        encrypted = HybridCrypto.encrypt_for_dns(plaintext, pub)
        decrypted = HybridCrypto.decrypt_from_dns(encrypted, priv)
        
        self.assertEqual(plaintext, decrypted)
    
    def test_aes_key_length(self):
        with self.assertRaises(ValueError):
            AESCipher.encrypt("test", b"short")
        
        with self.assertRaises(ValueError):
            AESCipher.decrypt(b"test", b"short", b"nonce", b"tag")


class TestDNSPackets(unittest.TestCase):
    """Test DNS packet building"""
    
    def test_domain_encoding(self):
        sender = DNSSender("127.0.0.1")
        encoded = sender._encode_domain_name("test.example.com")
        
        # Check format: \x04test\x07example\x03com\x00
        self.assertEqual(encoded[0], 4)
        self.assertEqual(encoded[1:5], b'test')
        self.assertEqual(encoded[5], 7)
        self.assertEqual(encoded[6:13], b'example')
        self.assertEqual(encoded[13], 3)
        self.assertEqual(encoded[14:17], b'com')
        self.assertEqual(encoded[17], 0)
    
    def test_dns_query_build(self):
        sender = DNSSender("127.0.0.1")
        query = sender.build_dns_query("test.covert.local")
        
        # Minimum DNS query size
        self.assertGreaterEqual(len(query), 12)
        
        # Check header fields
        self.assertEqual(len(query[2:4]), 2)  # Flags
        self.assertEqual(len(query[4:6]), 2)  # QDCOUNT


if __name__ == "__main__":
    print("=" * 60)
    print("🧪 Running CovertDNS Tests")
    print("=" * 60)
    unittest.main(verbosity=2)