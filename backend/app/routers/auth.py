from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, EmailStr
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.auth import create_access_token, hash_password, verify_password
from app.db import fetch_one

router = APIRouter()
limiter = Limiter(key_func=get_remote_address)


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


@router.post("/register", status_code=201)
@limiter.limit("5/hour")
async def register(request: Request, body: RegisterRequest):
    existing = await fetch_one("SELECT id FROM users WHERE email=$1", body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await fetch_one(
        "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email",
        body.email, hash_password(body.password),
    )
    return user


@router.post("/login")
@limiter.limit("10/minute")
async def login(request: Request, body: LoginRequest):
    user = await fetch_one("SELECT * FROM users WHERE email=$1", body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": create_access_token(str(user["id"])),
        "token_type": "bearer",
    }
