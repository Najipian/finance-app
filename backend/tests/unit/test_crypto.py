"""AES-256-GCM token cipher (NFR-01)."""

import base64
import os

import pytest

from finance_app.core.crypto import DecryptionError, TokenCipher, decode_key

AAD = b"connection-1"


def _key() -> bytes:
    return os.urandom(32)


def test_round_trip_and_versioned_format_nfr01() -> None:
    cipher = TokenCipher({1: _key()}, current_version=1)

    stored = cipher.encrypt("consent-token-123", associated_data=AAD)

    assert stored.startswith("v1:")
    assert "consent-token-123" not in stored
    assert cipher.decrypt(stored, associated_data=AAD) == "consent-token-123"


def test_same_plaintext_encrypts_differently_each_time() -> None:
    cipher = TokenCipher({1: _key()}, current_version=1)

    assert cipher.encrypt("x", associated_data=AAD) != cipher.encrypt("x", associated_data=AAD)


def test_ciphertext_moved_to_another_row_does_not_decrypt() -> None:
    cipher = TokenCipher({1: _key()}, current_version=1)
    stored = cipher.encrypt("secret", associated_data=b"connection-1")

    with pytest.raises(DecryptionError):
        cipher.decrypt(stored, associated_data=b"connection-2")


def test_tampered_ciphertext_is_rejected() -> None:
    cipher = TokenCipher({1: _key()}, current_version=1)
    version, payload = cipher.encrypt("secret", associated_data=AAD).split(":")
    raw = bytearray(base64.urlsafe_b64decode(payload))
    raw[-1] ^= 0x01

    with pytest.raises(DecryptionError):
        cipher.decrypt(
            f"{version}:{base64.urlsafe_b64encode(bytes(raw)).decode()}", associated_data=AAD
        )


@pytest.mark.parametrize("stored", ["garbage", "v9:AAAA", "vx:AAAA", "v1:%%%"])
def test_malformed_or_unknown_version_is_rejected(stored: str) -> None:
    cipher = TokenCipher({1: _key()}, current_version=1)

    with pytest.raises(DecryptionError):
        cipher.decrypt(stored, associated_data=AAD)


def test_key_rotation_keeps_old_values_readable() -> None:
    old_key, new_key = _key(), _key()
    before = TokenCipher({1: old_key}, current_version=1).encrypt("secret", associated_data=AAD)

    rotated = TokenCipher({1: old_key, 2: new_key}, current_version=2)

    assert rotated.decrypt(before, associated_data=AAD) == "secret"
    assert rotated.needs_reencryption(before)
    assert not rotated.needs_reencryption(rotated.encrypt("secret", associated_data=AAD))


def test_decode_key_requires_256_bits() -> None:
    assert len(decode_key(base64.b64encode(os.urandom(32)).decode())) == 32
    with pytest.raises(ValueError, match="32 bytes"):
        decode_key(base64.b64encode(os.urandom(16)).decode())
    with pytest.raises(ValueError, match="base64"):
        decode_key("not base64!!")


def test_cipher_rejects_missing_current_key() -> None:
    with pytest.raises(ValueError, match="current version"):
        TokenCipher({1: _key()}, current_version=2)
