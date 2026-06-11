"""
Hybrid Cryptography: Kyber-768 (PQC) + AES-256-GCM
Fixed: JSON instead of pickle (security)
"""

import base64
import json
import sys
from typing import Dict, Any

from encryption.kyber_kem import KyberKEM
from encryption.aes_cipher import AESCipher

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class HybridCrypto:
    """Hybrid encryption for end-to-end secure messaging"""
    
    @staticmethod
    def generate_keypair():
        """Generate Kyber-768 keypair"""
        return KyberKEM.generate_keypair()
    
    @staticmethod
    def encrypt_message(message: str, recipient_public_key: bytes) -> Dict[str, Any]:
        """Encrypt a message for a specific recipient"""
        # Step 1: Kyber encapsulation
        kyber_ciphertext, shared_secret = KyberKEM.encapsulate(recipient_public_key)
        
        # Step 2: AES encryption with shared secret
        encrypted_data = AESCipher.encrypt_to_json(message, shared_secret)
        
        return {
            'kyber_ciphertext': base64.b64encode(kyber_ciphertext).decode('ascii'),
            'encrypted_data': encrypted_data
        }
    
    @staticmethod
    def decrypt_message(encrypted_package: Dict[str, Any], private_key: bytes) -> str:
        """Decrypt a message from a sender"""
        # Step 1: Kyber decapsulation
        kyber_ciphertext = base64.b64decode(encrypted_package['kyber_ciphertext'])
        shared_secret = KyberKEM.decapsulate(kyber_ciphertext, private_key)
        
        # Step 2: AES decryption
        plaintext = AESCipher.decrypt_from_json(
            encrypted_package['encrypted_data'],
            shared_secret
        )
        
        return plaintext
    
    @staticmethod
    def encrypt_for_dns(message: str, recipient_public_key: bytes) -> str:
        """Encrypt and encode for DNS transport (base64)"""
        encrypted = HybridCrypto.encrypt_message(message, recipient_public_key)
        return base64.b64encode(json.dumps(encrypted).encode()).decode('ascii')
    
    @staticmethod
    def decrypt_from_dns(encrypted_b64: str, private_key: bytes) -> str:
        """Decrypt from DNS transport format"""
        encrypted_json = json.loads(base64.b64decode(encrypted_b64.encode('ascii')).decode())
        return HybridCrypto.decrypt_message(encrypted_json, private_key)


if __name__ == "__main__":
    print("=" * 60)
    print("🔐 HYBRID CRYPTOGRAPHY TEST")
    print("=" * 60)
    
    # Alice generates keypair
    alice_pub, alice_priv = HybridCrypto.generate_keypair()
    
    # Bob encrypts message
    secret = "Merhaba Alice! Bu mesaj Kyber-768 ve AES-256 ile şifrelendi. 🚀"
    encrypted = HybridCrypto.encrypt_message(secret, alice_pub)
    
    # Alice decrypts
    decrypted = HybridCrypto.decrypt_message(encrypted, alice_priv)
    
    if secret == decrypted:
        print("\n🎉 SUCCESS! Hybrid encryption works!")
    else:
        print("\n❌ FAILURE!")