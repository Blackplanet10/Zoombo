# ===========================================================
#  encryption.py — Simplified with PyCryptodome
# ===========================================================

"""
encryption.py – Simplified for use with the PyCryptodome library.
Provides easy-to-use RSA key generation, encryption, and decryption.

Functions:
────────────────────
• generate_rsa_keypair(bits=512)     →  public, private key tuples
• rsa_encrypt(message_bytes, pub)    →  bytes cipher
• rsa_decrypt(cipher_bytes, priv)    →  original bytes
• xor_bytes(data, key)               →  very simple stream cipher

NOTE: For real-world security, use larger keys and authenticated encryption.
"""

from Crypto.PublicKey import RSA
from Crypto.Cipher import PKCS1_OAEP
from typing import Tuple

def generate_rsa_keypair(bits: int = 1024) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """
    Generate an RSA public/private key pair.
    Args:
        bits: Number of bits for the modulus (e.g., 2048 for real security, 512 for demo).
    Returns:
        (public_key_tuple, private_key_tuple)
        public: (n, e), private: (n, d)
    """
    key = RSA.generate(bits)
    pub = (key.n, key.e)
    priv = (key.n, key.e, key.d)  # Include e!
    return pub, priv

def rsa_encrypt(message: bytes, pub: Tuple[int, int]) -> bytes:
    """
    Encrypt a message with an RSA public key.
    Args:
        message: Plaintext as bytes.
        pub: Public key as (n, e).
    Returns:
        Ciphertext as bytes.
    """
    key = RSA.construct((pub[0], pub[1]))
    cipher = PKCS1_OAEP.new(key)
    return cipher.encrypt(message)

def rsa_decrypt(cipher_bytes: bytes, priv: Tuple[int, int]) -> bytes:
    """
    Decrypt a message with an RSA private key.
    Args:
        cipher_bytes: Ciphertext as bytes.
        priv: Private key as (n, d).
    Returns:
        Decrypted message as bytes.
    """
    n, e, d = priv  # Unpack all three
    key = RSA.construct((n, e, d))
    cipher = PKCS1_OAEP.new(key)
    return cipher.decrypt(cipher_bytes)

def xor_bytes(data: bytes, key: bytes) -> bytes:
    """
    XOR a byte string with a (repeating) key. For demo use only.
    Args:
        data: Data to encrypt or decrypt.
        key: Bytes key, cycled as needed.
    Returns:
        XOR'd bytes.
    """
    klen = len(key)
    return bytes(b ^ key[i % klen] for i, b in enumerate(data))
