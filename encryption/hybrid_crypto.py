"""
Hybrid Cryptography: Kyber-768 (PQC) + AES-256-GCM

This module implements hybrid encryption that combines post-quantum key exchange
(Kyber-768 / ML-KEM) with AES-256-GCM symmetric encryption. The hybrid approach
provides the security benefits of both systems:
    - Kyber-768 enables quantum-resistant key exchange
    - AES-256-GCM provides efficient and authenticated bulk encryption

The encryption workflow:
    1. Sender obtains recipient's Kyber-768 public key
    2. Sender performs Kyber encapsulation to generate a shared secret
    3. Sender uses the shared secret as an AES-256 key
    4. Sender encrypts the message with AES-256-GCM
    5. Both the Kyber ciphertext and AES-encrypted data are transmitted

Security Note: JSON serialization is used instead of pickle to prevent
arbitrary code execution vulnerabilities that could arise from deserializing
untrusted pickle data.

NIST Standards:
    - ML-KEM (Kyber-768): FIPS 203
    - AES-256-GCM: NIST SP 800-38D
"""

import base64
import json
import sys
from typing import Dict, Any

from encryption.kyber_kem import KyberKEM
from encryption.aes_cipher import AESCipher

# Configure stdout encoding for cross-platform compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class HybridCrypto:
    """
    Hybrid encryption combining Kyber-768 (post-quantum) and AES-256-GCM.
    
    This class provides static methods for end-to-end encrypted messaging
    that remains secure against both classical and quantum adversaries.
    The hybrid approach is NIST-recommended for transitioning to post-quantum
    cryptography while maintaining compatibility with existing systems.
    
    Key Properties:
        - Forward Secrecy: Each message uses a new ephemeral shared secret
        - Authenticated Encryption: AES-GCM provides integrity protection
        - Quantum Resistance: Kyber-768 resists Shor's algorithm attacks
        - JSON-safe Output: All outputs are Base64-encoded for safe transport
    """
    
    @staticmethod
    def generate_keypair():
        """
        Generate a Kyber-768 keypair for a recipient.
        
        The keypair consists of:
            - Public key: 1,184 bytes (Base64 encoded for storage)
            - Private key: 2,400 bytes (Base64 encoded for storage)
        
        Returns:
            tuple: (public_key_bytes, private_key_bytes)
            
        Example:
            >>> pub, priv = HybridCrypto.generate_keypair()
            >>> # Share pub with senders, keep priv secret
        """
        return KyberKEM.generate_keypair()
    
    @staticmethod
    def encrypt_message(message: str, recipient_public_key: bytes) -> Dict[str, Any]:
        """
        Encrypt a message for a specific recipient using hybrid encryption.
        
        This method performs two main operations:
            1. Kyber encapsulation: Generates a shared secret and ciphertext
            2. AES-256-GCM encryption: Encrypts the message using the shared secret
        
        Args:
            message: Plaintext message to encrypt (UTF-8 string).
            recipient_public_key: Recipient's Kyber-768 public key (raw bytes).
        
        Returns:
            dict: A dictionary containing:
                - 'kyber_ciphertext': Base64-encoded Kyber ciphertext (1,088 bytes)
                - 'encrypted_data': AES-256-GCM encrypted message as JSON dict
        
        Example:
            >>> encrypted = HybridCrypto.encrypt_message("Secret", recipient_pub)
            >>> # Send encrypted['kyber_ciphertext'] and encrypted['encrypted_data']
        """
        # Step 1: Kyber encapsulation - generate shared secret and ciphertext
        kyber_ciphertext, shared_secret = KyberKEM.encapsulate(recipient_public_key)
        
        # Step 2: AES encryption with the Kyber-derived shared secret
        # The shared secret is exactly 32 bytes, suitable for AES-256
        encrypted_data = AESCipher.encrypt_to_json(message, shared_secret)
        
        # Return both components as a JSON-serializable dictionary
        return {
            'kyber_ciphertext': base64.b64encode(kyber_ciphertext).decode('ascii'),
            'encrypted_data': encrypted_data
        }
    
    @staticmethod
    def decrypt_message(encrypted_package: Dict[str, Any], private_key: bytes) -> str:
        """
        Decrypt a message from a sender using hybrid decryption.
        
        This method reverses the encryption process:
            1. Kyber decapsulation: Recovers the shared secret from the ciphertext
            2. AES-256-GCM decryption: Decrypts the message using the shared secret
        
        Args:
            encrypted_package: Dictionary containing:
                - 'kyber_ciphertext': Base64-encoded Kyber ciphertext
                - 'encrypted_data': AES-256-GCM encrypted message as JSON dict
            private_key: Recipient's Kyber-768 private key (raw bytes).
        
        Returns:
            str: Decrypted plaintext message.
        
        Raises:
            cryptography.exceptions.InvalidTag: If authentication fails
            Exception: If decryption otherwise fails
        
        Example:
            >>> plaintext = HybridCrypto.decrypt_message(encrypted, recipient_priv)
        """
        # Step 1: Kyber decapsulation - recover the shared secret
        kyber_ciphertext = base64.b64decode(encrypted_package['kyber_ciphertext'])
        shared_secret = KyberKEM.decapsulate(kyber_ciphertext, private_key)
        
        # Step 2: AES decryption with the recovered shared secret
        plaintext = AESCipher.decrypt_from_json(
            encrypted_package['encrypted_data'],
            shared_secret
        )
        
        return plaintext
    
    @staticmethod
    def encrypt_for_dns(message: str, recipient_public_key: bytes) -> str:
        """
        Encrypt a message and encode it for DNS transport.
        
        This convenience method combines encryption with Base64 encoding
        to produce a string that can be safely embedded in DNS queries.
        The output contains both the Kyber ciphertext and AES-encrypted data.
        
        Args:
            message: Plaintext message to encrypt.
            recipient_public_key: Recipient's Kyber-768 public key.
        
        Returns:
            str: Single Base64-encoded string containing the complete
                 encrypted package, ready for DNS transmission.
        
        Example:
            >>> dns_payload = HybridCrypto.encrypt_for_dns("Secret", pub)
            >>> # Send dns_payload inside a DNS query
        """
        encrypted = HybridCrypto.encrypt_message(message, recipient_public_key)
        # Serialize to JSON and Base64-encode for DNS-safe transport
        return base64.b64encode(json.dumps(encrypted).encode()).decode('ascii')
    
    @staticmethod
    def decrypt_from_dns(encrypted_b64: str, private_key: bytes) -> str:
        """
        Decrypt a message received from DNS transport.
        
        This convenience method reverses encrypt_for_dns by:
            1. Base64 decoding the input
            2. JSON deserializing to recover the encrypted package
            3. Performing hybrid decryption
        
        Args:
            encrypted_b64: Base64-encoded encrypted package string.
            private_key: Recipient's Kyber-768 private key.
        
        Returns:
            str: Decrypted plaintext message.
        
        Example:
            >>> plaintext = HybridCrypto.decrypt_from_dns(dns_payload, priv)
        """
        # Reverse the DNS encoding process
        encrypted_json = json.loads(base64.b64decode(encrypted_b64.encode('ascii')).decode())
        return HybridCrypto.decrypt_message(encrypted_json, private_key)


if __name__ == "__main__":
    """
    Standalone test routine for hybrid cryptography.
    
    This test verifies the complete hybrid encryption workflow:
        1. Keypair generation
        2. Encryption using the public key
        3. Decryption using the private key
        4. Round-trip integrity check
    
    A successful test confirms that both Kyber and AES components
    are functioning correctly together.
    """
    print("=" * 60)
    print("Hybrid Cryptography Test (Kyber-768 + AES-256-GCM)")
    print("=" * 60)
    
    # Alice generates her keypair (recipient)
    alice_pub, alice_priv = HybridCrypto.generate_keypair()
    print(f"\n✅ Keypair generated")
    print(f"   Public key size: {len(alice_pub)} bytes")
    print(f"   Private key size: {len(alice_priv)} bytes")
    
    # Bob encrypts a message for Alice using her public key
    secret = "Hello Alice! This message is encrypted with Kyber-768 and AES-256. 🚀"
    print(f"\n📝 Original message: {secret}")
    
    encrypted = HybridCrypto.encrypt_message(secret, alice_pub)
    print(f"🔐 Encrypted package created")
    print(f"   Kyber ciphertext size: {len(encrypted['kyber_ciphertext'])} chars (Base64)")
    
    # Alice decrypts the message using her private key
    decrypted = HybridCrypto.decrypt_message(encrypted, alice_priv)
    
    # Verify the round-trip was successful
    if secret == decrypted:
        print("\n🎉 SUCCESS! Hybrid encryption/decryption works correctly!")
        print("   Kyber-768 key exchange + AES-256-GCM bulk encryption")
    else:
        print("\n❌ FAILURE! Encryption/decryption round-trip failed.")