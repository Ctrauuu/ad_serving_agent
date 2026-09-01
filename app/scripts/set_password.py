import asyncio
from getpass import getpass

from pwdlib import PasswordHash
from sqlalchemy import text

from app.infrastructure.database import async_session, engine

password_hasher = PasswordHash.recommended()


async def main() -> None:
    username = input("用户名: ").strip()
    password = getpass("新密码: ")
    confirmation = getpass("确认密码: ")

    if not username:
        raise SystemExit("用户名不能为空")
    if len(password) < 8:
        raise SystemExit("密码不能少于 8 位")
    if password != confirmation:
        raise SystemExit("两次输入的密码不一致")

    async with async_session.begin() as session:
        result = await session.execute(
            text(
                """
                UPDATE `user`
                SET password_hash = :password_hash
                WHERE username = :username
                """
            ),
            {
                "username": username,
                "password_hash": password_hasher.hash(password),
            },
        )

        if result.rowcount != 1: # type: ignore
            raise SystemExit("用户不存在")

    await engine.dispose()
    print("密码已安全更新")


if __name__ == "__main__":
    asyncio.run(main())