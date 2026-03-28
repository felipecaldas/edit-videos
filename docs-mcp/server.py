from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from docs_mcp.server import create_server, main

__all__ = [
    "create_server",
    "main",
]


if __name__ == "__main__":
    main()
