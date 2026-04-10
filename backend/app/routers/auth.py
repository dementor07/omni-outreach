from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from app.auth import hash_password, verify_password, create_access_token
from app.db import execute, fetch_one

router = APIRouter()


class RegisterRequest(BaseModel):
    email: str
    password: str


class LoginRequest(BaseModel):
    email: str
    password: str


@router.post("/register", status_code=201)
async def register(body: RegisterRequest):
    existing = await fetch_one("SELECT id FROM users WHERE email=$1", body.email)
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")
    user = await fetch_one(
        "INSERT INTO users (email, password_hash) VALUES ($1, $2) RETURNING id, email",
        body.email, hash_password(body.password),
    )
    return user


@router.post("/login")
async def login(body: LoginRequest):
    user = await fetch_one("SELECT * FROM users WHERE email=$1", body.email)
    if not user or not verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {
        "access_token": create_access_token(str(user["id"])),
        "token_type": "bearer",
    }
