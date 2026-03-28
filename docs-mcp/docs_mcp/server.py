from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.fastmcp import FastMCP

from .catalog import ContractCatalog, build_default_catalog

_SERVER_NAME = "tabario-core-api-docs"
_RESOURCE_PREFIX = "docs://tabario-core-api"


def create_server(repo_root: Path | None = None) -> FastMCP:
    """Create a FastMCP server that exposes docs/api as MCP resources and tools."""
    catalog = build_default_catalog(repo_root=repo_root)
    server = FastMCP(_SERVER_NAME)
    _register_tools(server, catalog)
    _register_resources(server, catalog)
    return server


def _register_tools(server: FastMCP, catalog: ContractCatalog) -> None:
    @server.tool()
    def list_contracts(category: str | None = None) -> list[dict[str, Any]]:
        """List available contract documents, optionally filtered by category."""
        return catalog.list_docs(category=category)

    @server.tool()
    def read_contract(doc_id: str) -> dict[str, Any]:
        """Read a contract document by id or resource URI."""
        doc = catalog.get_doc(doc_id)
        if doc is None:
            raise ValueError(f"Unknown contract document: {doc_id}")
        return {
            **doc.to_summary(),
            "content": doc.content,
            "headings": list(doc.headings),
        }

    @server.tool()
    def find_contracts(query: str, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Search contract documents by free-text query."""
        return catalog.find_docs(query=query, category=category, limit=limit)

    @server.tool()
    def get_endpoint_by_route(route: str) -> dict[str, Any]:
        """Find the best matching endpoint contract for an HTTP route."""
        result = catalog.get_endpoint_by_route(route)
        if result is None:
            raise ValueError(f"No endpoint contract found for route: {route}")
        return result

    @server.tool()
    def get_contract_relations(doc_id: str) -> dict[str, Any]:
        """Return a contract plus the related docs it references."""
        result = catalog.get_contract_relations(doc_id)
        if result is None:
            raise ValueError(f"Unknown contract document: {doc_id}")
        return result


def _register_resources(server: FastMCP, catalog: ContractCatalog) -> None:
    @server.resource(f"{_RESOURCE_PREFIX}/index")
    def api_contract_index() -> str:
        """Return the top-level API contract index document."""
        doc = catalog.get_doc("README")
        if doc is None:
            raise ValueError("Missing docs/api/README.md")
        return doc.content

    for doc in catalog.list_docs():
        _register_document_resource(server, catalog, doc["id"])


def _register_document_resource(server: FastMCP, catalog: ContractCatalog, doc_id: str) -> None:
    resource_uri = f"{_RESOURCE_PREFIX}/{doc_id}"

    @server.resource(resource_uri)
    def _document_resource(current_doc_id: str = doc_id) -> str:
        doc = catalog.get_doc(current_doc_id)
        if doc is None:
            raise ValueError(f"Unknown contract document: {current_doc_id}")
        return doc.content


def main() -> None:
    """Run the MCP server over stdio."""
    server = create_server()
    server.run()
