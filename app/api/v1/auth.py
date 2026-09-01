from fastapi import APIRouter, HTTPException, status

from app.api.dependencies.auth import CurrentUser, SessionDep
from app.api.routing import UnifiedResponseRoute
from app.core.security import create_access_token
from app.schemas.auth import LoginRequest, LoginResult, UserInfo
from app.services.auth import authenticate_user

router = APIRouter(
    prefix="/auth",
    tags=["auth"],
    route_class=UnifiedResponseRoute
)

@router.post("/login", response_model=None)
async def login(
    form: LoginRequest,
    session: SessionDep,
) -> LoginResult:
    user = await authenticate_user(
        session,
        form.username, 
        form.password.get_secret_value()
        )
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return LoginResult(
        token=create_access_token(user.id, user.role),
        user=UserInfo.model_validate(user)
    )


@router.get("/me", response_model=None)
async def me(
    current_user: CurrentUser
) -> UserInfo:
    return UserInfo.model_validate(current_user)
