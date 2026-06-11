"""
Kyber-768 Key Encapsulation Mechanism (KEM)

Implementation of the Kyber-768 post-quantum key encapsulation mechanism as
standardized by NIST in FIPS 203 (Module-Lattice-Based Key-Encapsulation
Mechanism - ML-KEM). Kyber is a lattice-based cryptosystem that provides
security against attacks by quantum computers using Shor's algorithm.

Kyber-768 offers security roughly equivalent to AES-192 in the classical
setting and provides NIST security level 3 (the second-highest level,
suitable for most applications).

Key Parameters (Kyber-768):
    - Public key size: 1,184 bytes
    - Private key size: 2,400 bytes
    - Ciphertext size: 1,088 bytes
    - Shared secret size: 32 bytes (after SHA-256 hashing)

The key exchange protocol:
    1. Receiver generates a keypair and shares the public key
    2. Sender uses the public key to encapsulate a shared secret
    3. Sender sends the ciphertext to the receiver
    4. Receiver decapsulates to recover the same shared secret

This implementation uses the kyber-py library, a pure Python implementation
of Kyber-768 that is compatible with the NIST standard.
"""

import hashlib
import sys
import base64

# Attempt to import the Kyber-768 implementation
try:
    from kyber_py.kyber import Kyber768
except ImportError:
    print("ERROR: kyber-py not installed. Run: pip install kyber-py")
    sys.exit(1)

# Configure stdout encoding for cross-platform compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class KyberKEM:
    """
    Kyber-768 Key Encapsulation Mechanism (KEM) for post-quantum key exchange.
    
    This class provides a simplified interface to the Kyber-768 KEM operations,
    handling the underlying library's API quirks and providing consistent
    return values. The class follows the standard KEM workflow:
        - generate_keypair(): Receiver generates (pk, sk)
        - encapsulate(): Sender encapsulates (ss, ct)
        - decapsulate(): Receiver recovers ss from ct
    
    All shared secrets are post-processed with SHA-256 to ensure uniform
    distribution and 256-bit security strength for use with AES-256.
    
    NIST Standard:
        - Algorithm: ML-KEM (Module-Lattice-Based Key-Encapsulation Mechanism)
        - FIPS Publication: FIPS 203 (August 2024)
        - Parameter Set: ML-KEM-768 (security level 3)
    
    Usage Example:
        # Receiver (Alice)
        public_key, private_key = KyberKEM.generate_keypair()
        
        # Sender (Bob) - using Alice's public key
        ciphertext, shared_secret = KyberKEM.encapsulate(public_key)
        
        # Receiver (Alice) - using the ciphertext from Bob
        recovered_secret = KyberKEM.decapsulate(ciphertext, private_key)
        # shared_secret == recovered_secret
    """
    
    @staticmethod
    def generate_keypair():
        """
        Generate a new Kyber-768 keypair.
        
        The keypair consists of:
            - Public key: 1,184 bytes - share with senders
            - Private key: 2,400 bytes - keep secret
        
        Returns:
            tuple: (public_key_bytes, private_key_bytes)
            
        Example:
            >>> public_key, private_key = KyberKEM.generate_keypair()
        """
        public_key, private_key = Kyber768.keygen()
        return public_key, private_key
    
    @staticmethod
    def encapsulate(public_key: bytes):
        """
        Encapsulate a shared secret using a recipient's public key.
        
        This operation is performed by the sender. It generates a random
        shared secret, encapsulates it using the recipient's public key,
        and produces a ciphertext that can be sent to the recipient.
        
        Args:
            public_key: Recipient's Kyber-768 public key (1,184 bytes).
        
        Returns:
            tuple: (ciphertext, shared_secret)
                - ciphertext (bytes): 1,088 bytes, sent to recipient
                - shared_secret (bytes): 32 bytes, used for symmetric encryption
        
        Example:
            >>> ciphertext, shared_secret = KyberKEM.encapsulate(public_key)
        """
        # kyber-py returns (shared_secret, ciphertext)
        # We reorder to maintain consistent return format
        raw_shared_secret, ciphertext = Kyber768.encaps(public_key)
        # Hash to ensure uniform distribution and 256-bit security
        shared_secret = hashlib.sha256(raw_shared_secret).digest()
        return ciphertext, shared_secret
    
    @staticmethod
    def decapsulate(ciphertext: bytes, private_key: bytes):
        """
        Decapsulate a shared secret using a recipient's private key.
        
        This operation is performed by the recipient. It recovers the
        original shared secret from the ciphertext using the private key.
        
        Args:
            ciphertext: Kyber ciphertext from the sender (1,088 bytes).
            private_key: Recipient's Kyber-768 private key (2,400 bytes).
        
        Returns:
            bytes: The recovered shared secret (32 bytes), identical to the
                   sender's shared secret.
        
        Example:
            >>> shared_secret = KyberKEM.decapsulate(ciphertext, private_key)
        """
        raw_shared_secret = Kyber768.decaps(private_key, ciphertext)
        # Apply the same hash as in encapsulate()
        shared_secret = hashlib.sha256(raw_shared_secret).digest()
        return shared_secret
    
    @staticmethod
    def keypair_to_b64(public_key: bytes, private_key: bytes) -> tuple:
        """
        Convert a keypair to Base64 strings for storage or transmission.
        
        Base64 encoding makes the binary keys safe for JSON serialization,
        environment variables, or transmission over text-based protocols.
        
        Args:
            public_key: Raw public key bytes (1,184 bytes).
            private_key: Raw private key bytes (2,400 bytes).
        
        Returns:
            tuple: (public_key_base64, private_key_base64)
            
        Example:
            >>> pub_b64, priv_b64 = KyberKEM.keypair_to_b64(pub, priv)
        """
        return base64.b64encode(public_key).decode(), base64.b64encode(private_key).decode()
    
    @staticmethod
    def keypair_from_b64(public_b64: str, private_b64: str) -> tuple:
        """
        Load a keypair from Base64 strings.
        
        This method reverses the keypair_to_b64 operation.
        
        Args:
            public_b64: Base64-encoded public key string.
            private_b64: Base64-encoded private key string.
        
        Returns:
            tuple: (public_key_bytes, private_key_bytes)
            
        Example:
            >>> pub, priv = KyberKEM.keypair_from_b64(pub_b64, priv_b64)
        """
        return base64.b64decode(public_b64), base64.b64decode(private_b64)


if __name__ == "__main__":
    """
    Standalone test routine for Kyber-768 KEM.
    
    This test verifies the core KEM functionality:
        1. Keypair generation
        2. Encapsulation using the public key
        3. Decapsulation using the private key
        4. Shared secret equality check
    
    A successful test confirms that the Kyber-768 implementation is
    functioning correctly and that both parties obtain the same shared secret.
    """
    print("=" * 50)
    print("Kyber-768 KEM Test (NIST FIPS 203)")
    print("=" * 50)
    
    # Generate keypair (receiver side)
    pub, priv = KyberKEM.generate_keypair()
    print(f"\n✅ Keypair generated")
    print(f"   Public key: {len(pub)} bytes")
    print(f"   Private key: {len(priv)} bytes")
    
    # Encapsulate shared secret (sender side)
    cipher, ss1 = KyberKEM.encapsulate(pub)
    print(f"📦 Encapsulation complete")
    print(f"   Ciphertext: {len(cipher)} bytes")
    
    # Decapsulate shared secret (receiver side)
    ss2 = KyberKEM.decapsulate(cipher, priv)
    
    # Verify shared secrets match
    if ss1 == ss2:
        print("\n🎉 Shared secrets match! Key exchange successful!")
        print(f"   Shared secret size: {len(ss1)} bytes (AES-256 key)")
    else:
        print("\n❌ Shared secrets do NOT match! Key exchange failed.")