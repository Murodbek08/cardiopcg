"""Create the FIRST administrator (production has no demo/seed users).

Usage (interactive - the password is read with getpass, never from argv):
    python scripts/create_admin.py --username admin --full-name "Bosh administrator"

Non-interactive (containers / CI): provide the password through the environment, not argv:
    CREATE_ADMIN_PASSWORD='...' python scripts/create_admin.py --username admin --full-name "..."

The password is never logged or printed. The script refuses to run if the username already exists.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.config import get_settings  # noqa: E402
from app.core.errors import AppError  # noqa: E402
from app.core.security import hash_password, validate_password_strength  # noqa: E402
from app.db.base import utcnow  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker, init_engine  # noqa: E402
from app.models.enums import AuditAction, UserRole, UserStatus  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services import audit_service  # noqa: E402

USERNAME_RE = re.compile(r"^[a-z0-9._-]{3,32}$")


async def create_admin(username: str, full_name: str, password: str, email: str | None) -> str:
    init_engine(get_settings())
    try:
        async with get_sessionmaker()() as s:
            exists = (await s.execute(select(User.id).where(User.username == username))).first()
            if exists:
                raise SystemExit(f"Error: username '{username}' already exists")
            validate_password_strength(password, 10, [username, full_name])
            u = User(
                username=username,
                email=email,
                password_hash=hash_password(password),
                full_name=full_name,
                role=UserRole.admin,
                status=UserStatus.active,
                must_change_password=False,
                password_changed_at=utcnow(),
            )
            s.add(u)
            await s.flush()
            audit_service.log_event(
                s,
                AuditAction.create,
                resource_type="user",
                resource_id=u.id,
                changes={"after": {"username": username, "role": "admin"}},
                meta={"via": "create_admin.py"},
            )
            await s.commit()
            return str(u.id)
    finally:
        await dispose_engine()


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--username", required=True)
    ap.add_argument("--full-name", required=True)
    ap.add_argument("--email", default=None)
    args = ap.parse_args()
    username = args.username.strip().lower()
    if not USERNAME_RE.match(username):
        raise SystemExit("Error: username must be 3-32 chars of [a-z0-9._-]")
    password = os.environ.get("CREATE_ADMIN_PASSWORD")
    if not password:
        password = getpass.getpass("Password: ")
        if getpass.getpass("Repeat password: ") != password:
            raise SystemExit("Error: passwords do not match")
    try:
        uid = asyncio.run(create_admin(username, args.full_name.strip(), password, args.email))
    except AppError as exc:
        raise SystemExit(f"Error: {exc.message}")
    print(f"Admin '{username}' created (id={uid}).")


if __name__ == "__main__":
    main()
