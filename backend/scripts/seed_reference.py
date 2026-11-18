"""Load the drug-KB YAML seed (backend/data/drugs) into the database. Idempotent; seeds are DRAFT (not clinically reviewed).

    python scripts/seed_reference.py [--dir backend/data/drugs]
Contains no users/passwords.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.config import get_settings  # noqa: E402
from app.db.session import dispose_engine, get_sessionmaker, init_engine  # noqa: E402
from app.services import kb_service  # noqa: E402


async def main(directory: str | None) -> None:
    init_engine(get_settings())
    try:
        async with get_sessionmaker()() as s:
            res = await kb_service.seed_from_yaml(s, directory)
            await s.commit()
            print(res)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default=None)
    asyncio.run(main(ap.parse_args().dir))
