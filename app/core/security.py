from datetime import datetime, timedelta, timezone
from typing import Any
from pwdlib import PasswordHash
from app.core.config import get_settings

import jwt

password_hasher = PasswordHash.recommended()

def hash_password(password: str) -> str:
    """哈希明文密码。

    Args:
        password: 明文密码。

    Returns:
        返回类型为 str 的执行结果。
    """
    return password_hasher.hash(password)

def verify_password(password: str, password_hash: str) -> bool:
    """验证密码哈希。

    Args:
        password: 明文密码。
        password_hash: 密码哈希。

    Returns:
        返回类型为 bool 的执行结果。
    """
    return password_hasher.verify(password, password_hash)

def create_access_token(user_id: int, role:str) -> str:
    """签发访问令牌。

    Args:
        user_id: 用户编号。
        role: 用户角色。

    Returns:
        返回类型为 str 的执行结果。
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)

    payload = {
        "sub": str(user_id),
        "role": role,
        "iat": now,
        "exp": now + timedelta(
            minutes=settings.jwt_access_token_expire_minutes
        ),
    }

    return jwt.encode(
        payload,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )

def decode_access_token(token: str) -> dict[str,Any]:
    """解析访问令牌。

    Args:
        token: 访问令牌。

    Returns:
        返回类型为 dict[str, Any] 的执行结果。
    """
    settings = get_settings()

    return jwt.decode(
        token,
        key=settings.jwt_secret_key.get_secret_value(),
        algorithms=[settings.jwt_algorithm],
        options={"require": ["exp", "iat", "sub"]},
    )
