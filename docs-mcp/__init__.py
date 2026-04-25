from pathlib import Path
import sys

PACKAGE_ROOT = Path(__file__).resolve().parent
if str(PACKAGE_ROOT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_ROOT))

from docs_mcp import ContractCatalog, ContractDoc, build_default_catalog, create_server

__all__ = [
    "ContractCatalog",
    "ContractDoc",
    "build_default_catalog",
    "create_server",
]
