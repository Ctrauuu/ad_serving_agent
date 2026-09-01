from typing import Annotated
from fastapi.security import HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.database import get_session
from fastapi import Depends,HTTPException,status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from app.models.user import User
from app.schemas.auth import Role
from app.core.security import decode_access_token
from jwt.exceptions import InvalidTokenError

bearer_scheme = HTTPBearer(auto_error=False)

SessionDep = Annotated[AsyncSession, Depends(get_session)]

def unauthorized_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized",
        headers={"WWW-Authenticate": "Bearer"},
    )

# HTTPAuthorizationCredentials(
#     scheme="Bearer",
#     credentials="eyJhbGciOi..."
# )

async def get_current_user(
        credentials: Annotated[
            HTTPAuthorizationCredentials | None,
            Depends(bearer_scheme)
        ],
        session: SessionDep,
) -> User:
    if credentials is None:
        raise unauthorized_exception()

    try:
        payload = decode_access_token(credentials.credentials)
        user_id = int(payload["sub"])
        token_role = payload["role"]
    except(InvalidTokenError, KeyError, TypeError, ValueError):
        raise unauthorized_exception() from None

    user = await session.get(User, user_id)

    if(
        user is None or user.status != "启用" or user.role != token_role
    ):
        raise unauthorized_exception()

    return user

CurrentUser = Annotated[User, Depends(get_current_user)]

def require_role(required_role: Role):
    async def role_dependency(current_user: CurrentUser) -> User:
        if current_user.role != required_role:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="权限不足",
            )
        return current_user

    return role_dependency