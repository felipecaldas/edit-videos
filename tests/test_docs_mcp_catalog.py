from pathlib import Path
import importlib
import sys


def _load_catalog_module():
    package_root = Path(__file__).resolve().parents[1] / "docs-mcp"
    if str(package_root) not in sys.path:
        sys.path.insert(0, str(package_root))
    return importlib.import_module("docs_mcp.catalog")


def test_build_default_catalog_indexes_expected_docs() -> None:
    catalog_module = _load_catalog_module()
    catalog = catalog_module.build_default_catalog(Path(__file__).resolve().parents[1])

    orchestrate_doc = catalog.get_doc("endpoints/orchestrate")
    assert orchestrate_doc is not None
    assert orchestrate_doc.resource_uri == "docs://tabario-core-api/endpoints/orchestrate"
    assert "POST /orchestrate/start" in orchestrate_doc.routes


def test_route_lookup_returns_related_docs() -> None:
    catalog_module = _load_catalog_module()
    catalog = catalog_module.build_default_catalog(Path(__file__).resolve().parents[1])

    result = catalog.get_endpoint_by_route("POST /orchestrate/generate-videos")

    assert result is not None
    assert result["contract"]["id"] == "endpoints/orchestrate"
    related_ids = {item["id"] for item in result["related"]}
    assert "workflows/storyboard-video-workflow" in related_ids
