"""Application-layer encryption for bank secrets (AES-256-GCM).

Stored format: ``v<key_version>:<base64url(nonce || ciphertext_with_tag)>``.

- A fresh random 12-byte nonce per value, as GCM requires.
- The key version travels with the ciphertext, so keys can be rotated: new values
  use the current key, older values still decrypt with retired keys.
- Callers pass *associated data* (e.g. the connection ID). It is authenticated but
  not stored, so a ciphertext copied onto another row fails to decrypt.
"""

import base64
import binascii
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

KEY_BYTES = 32  # AES-256
NONCE_BYTES = 12
TAG_BYTES = 16


class DecryptionError(Exception):
    """A stored value is malformed, was tampered with, or uses an unknown key."""


def decode_key(encoded: str) -> bytes:
    """Decode a base64 key and check it is exactly 256 bits.

    Args:
        encoded: Standard or URL-safe base64 of 32 random bytes.

    Returns:
        The raw key bytes.

    Raises:
        ValueError: The value is not base64 or not 32 bytes long.
    """
    try:
        key = base64.urlsafe_b64decode(encoded.replace("+", "-").replace("/", "_"))
    except (binascii.Error, ValueError) as exc:
        raise ValueError("encryption key must be base64") from exc
    if len(key) != KEY_BYTES:
        raise ValueError(f"encryption key must decode to {KEY_BYTES} bytes, got {len(key)}")
    return key


class TokenCipher:
    """Encrypts and decrypts short secrets such as provider consent tokens.

    Args:
        keys: Raw 32-byte keys by version number.
        current_version: The version used for new encryptions; must be in ``keys``.
    """

    def __init__(self, keys: dict[int, bytes], current_version: int) -> None:
        if current_version not in keys:
            raise ValueError(f"no key for current version {current_version}")
        if any(len(key) != KEY_BYTES for key in keys.values()):
            raise ValueError(f"every key must be {KEY_BYTES} bytes")
        self._keys = {version: AESGCM(key) for version, key in keys.items()}
        self._current = current_version

    def encrypt(self, plaintext: str, *, associated_data: bytes) -> str:
        """Encrypt a string with the current key.

        Args:
            plaintext: The secret to protect.
            associated_data: Context the ciphertext is bound to (not stored).

        Returns:
            The versioned, base64url-encoded ciphertext.
        """
        nonce = os.urandom(NONCE_BYTES)
        sealed = self._keys[self._current].encrypt(nonce, plaintext.encode(), associated_data)
        payload = base64.urlsafe_b64encode(nonce + sealed).decode()
        return f"v{self._current}:{payload}"

    def decrypt(self, stored: str, *, associated_data: bytes) -> str:
        """Decrypt a value produced by ``encrypt``.

        Args:
            stored: The versioned ciphertext.
            associated_data: The same context used when encrypting.

        Returns:
            The original plaintext.

        Raises:
            DecryptionError: Wrong format, unknown key version, tampering, or
                mismatched associated data.
        """
        try:
            version_part, payload = stored.split(":", 1)
            version = int(version_part.removeprefix("v"))
            raw = base64.urlsafe_b64decode(payload)
        except (ValueError, binascii.Error) as exc:
            raise DecryptionError("malformed ciphertext") from exc
        aead = self._keys.get(version)
        if aead is None:
            raise DecryptionError(f"unknown key version {version}")
        # base64 decoding silently skips invalid characters, so check the length:
        # a valid value holds at least a nonce and a 16-byte authentication tag.
        if len(raw) < NONCE_BYTES + TAG_BYTES:
            raise DecryptionError("malformed ciphertext")
        nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
        try:
            return aead.decrypt(nonce, sealed, associated_data).decode()
        except InvalidTag as exc:
            raise DecryptionError("authentication failed") from exc

    def needs_reencryption(self, stored: str) -> bool:
        """Whether a value was encrypted with a retired key version."""
        return not stored.startswith(f"v{self._current}:")
