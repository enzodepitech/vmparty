import secrets
from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["argon2"], deprecated="auto")

def create_user_password():
    """
    Create user password
    """
    return secrets.token_urlsafe(12)

def hash_password(password: str) -> str:
    """Génère un hash Argon2 sécurisé du mot de passe."""
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Vérifie si le mot de passe en clair correspond au hash en base."""
    return pwd_context.verify(plain_password, hashed_password)
