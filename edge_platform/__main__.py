"""
Entry point for the Industrial Edge AI Platform.
Can be run via: python -m edge_platform
For the full auto-setup experience, use run.py instead.
"""

import asyncio
import logging
import logging.handlers
import os
import sys
from pathlib import Path

# Ensure project root is in path
ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import uvicorn

from edge_platform.api.app import create_app
from edge_platform.config import get_config
from edge_platform.platform import EdgePlatform


def setup_logging(level: str = "INFO") -> None:
    """Configure logging for the platform."""
    log_dir = ROOT / "data" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    
    file_handler = logging.handlers.RotatingFileHandler(
        str(log_dir / "platform.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=3,
    )
    handlers.append(file_handler)
    
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=handlers,
    )
    
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("aiomqtt").setLevel(logging.WARNING)


async def run_platform() -> None:
    """Main async entry point."""
    config = get_config()
    
    setup_logging(level="INFO")
    logger = logging.getLogger(__name__)
    
    platform = EdgePlatform(config)
    app = create_app(config, platform)
    
    await platform.start()
    
    server_config = uvicorn.Config(
        app,
        host=config.api.host,
        port=config.api.port,
        workers=1,
        log_level="warning",
        access_log=False,
    )
    server = uvicorn.Server(server_config)
    
    logger.info("API server running on http://%s:%d", config.api.host, config.api.port)
    
    try:
        await server.serve()
    except asyncio.CancelledError:
        pass
    finally:
        await platform.stop()


def main() -> None:
    """Synchronous entry point."""
    try:
        asyncio.run(run_platform())
    except KeyboardInterrupt:
        pass
    except Exception as e:
        logging.getLogger(__name__).critical("Platform crashed: %s", e, exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
