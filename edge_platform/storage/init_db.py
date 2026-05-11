"""
Database initialization script.
Creates all required databases and directories.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from edge_platform.config import get_config
from edge_platform.storage.sqlite_store import SQLiteStore


async def init_databases():
    """Initialize all databases."""
    config = get_config()
    
    print("Initializing databases...")
    
    # SQLite hot storage
    store = SQLiteStore(config.storage.sqlite)
    await store.initialize()
    await store.close()
    print(f"  ✓ SQLite: {config.storage.sqlite.path}")
    
    # Create archive directories
    archive_dir = Path(config.storage.parquet.archive_dir)
    (archive_dir / "telemetry").mkdir(parents=True, exist_ok=True)
    (archive_dir / "inference").mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Archives: {archive_dir}")
    
    # Create model directory
    model_dir = Path(config.inference.model_dir)
    model_dir.mkdir(parents=True, exist_ok=True)
    print(f"  ✓ Models: {model_dir}")
    
    print("\nDatabase initialization complete.")


if __name__ == "__main__":
    asyncio.run(init_databases())
