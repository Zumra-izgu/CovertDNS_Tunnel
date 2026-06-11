"""
AES-256-GCM Authenticated Encryption Module

This module implements AES-256-GCM (Galois/Counter Mode) authenticated encryption,
providing both confidentiality and integrity protection for messages. The GCM mode
combines encryption with authentication in a single operation, producing an
authentication tag that verifies the integrity of the ciphertext.

The implementation uses the cryptography.hazmat.primitives library, which provides
a high-level interface to the OpenSSL cryptographic primitives. All keys are
expected to be exactly 32 bytes (256 bits) as required by AES-256.

Key Features:
    - 256-bit key length for high security
    - 96-bit (12 byte) nonce for each encryption operation
    - 128-bit authentication tag for integrity verification
    - Base64 encoding for JSON-safe serialization
"""

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend
import os
import sys
import json
import base64

# Configure stdout encoding for cross-platform compatibility
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


class AESCipher:
    """
    AES-256-GCM authenticated encryption utility class.
    
    This class provides static methods for encrypting and decrypting messages
    using the AES-256-GCM algorithm. The GCM mode ensures that any tampering
    with the ciphertext or additional authenticated data (AAD) will be detected
    upon decryption.
    
    The encryption workflow:
        1. Generate a random 96-bit nonce
        2. Encrypt the plaintext using AES-256 in GCM mode
        3. Return the ciphertext, nonce, and authentication tag
        4. For storage, all components are Base64-encoded and wrapped in JSON
    
    Security Considerations:
        - Each encryption operation MUST use a unique nonce
        - Nonces are generated using os.urandom (cryptographically secure)
        - The authentication tag is verified during decryption
        - Keys must be kept secret and stored securely
    """
    
    @staticmethod
    def encrypt(plaintext: str, key: bytes):
        """
        Encrypt plaintext using AES-256-GCM.
        
        This method performs authenticated encryption of the input plaintext.
        A random nonce is generated for each encryption operation to ensure
        semantic security (identical plaintexts produce different ciphertexts).
        
        Args:
            plaintext (str): The message to encrypt. Will be UTF-8 encoded.
            key (bytes): AES-256 encryption key. Must be exactly 32 bytes.
        
        Returns:
            tuple: A three-element tuple containing:
                - ciphertext (bytes): The encrypted message
                - nonce (bytes): 12-byte random nonce used for encryption
                - tag (bytes): 16-byte authentication tag for integrity verification
        
        Raises:
            ValueError: If the provided key is not exactly 32 bytes in length.
        
        Example:
            >>> ciphertext, nonce, tag = AESCipher.encrypt("Secret message", key)
        """
        if len(key) != 32:
            raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
        
        # Generate a cryptographically random 96-bit nonce (12 bytes)
        # Each nonce must be unique per encryption operation with the same key
        nonce = os.urandom(12)
        
        # Initialize AES cipher in GCM mode with the generated nonce
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce),
            backend=default_backend()
        )
        
        # Create encryptor object and perform the encryption
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(plaintext.encode('utf-8')) + encryptor.finalize()
        
        # Return all three components needed for decryption
        return ciphertext, nonce, encryptor.tag
    
    @staticmethod
    def decrypt(ciphertext: bytes, key: bytes, nonce: bytes, tag: bytes) -> str:
        """
        Decrypt ciphertext using AES-256-GCM.
        
        This method performs authenticated decryption of the ciphertext. If the
        ciphertext has been tampered with or the authentication tag does not
        match, an exception will be raised during finalization.
        
        Args:
            ciphertext (bytes): The encrypted message to decrypt.
            key (bytes): AES-256 decryption key (must match encryption key).
            nonce (bytes): The nonce that was used during encryption.
            tag (bytes): The authentication tag generated during encryption.
        
        Returns:
            str: The decrypted plaintext message.
        
        Raises:
            ValueError: If the provided key is not exactly 32 bytes in length.
            cryptography.exceptions.InvalidTag: If authentication fails.
        
        Example:
            >>> plaintext = AESCipher.decrypt(ciphertext, key, nonce, tag)
        """
        if len(key) != 32:
            raise ValueError(f"AES-256 key must be 32 bytes, got {len(key)}")
        
        # Initialize AES cipher in GCM mode with the same nonce and tag
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag),
            backend=default_backend()
        )
        
        # Create decryptor and perform the decryption
        # The tag is automatically verified during finalize()
        decryptor = cipher.decryptor()
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        # Return the plaintext as a UTF-8 decoded string
        return plaintext.decode('utf-8')
    
    @staticmethod
    def encrypt_to_json(plaintext: str, key: bytes) -> dict:
        """
        Encrypt plaintext and return a JSON-serializable dictionary.
        
        This convenience method encrypts the plaintext and converts all binary
        outputs to Base64-encoded strings, making the result suitable for JSON
        serialization, database storage, or network transmission.
        
        Args:
            plaintext (str): The message to encrypt.
            key (bytes): AES-256 encryption key (32 bytes).
        
        Returns:
            dict: A dictionary containing Base64-encoded:
                - 'ciphertext': The encrypted message
                - 'nonce': The random nonce used for encryption
                - 'tag': The authentication tag
        
        Example:
            >>> encrypted = AESCipher.encrypt_to_json("Secret message", key)
            >>> # Store encrypted in database or send over network
        """
        ciphertext, nonce, tag = AESCipher.encrypt(plaintext, key)
        return {
            'ciphertext': base64.b64encode(ciphertext).decode('ascii'),
            'nonce': base64.b64encode(nonce).decode('ascii'),
            'tag': base64.b64encode(tag).decode('ascii')
        }
    
    @staticmethod
    def decrypt_from_json(encrypted_json: dict, key: bytes) -> str:
        """
        Decrypt plaintext from a JSON-serializable dictionary.
        
        This convenience method reverses the encrypt_to_json operation by
        decoding the Base64 strings before performing decryption.
        
        Args:
            encrypted_json (dict): Dictionary containing Base64-encoded:
                - 'ciphertext': The encrypted message
                - 'nonce': The nonce used during encryption
                - 'tag': The authentication tag
            key (bytes): AES-256 decryption key (32 bytes).
        
        Returns:
            str: The decrypted plaintext message.
        
        Example:
            >>> encrypted = AESCipher.encrypt_to_json("Secret message", key)
            >>> plaintext = AESCipher.decrypt_from_json(encrypted, key)
        """
        ciphertext = base64.b64decode(encrypted_json['ciphertext'])
        nonce = base64.b64decode(encrypted_json['nonce'])
        tag = base64.b64decode(encrypted_json['tag'])
        return AESCipher.decrypt(ciphertext, key, nonce, tag)


if __name__ == "__main__":
    """
    Standalone test routine for the AES-256-GCM cipher.
    
    This test verifies that encryption and decryption work correctly by:
        1. Generating a random 32-byte AES-256 key
        2. Encrypting a test message containing Unicode characters
        3. Serializing to JSON and back
        4. Decrypting and comparing with the original message
    
    A successful test indicates that all encoding, encryption, and
    serialization operations are functioning correctly.
    """
    print("=" * 50)
    print("AES-256-GCM Cipher Test")
    print("=" * 50)
    
    # Generate a cryptographically secure random 256-bit key
    key = os.urandom(32)
    original = "This is a secret message! 🚀"
    print(f"Original: {original}")
    
    # Encrypt the message and convert to JSON-serializable format
    encrypted = AESCipher.encrypt_to_json(original, key)
    
    # Decrypt the message back to plaintext
    decrypted = AESCipher.decrypt_from_json(encrypted, key)
    
    # Verify that the round-trip was successful
    if original == decrypted:
        print("\nEncryption/Decryption successful!")
    else:
        print("\nFailed!")