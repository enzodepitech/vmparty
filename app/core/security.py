import secrets
from passlib.hash import sha512_crypt

def create_user_password():
    """
    Create user password
    """
    return secrets.token_urlsafe(12)

def hash_password(password: str) -> str:
    """Génère un hash Argon2 sécurisé du mot de passe."""
    return sha512_crypt.using(rounds=5000).hash(password)
