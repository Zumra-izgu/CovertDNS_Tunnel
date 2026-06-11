"""
AES-256-GCM Authenticated Encryption
Fixed: Better error handling and encoding
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os
import sys
import json
import base64

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AESCipher:
    """AES-256-GCM for message encryption"""
    
    @staticmethod
    def encrypt(plaintext: str, key: bytes):
        """Encrypt plaintext with AES-256-GCM"""
        if len(key) != 32:
            raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
        
        nonce = os.urandom(12)
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce),
            backend=default_backend()
        )
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext.encode('utf-8')) + encryptor.finalize()
        
        return ciphertext, nonce, encryptor.tag
    
    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes, nonce: bytes, tag: bytes) -> str:
        """Decrypt ciphertext with AES-256-GCM"""
        if len(key) != 32:
            raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
        
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag),
            backend=default_backend()
        )
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        return plaintext.decode('utf-8')
    
    @staticmethod
    def encrypt_to_json(plaintext: str, key: bytes) -> str:
        """Encrypt and return as JSON-serializable dict"""
        ciphertext, nonce, tag = AESCipher.encrypt(plaintext, key)
        return {
            'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
            'nonce': base64.b64encode(nonce).decode('ascii'),
            'tag': base64.b64encode(tag).decode('ascii')
        }
    
    @staticmethod
    def decrypt_from_json(encrypted_json: dict, key: bytes) -> str:
        """Decrypt from JSON dict"""
        ciphertext = base64.b64decode(encrypted_json['ciphertext'])
        nonce = base64.b64decode(encrypted_json['nonce'])
        tag = base64.b64decode(encrypted_json['tag'])
        return AESCipher.decrypt(ciphertext, key, nonce, tag)


if __name__ == "__main__":
    print("=" * 50)
    print("🔐 AES-256-GCM Test")
    print("=" * 50)
    
    key = os.urandom(32)
    original = "Bu gizli bir mesajdır! 🚀"
    print(f"Original: {original}")
    
    encrypted = AESCipher.encrypt_to_json(original, key)
    decrypted = AESCipher.decrypt_from_json(encrypted, key)
    
    if original == decrypted:
        print("\n🎉 Encryption/Decryption successful!")
    else:
        print("\n❌ Failed!")