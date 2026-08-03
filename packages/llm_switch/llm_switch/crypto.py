"""Fernet-based symmetric encryption for secrets in the endpoint registry.

Ported from Odysseus' src/secret_storage.py, made self-contained (no Odysseus
imports) and pointed at ~/.llm_switch/.key instead of data/.app_key.

Encrypted values carry an "enc:" prefix so encrypt()/decrypt() are idempotent:
re-encrypting an already-encrypted value is a no-op, and decrypting a
plaintext value returns it unchanged.
"""
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

_KEY_PATH = Path(os.path.expanduser("~/.llm_switch/.key"))
_PREFIX = "enc:"
_fernet: Fernet | None = None


def _safe_chmod(path: Path, mode: int) -> None:
    """chmod on POSIX; no-op on Windows (and swallow any other failure)."""
    try:
        os.chmod(path, mode)
    except (OSError, NotImplementedError):
        pass


def _load_or_create_key() -> bytes:
    if _KEY_PATH.exists():
        return _KEY_PATH.read_bytes()
    _KEY_PATH.parent.mkdir(parents=True, exist_ok=True)
    key = Fernet.generate_key()
    _KEY_PATH.write_bytes(key)
    _safe_chmod(_KEY_PATH, 0o600)
    return key


def _get_fernet() -> Fernet:
    global _fernet
    if _fernet is None:
        _fernet = Fernet(_load_or_create_key())
    return _fernet


def encrypt(plaintext: str) -> str:
    """Encrypt a string. Empty input passes through. Already-encrypted
    values pass through unchanged so re-encrypting is a no-op."""
    if not plaintext:
        return plaintext or ""
    if plaintext.startswith(_PREFIX):
        return plaintext
    token = _get_fernet().encrypt(plaintext.encode("utf-8")).decode("ascii")
    return _PREFIX + token


def decrypt(value: str) -> str:
    """Decrypt an "enc:"-prefixed value. Plaintext (unprefixed) passes through
    unchanged. Returns "" on decryption failure (corrupt or rotated-key
    token) rather than raising."""
    if not value:
        return value or ""
    if not value.startswith(_PREFIX):
        return value
    try:
        return _get_fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except InvalidToken:
        return ""
    except Exception:
        return ""


def is_encrypted(value: str) -> bool:
    return bool(value) and value.startswith(_PREFIX)
