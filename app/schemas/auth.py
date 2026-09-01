from typing import Literal
from pydantic import BaseModel,ConfigDict,Field,SecretStr

Role = Literal["投放人员","增长运营","投放负责人"]

class LoginRequest(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    password: SecretStr

class UserInfo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    username: str
    display_name: str
    role: Role

class LoginResult(BaseModel):
    token: str
    token_type: Literal["bearer"] = "bearer"
    user: UserInfo

