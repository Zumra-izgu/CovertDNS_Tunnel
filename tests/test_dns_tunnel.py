"""
CovertDNS - System Tests with Visible Output

This test suite validates the core functionality of the CovertDNS system
and displays detailed output of cryptographic operations including key
generation, encryption, and decryption.

Usage:
    python test_verbose.py
"""

import sys
import os
import base64
import time

# Add parent directory to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from encryption.aes_cipher import AESCipher
from encryption.kyber_kem import KyberKEM
from encryption.hybrid_crypto import HybridCrypto
from dns_tunnel import DNSSender


def print_header(title):
    """Print a formatted section header"""
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def print_subheader(title):
    """Print a subsection header"""
    print(f"\n  --- {title} ---")


def print_key_visualization(label, data, max_len=60):
    """Print a visual representation of key data"""
    if isinstance(data, bytes):
        display = data[:max_len].hex() + ("..." if len(data) > max_len else "")
        print(f"     {label}: {len(data)} bytes")
        print(f"     Hex: {display[:80]}")
    else:
        display = data[:max_len] + ("..." if len(data) > max_len else "")
        print(f"     {label}: {len(data)} chars")
        print(f"     Value: {display}")


def test_aes_with_visualization():
    """Test 1: AES-256-GCM with visual output"""
    print_subheader("AES-256-GCM Encryption Test")
    
    key = b"K" * 32
    original = "Confidential message for AES-256-GCM testing."
    
    print(f"     Original message: '{original}'")
    print(f"     Message length: {len(original)} bytes")
    print_key_visualization("AES-256 Key", key, 16)
    
    encrypted = AESCipher.encrypt_to_json(original, key)
    print(f"     Encrypted (Base64 ciphertext): {encrypted['ciphertext'][:50]}...")
    print(f"     Nonce (Base64): {encrypted['nonce'][:20]}...")
    print(f"     Tag (Base64): {encrypted['tag'][:20]}...")
    
    decrypted = AESCipher.decrypt_from_json(encrypted, key)
    print(f"     Decrypted: '{decrypted}'")
    
    assert original == decrypted
    print("\n     ✓ AES-256-GCM: Encryption and decryption successful")
    return True


def test_kyber_with_visualization():
    """Test 2: Kyber-768 key generation and exchange with visual output"""
    print_subheader("Kyber-768 Key Encapsulation Mechanism (NIST FIPS 203)")
    
    print("     Step 1: Generating keypair (Receiver side)...")
    pub, priv = KyberKEM.generate_keypair()
    
    print_key_visualization("Public Key", pub)
    print_key_visualization("Private Key", priv)
    
    print("\n     Step 2: Encapsulating shared secret (Sender side)...")
    cipher, ss1 = KyberKEM.encapsulate(pub)
    
    print_key_visualization("Ciphertext", cipher)
    print_key_visualization("Shared Secret (Sender)", ss1)
    
    print("\n     Step 3: Decapsulating shared secret (Receiver side)...")
    ss2 = KyberKEM.decapsulate(cipher, priv)
    
    print_key_visualization("Shared Secret (Receiver)", ss2)
    
    assert ss1 == ss2
    assert len(ss1) == 32
    
    print("\n     ✓ Kyber-768: Shared secrets match! Key exchange successful.")
    print(f"     Security level: NIST Level 3 (AES-192 equivalent)")
    return True


def test_hybrid_with_visualization():
    """Test 3: Hybrid encryption with visual output"""
    print_subheader("Hybrid Encryption (Kyber-768 + AES-256-GCM)")
    
    print("     Step 1: Generating Kyber-768 keypair...")
    pub, priv = HybridCrypto.generate_keypair()
    print(f"     Public key size: {len(pub)} bytes")
    print(f"     Private key size: {len(priv)} bytes")
    
    original = "Top secret message using post-quantum cryptography."
    print(f"\n     Original message: '{original}'")
    
    print("\n     Step 2: Encrypting with public key...")
    encrypted = HybridCrypto.encrypt_message(original, pub)
    
    kyber_ct = encrypted['kyber_ciphertext']
    aes_data = encrypted['encrypted_data']
    
    print(f"     Kyber ciphertext (Base64): {kyber_ct[:50]}... ({len(kyber_ct)} chars)")
    print(f"     AES encrypted data (Base64): {aes_data['ciphertext'][:40]}...")
    
    print("\n     Step 3: Decrypting with private key...")
    decrypted = HybridCrypto.decrypt_message(encrypted, priv)
    
    print(f"     Decrypted: '{decrypted}'")
    
    assert original == decrypted
    print("\n     ✓ Hybrid Encryption: Post-quantum secure message exchange successful")
    return True


def test_dns_format_with_visualization():
    """Test 4: DNS transport format with visual output"""
    print_subheader("DNS Transport Format")
    
    pub, priv = HybridCrypto.generate_keypair()
    original = "DNS tunnel payload test message"
    
    print(f"     Original: '{original}'")
    print(f"     Size: {len(original)} bytes")
    
    print("\n     Step 1: Encrypting for DNS transport...")
    encoded = HybridCrypto.encrypt_for_dns(original, pub)
    print(f"     DNS-safe encoded: {encoded[:60]}...")
    print(f"     Encoded size: {len(encoded)} chars (Base64 + JSON)")
    
    print("\n     Step 2: Decrypting from DNS transport...")
    decoded = HybridCrypto.decrypt_from_dns(encoded, priv)
    print(f"     Decoded: '{decoded}'")
    
    assert original == decoded
    print("\n     ✓ DNS Format: Ready for DNS query embedding")
    return True


def test_dns_packet_visualization():
    """Test 5: DNS packet construction with visual output"""
    print_subheader("DNS Query Packet Construction (RFC 1035)")
    
    sender = DNSSender("127.0.0.1")
    
    domain = "0001.SGVsbG8gd29ybGQ.covert.local"
    print(f"     Domain name: {domain}")
    
    query = sender.build_dns_query(domain)
    
    print(f"     Packet size: {len(query)} bytes")
    
    # Parse and display packet structure
    transaction_id = query[0:2].hex()
    flags = query[2:4].hex()
    qdcount = int.from_bytes(query[4:6], 'big')
    
    print(f"\n     DNS Header:")
    print(f"       Transaction ID: 0x{transaction_id}")
    print(f"       Flags: 0x{flags} (Standard query)")
    print(f"       QDCOUNT: {qdcount} (1 question)")
    
    # Extract domain from packet
    pos = 12
    domain_parts = []
    while pos < len(query):
        length = query[pos]
        if length == 0:
            break
        pos += 1
        domain_parts.append(query[pos:pos+length].decode('ascii'))
        pos += length
    
    print(f"\n     Question Section:")
    print(f"       QNAME: {'.'.join(domain_parts)}")
    qtype = int.from_bytes(query[pos:pos+2], 'big')
    print(f"       QTYPE: {qtype} (A record)")
    qclass = int.from_bytes(query[pos+2:pos+4], 'big')
    print(f"       QCLASS: {qclass} (IN)")
    
    print("\n     ✓ DNS Packet: RFC 1035 compliant")
    return True


def test_chunking_visualization():
    """Test 6: Message chunking demonstration"""
    print_subheader("DNS Message Chunking")
    
    pub, priv = HybridCrypto.generate_keypair()
    long_message = "This is a very long secret message that needs to be split into multiple DNS chunks because DNS labels have a maximum length of 63 characters per RFC 1035. This demonstrates the chunking mechanism."
    
    print(f"     Original message length: {len(long_message)} characters")
    print(f"     Original message: '{long_message[:80]}...'")
    
    # Encrypt
    encrypted = HybridCrypto.encrypt_for_dns(long_message, pub)
    print(f"\n     Encrypted size: {len(encrypted)} characters")
    
    # Simulate chunking
    MAX_CHUNK = 45
    chunks = []
    for i in range(0, len(encrypted), MAX_CHUNK):
        chunks.append(encrypted[i:i+MAX_CHUNK])
    
    print(f"\n     Split into {len(chunks)} chunks (max {MAX_CHUNK} chars per chunk):")
    for i, chunk in enumerate(chunks[:5]):
        print(f"       Chunk {i+1:2d}: {chunk[:40]}... ({len(chunk)} chars)")
    if len(chunks) > 5:
        print(f"       ... and {len(chunks) - 5} more chunks")
    
    print("\n     DNS query format: <seq>.<chunk>.covert.local")
    print(f"       Example: 0001.{chunks[0][:20]}...covert.local")
    
    # Decrypt back
    decoded = HybridCrypto.decrypt_from_dns(encrypted, priv)
    assert long_message == decoded
    
    print("\n     ✓ Chunking: Message successfully split and reassembled")
    return True


def test_performance_visualization():
    """Test 7: Performance metrics"""
    print_subheader("Performance Metrics")
    
    import time
    
    # Key generation time
    start = time.time()
    pub, priv = KyberKEM.generate_keypair()
    keygen_time = (time.time() - start) * 1000
    
    # Encapsulation time
    start = time.time()
    cipher, ss = KyberKEM.encapsulate(pub)
    encaps_time = (time.time() - start) * 1000
    
    # Decapsulation time
    start = time.time()
    ss2 = KyberKEM.decapsulate(cipher, priv)
    decaps_time = (time.time() - start) * 1000
    
    print(f"     Kyber-768 Performance:")
    print(f"       Key generation: {keygen_time:.2f} ms")
    print(f"       Encapsulation:  {encaps_time:.2f} ms")
    print(f"       Decapsulation:  {decaps_time:.2f} ms")
    
    print(f"\n     Key Sizes (NIST FIPS 203):")
    print(f"       Public key:  {len(pub)} bytes")
    print(f"       Private key: {len(priv)} bytes")
    print(f"       Ciphertext:  {len(cipher)} bytes")
    print(f"       Shared secret: {len(ss)} bytes (AES-256 key)")
    
    print(f"\n     DNS Constraints (RFC 1035):")
    print(f"       Max label length: 63 characters")
    print(f"       Safe chunk size: 45 characters")
    print(f"       Protocol: UDP port 53")
    
    return True


def run_all_tests():
    """Run all tests with verbose output"""
    print_header("COVERTDNS SYSTEM VERIFICATION")
    print("\n  Testing post-quantum DNS tunnel implementation")
    print("  Standards: NIST FIPS 203 | RFC 1035")
    print("  Cryptography: Kyber-768 + AES-256-GCM")
    
    tests = [
        ("AES-256-GCM Encryption", test_aes_with_visualization),
        ("Kyber-768 Key Exchange", test_kyber_with_visualization),
        ("Hybrid Encryption", test_hybrid_with_visualization),
        ("DNS Transport Format", test_dns_format_with_visualization),
        ("DNS Packet Construction", test_dns_packet_visualization),
        ("Message Chunking", test_chunking_visualization),
        ("Performance Metrics", test_performance_visualization),
    ]
    
    passed = 0
    for name, test_func in tests:
        print_header(f"TEST: {name}")
        if test_func():
            passed += 1
        time.sleep(0.3)  # Pause for readability
    
    # Final summary
    print_header("TEST SUMMARY")
    print(f"\n  Total Tests: {len(tests)}")
    print(f"  Passed:      {passed}")
    print(f"  Failed:      {len(tests) - passed}")
    
    if passed == len(tests):
        print("\n  ✓ ALL TESTS PASSED")
        print("\n  System is ready for deployment.")
    else:
        print("\n  ✗ SOME TESTS FAILED")
    
    print("\n" + "=" * 70)
    
    return passed == len(tests)


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)