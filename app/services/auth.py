from pwdlib.exceptions import UnknownHashError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password, verify_password
from app.models.user import User

_dummy_password_hash = hash_password("dummy-password-never-used")

async def authenticate_user(
        session: AsyncSession,
        username: str,
        password: str,
) -> User | None:
    """认证用户名和密码。

    Args:
        session: 数据库异步会话。
        username: 函数输入参数。
        password: 明文密码。

    Returns:
        返回类型为 User | None 的执行结果。
    """
    user = await session.scalar(
        select(User).where(User.username == username)
    )

    stored_hash = (
        user.password_hash 
        if user is not None
        else _dummy_password_hash
    )

    try:
        password_matches = verify_password(password, stored_hash)
    except UnknownHashError:
        password_matches = False

    if(
        user is None
        or user.status != "启用"
        or not password_matches
    ):
        return None

    return user
