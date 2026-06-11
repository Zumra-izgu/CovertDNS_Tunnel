"""
Kyber-768 Key Encapsulation Mechanism (KEM)
Post-Quantum Cryptography - NIST Standard (FIPS 203)
Fixed: Correct encapsulation order and error handling
"""

import hashlib
import sys
import base64

try:
    from kyber_py.kyber import Kyber768
except ImportError:
    print("❌ kyber-py not installed. Run: pip install kyber-py")
    sys.exit(1)

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class KyberKEM:
    """Kyber-768 KEM for post-quantum secure key exchange"""
    
    @staticmethod
    def generate_keypair():
        """Generate Kyber-768 keypair (Receiver side)"""
        public_key, private_key = Kyber768.keygen()
        return public_key, private_key
    
    @staticmethod
    def encapsulate(public_key: bytes):
        """Encapsulate shared secret (Sender side)
        Returns: (ciphertext, shared_secret)
        """
        # kyber-py returns (shared_secret, ciphertext)
        # We ensure order is consistent
        raw_shared_secret, ciphertext = Kyber768.encaps(public_key)
        shared_secret = hashlib.sha256(raw_shared_secret).digest()
        return ciphertext, shared_secret
    
    @staticmethod
    def decapsulate(ciphertext: bytes, private_key: bytes):
        """Decapsulate shared secret (Receiver side)"""
        raw_shared_secret = Kyber768.decaps(private_key, ciphertext)
        shared_secret = hashlib.sha256(raw_shared_secret).digest()
        return shared_secret
    
    @staticmethod
    def keypair_to_b64(public_key: bytes, private_key: bytes) -> tuple:
        """Convert keys to base64 for storage/transmission"""
        return base64.b64encode(public_key).decode(), base64.b64encode(private_key).decode()
    
    @staticmethod
    def keypair_from_b64(public_b64: str, private_b64: str) -> tuple:
        """Load keys from base64"""
        return base64.b64decode(public_b64), base64.b64decode(private_b64)


if __name__ == "__main__":
    print("=" * 50)
    print("🔐 Kyber-768 KEM Test")
    print("=" * 50)
    
    pub, priv = KyberKEM.generate_keypair()
    cipher, ss1 = KyberKEM.encapsulate(pub)
    ss2 = KyberKEM.decapsulate(cipher, priv)
    
    if ss1 == ss2:
        print("\n🎉 Shared secrets match! Key exchange successful!")
        print(f"   Shared secret size: {len(ss1)} bytes (should be 32)")
    else:
        print("\n❌ Shared secrets do NOT match!")