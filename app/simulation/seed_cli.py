"""Apply a deterministic simulation seed."""

import asyncio
import json
import os

from app.config import get_settings
from app.simulation.seed import seed_url


async def run() -> None:
    state = await seed_url(
        get_settings().database_url.get_secret_value(),
        os.getenv("SEED_PROFILE", "small"),
        large_nodes=int(os.getenv("SEED_LARGE_NODES", "10")),
        large_resources=int(os.getenv("SEED_LARGE_RESOURCES", "10000")),
    )
    print(json.dumps(state, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(run())
