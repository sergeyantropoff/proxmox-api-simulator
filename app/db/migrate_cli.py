"""Apply configured database migrations."""

import asyncio

from app.config import get_settings
from app.db.migrations import migrate_url


async def run() -> None:
    settings = get_settings()
    count = await migrate_url(settings.database_url.get_secret_value())
    print(f"applied {count} migration(s)")


if __name__ == "__main__":
    asyncio.run(run())
