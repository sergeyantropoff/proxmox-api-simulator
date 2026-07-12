"""Apply a deterministic simulation seed."""

import asyncio
import json

from app.config import get_settings
from app.simulation.seed import seed_url


async def run() -> None:
    state = await seed_url(get_settings().database_url.get_secret_value())
    print(json.dumps(state, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(run())
