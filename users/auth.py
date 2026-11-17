from jose import jwt, JWTError
from datetime import datetime, timedelta, timezone
from fastapi.security import OAuth2PasswordBearer
from fastapi import Depends, status
from fastapi.exceptions import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from config.config import (
    get_db,
    SECRET_KEY,
    ALGORITHM,
    ACCESS_TOKEN_EXPIRE_MINUTES,
    REFRESH_TOKEN_EXPIRE_DAYS,
    API_PUBLIC_PREFIX,
)
from users.crud import get_user_by_id
from users.models import User, UserRole

import asyncio

import bcrypt

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{API_PUBLIC_PREFIX}/auth/login")

def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

def verify_password(plain_password: str, hashed_password: str) -> bool:
    try:
        return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


# bcrypt ataylab sekin (~250 ms CPU). Async handler ichida to'g'ridan-to'g'ri chaqirilsa
# event loop shu vaqtga to'xtaydi va serverdagi BARCHA so'rovlar kutib qoladi. Shuning
# uchun API ichida doim shu ikki async versiyadan foydalaning — ular hisoblashni alohida
# thread'ga chiqaradi. Sinxron versiyalar faqat skriptlar uchun qoldirilgan.
async def hash_password_async(password: str) -> str:
    return await asyncio.to_thread(hash_password, password)


async def verify_password_async(plain_password: str, hashed_password: str) -> bool:
    return await asyncio.to_thread(verify_password, plain_password, hashed_password)


# Parolni tiklash tokeni qancha vaqt amal qiladi (daqiqa)
PASSWORD_RESET_TOKEN_EXPIRE_MINUTES = 10


def token_payload_for(user: User) -> dict:
    """Token ichiga tushadigan claim'lar.

    `role` claim tashqi mikroserviz (`support_service/`) uchun qo'shildi: u asosiy
    bazaga ulanmaydi, shuning uchun foydalanuvchining rolini tokendan boshqa joydan
    bila olmaydi. Asosiy ilova esa rolni HAMON bazadan o'qiydi (`get_current_user`) —
    admin rolni o'zgartirsa yoki foydalanuvchi banlansa, hali muddati tugamagan token
    bilan eski huquqlar ishlab qolmasligi uchun. Ya'ni claim — qulaylik, manba
    haqiqat emas.
    """
    return {"sub": str(user.id), "role": user.role.value if user.role else None}


def create_access_token(data: dict):
    to_encode=data.copy()
    expire = datetime.now(timezone.utc) + timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES)

    to_encode.update({
        "exp": expire,
        "type": "access"
    })

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_refresh_token(data: dict):
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=REFRESH_TOKEN_EXPIRE_DAYS)

    to_encode.update({
        "exp": expire,
        "type": "refresh"
    })

    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def create_password_reset_token(data: dict):
    """Faqat parol tiklash uchun — qisqa muddatli, type='reset'.

    type='access' emas, shuning uchun bu token bilan boshqa himoyalangan
    endpointlarga (get_current_user) kirib bo'lmaydi.
    """
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=PASSWORD_RESET_TOKEN_EXPIRE_MINUTES
    )
    to_encode.update({
        "exp": expire,
        "type": "reset",
    })
    return jwt.encode(to_encode, SECRET_KEY, algorithm=ALGORITHM)


def verify_token(token: str):
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        return None


async def get_current_user(
    token: str = Depends(oauth2_scheme),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(token)


    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Yaroqsiz yoki muddati o'tgan token"
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token xato")

    user = await get_user_by_id(db, int(user_id))
    if user is None:
        raise HTTPException(status_code=401, detail="Foydalanuvchi topilmadi")
    return user


async def get_current_active_user(
    current_user: User = Depends(get_current_user),
) -> User:
    if current_user.is_banned:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akkaunt bloklangan.",
        )
    if not current_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Akkaunt faol emas.",
        )
    return current_user


async def get_current_sender(
    current_user: User = Depends(get_current_active_user),
) -> User:
    """Faqat yuk beruvchi (mijoz) — buyurtma yaratish/tahrirlash/o'chirish."""
    if current_user.role != UserRole.SENDER:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Bu amal faqat yuk beruvchi (sender) uchun.",
        )
    return current_user

