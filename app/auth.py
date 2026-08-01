import os
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired

from fastapi import WebSocket, WebSocketException, Request, HTTPException, status

SECRET_KEY = os.getenv("SECRET_KEY", "")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD_HASH = os.getenv("ADMIN_PASSWORD_HASH")

ph = PasswordHasher()
serializer = URLSafeTimedSerializer(SECRET_KEY, salt="admin-session")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password)
    except VerifyMismatchError:
        return False

def create_session_token(username: str) -> str:
    return serializer.dumps({"user": username})

def verify_session_token(token: str, max_age: int = 86400) -> str | None:
    """Verifies token and ensures it hasn't expired (default 24h)."""
    try:
        data = serializer.loads(token, max_age=max_age)
        return data.get("user")
    except (BadSignature, SignatureExpired):
        return None

async def require_admin_ws(websocket: WebSocket) -> str:
    """Authenticates a WebSocket connection using the admin_session cookie."""
    session_token = websocket.cookies.get("admin_session")

    if not session_token:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Unauthorized")

    username = verify_session_token(session_token)
    if not username or username != ADMIN_USERNAME:
        raise WebSocketException(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid session")

    return username
    
async def require_admin(request: Request):
    session_token = request.cookies.get("admin_session")
    
    if not session_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized access",
            headers={"Location": "/login"}
        )
        
    username = verify_session_token(session_token)
    if not username or username != ADMIN_USERNAME:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session invalid or expired"
        )
    return username
