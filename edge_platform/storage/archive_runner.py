"""
Standalone archive runner for systemd timer execution.
Runs a single archival cycle and exits.
"""

import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from edge_platform.config import get_config
from edge_platform.storage.archiver import DataArchiver

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


async def run_archival():
    """Run a single archival cycle."""
    config = get_config()
    
    archiver = DataArchiver(
        config.storage.sqlite.path,
        config.storage.parquet,
        config.retention,
    )
    
    logger.info("Starting archival cycle...")
    stats = await archiver.run_archival_cycle()
    logger.info("Archival complete: %s", stats)


if __name__ == "__main__":
    asyncio.run(run_archival())
