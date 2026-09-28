"""Local admin CLI.

    python -m app.cli create-admin admin@example.com "Full Name"
The password is read interactively (or from HIREAI_ADMIN_PASSWORD) and never echoed.
"""

import asyncio
import getpass
import os
import sys

from sqlalchemy import select

from app.core.database import AsyncSessionLocal, engine
from app.core.security import hash_password
from app.models.enums import UserRole
from app.models.users import User


async def create_admin(email: str, name: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        if await db.scalar(select(User).where(User.email == email)):
            print("user already exists")
            return
        db.add(User(email=email, full_name=name, role=UserRole.PLATFORM_ADMIN, password_hash=hash_password(password)))
        await db.commit()
        print(f"created platform admin {email}")
    await engine.dispose()


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] != "create-admin":
        print(__doc__)
        sys.exit(1)
    pw = os.environ.get("HIREAI_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(pw) < 12:
        sys.exit("admin password must be at least 12 characters")
    asyncio.run(create_admin(sys.argv[2], sys.argv[3], pw))
