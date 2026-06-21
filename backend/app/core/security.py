import datetime
from typing import Optional, Any
import jwt
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

from config import settings


# Password hashing utility using Argon2
ph = PasswordHasher()


def get_password_hash(password: str) -> str:
    """Hash a clear-text password using the Argon2 hashing algorithm."""
    return ph.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a clear-text password against a hashed Argon2 password signature."""
    try:
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False
    except Exception:
        return False


def create_access_token(subject: Any, tier: str, litellm_api_key: Optional[str] = None, expires_delta: Optional[datetime.timedelta] = None) -> str:
    """
    Generate a JWT access token for the subject user.
    Includes subscription tier and optional LiteLLM API key in payload claims.
    """
    if expires_delta:
        expire = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        expire = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    
    to_encode = {
        "exp": expire,
        "sub": str(subject),
        "tier": tier,
        "litellm_api_key": litellm_api_key
    }
    
    encoded_jwt = jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return encoded_jwt


def decode_access_token(token: str) -> Optional[dict]:
    """Decode a JWT access token and return its payload claims, validating signatures and expiration dates."""
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except jwt.PyJWTError:
        return None
