import base64
import hashlib
import logging
from cryptography.fernet import Fernet
from backend.app.config import settings

logger = logging.getLogger("app.security")

# Ensure an encryption key is present. If not, use standard fallback
ENCRYPTION_SECRET = getattr(settings, "ENCRYPTION_KEY", "honestmatch_aes_secret_key_32bytes_!!")

def derive_key(secret: str) -> bytes:
    """Derives a url-safe base64 key from a plain-text secret for symmetric encryption."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)

try:
    key_bytes = derive_key(ENCRYPTION_SECRET)
    cipher_suite = Fernet(key_bytes)
    logger.info("Field-level cryptography engine loaded successfully.")
except Exception as e:
    logger.error(f"Error loading cryptography: {e}")
    cipher_suite = None

def encrypt_text(text: str) -> str:
    """Encrypts cleartext to secure base64 string for PII protection at rest."""
    if not text:
        return ""
    if cipher_suite is None:
        return text
    try:
        cipher_text = cipher_suite.encrypt(text.encode("utf-8"))
        return cipher_text.decode("utf-8")
    except Exception as e:
        logger.error(f"Field encryption failed: {e}")
        return text

def decrypt_text(cipher_text: str) -> str:
    """Decrypts secure base64 string back into original cleartext."""
    if not cipher_text:
        return ""
    if cipher_suite is None:
        return cipher_text
    try:
        decrypted = cipher_suite.decrypt(cipher_text.encode("utf-8"))
        return decrypted.decode("utf-8")
    except Exception as e:
        logger.error(f"Field decryption failed: {e}. Returning raw value.")
        return cipher_text
