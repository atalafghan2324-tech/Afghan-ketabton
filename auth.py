import os
from datetime import datetime, timedelta, timezone
import jwt
from jwt import InvalidTokenError
from pwdlib import PasswordHash
from fastapi import Depends, HTTPException
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from database import get_db
from models import User

SECRET_KEY = os.getenv('SECRET_KEY')
if not SECRET_KEY or len(SECRET_KEY) < 32:
    raise RuntimeError('Set SECRET_KEY environment variable to a random string of at least 32 characters')
ALGORITHM = 'HS256'
hasher = PasswordHash.recommended()
security = HTTPBearer()

def hash_password(password: str) -> str:
    return hasher.hash(password)

def verify_password(password: str, stored: str) -> bool:
    return hasher.verify(password, stored)

def create_token(user_id: int) -> str:
    payload = {'sub': str(user_id), 'exp': datetime.now(timezone.utc) + timedelta(hours=24)}
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def current_user(credentials: HTTPAuthorizationCredentials = Depends(security), db: Session = Depends(get_db)) -> User:
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        user_id = int(payload['sub'])
    except (InvalidTokenError, KeyError, ValueError, TypeError):
        raise HTTPException(401, 'Invalid or expired token', headers={'WWW-Authenticate': 'Bearer'})
    user = db.get(User, user_id)
    if not user:
        raise HTTPException(401, 'User no longer exists')
    return user
