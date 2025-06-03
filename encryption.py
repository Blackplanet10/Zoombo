# ===========================================================
#  encryption.py
# ===========================================================

"""
encryption.py – A *pure‑Python* mini crypto library used by the video‑chat
project.  It deliberately avoids external packages so that the maths is
transparent and easy to follow.

Provided primitives
────────────────────
• generate_rsa_keypair(bits=512)     →  public, private key tuples
• rsa_encrypt(message_bytes, pub)    →  int cipher
• rsa_decrypt(cipher_int, priv)      →  original bytes
• xor_bytes(data, key)               →  *very* simple stream cipher

WARNING  ✱  RSA‑512 and XOR‑only are **not** secure in the real world.  They
             are perfect for classroom demonstrations, but *never* use them
             commercially!
"""

from __future__ import annotations
import secrets, random, math
from typing import Tuple

# ---------- helper maths ----------

def _egcd(a: int, b: int):
    """Extended GCD – returns (g, x, y) so that ax + by = g = gcd(a, b)."""
    if b == 0:
        return a, 1, 0
    g, x1, y1 = _egcd(b, a % b)
    return g, y1, x1 - (a // b) * y1

def _modinv(e: int, phi: int) -> int:
    """Modular inverse of *e* mod *phi* (i.e. e·d ≡ 1 (mod φ))."""
    g, x, _ = _egcd(e, phi)
    if g != 1:
        raise ValueError("e and phi are not coprime – inverse doesn’t exist")
    return x % phi

# ----- Miller–Rabin primality test -----
_MR_BASES = [2, 3, 5, 7, 11, 13, 17, 19, 23, 29, 31, 37]

def _is_probable_prime(n: int) -> bool:
    if n in (2, 3):
        return True
    if n < 2 or n % 2 == 0:
        return False

    # write n‑1 = 2^s · d  with d odd
    d, s = n - 1, 0
    while d % 2 == 0:
        d //= 2;  s += 1

    def _try(a: int):
        x = pow(a, d, n)
        if x in (1, n - 1):
            return True
        for _ in range(s - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                return True
        return False

    for a in _MR_BASES:
        if a % n == 0:
            continue
        if not _try(a):
            return False
    return True


def _random_prime(bits: int) -> int:
    """Generate a random *probable* prime of exactly *bits* bits."""
    assert bits >= 8, "Very small RSA keys are pointless 🥲"
    while True:
        # ensure the number has the top bit set and is odd
        candidate = secrets.randbits(bits) | 1 | (1 << bits - 1)
        if _is_probable_prime(candidate):
            return candidate

# ---------- RSA key generation ----------

KeyPair = Tuple[Tuple[int, int], Tuple[int, int]]  # (pub, priv)


def generate_rsa_keypair(bits: int = 512) -> KeyPair:
    """Return (public, private) key‑pair for a modulus of *bits* bits."""
    p = _random_prime(bits // 2)
    q = _random_prime(bits // 2)
    while p == q:  # astronomical odds, but still…
        q = _random_prime(bits // 2)

    n = p * q
    phi = (p - 1) * (q - 1)
    e = 65537  # standard choice
    d = _modinv(e, phi)
    return (n, e), (n, d)


# ---------- RSA encrypt / decrypt ----------

def rsa_encrypt(message: bytes, pub: Tuple[int, int]) -> int:
    """Encrypt *message* (≤ modulus size) with *pub*, returning an int cipher."""
    n, e = pub
    m_int = int.from_bytes(message, "big")
    if m_int >= n:
        raise ValueError("Plaintext too large – choose bigger key or use hybrid crypto")
    return pow(m_int, e, n)


def rsa_decrypt(cipher_int: int, priv: Tuple[int, int]) -> bytes:
    """Decrypt an *int* cipher back to raw bytes using *priv*."""
    n, d = priv
    m_int = pow(cipher_int, d, n)
    byte_len = (n.bit_length() + 7) // 8
    return m_int.to_bytes(byte_len, "big").lstrip(b"\x00")


# ---------- toy symmetric cipher ----------

def xor_bytes(data: bytes, key: bytes) -> bytes:
    """Return *data* XORed with cycling *key* (simple but fast)."""
    klen = len(key)
    return bytes(b ^ key[i % klen] for i, b in enumerate(data))