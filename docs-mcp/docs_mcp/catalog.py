from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any, Iterable


_DOCS_NAMESPACE = "tabario-core-api"
_ROUTE_HEADING_RE = re.compile(r"^##\s+`(?P<route>[A-Z]+\s+/[^`]+)`\s*$")
_RELATED_DOC_RE = re.compile(r"-\s+`(?P<doc>[^`]+\.md)`")


@dataclass(frozen=True)
class ContractDoc:
    """Represents a documentation contract file exposed through MCP."""

    doc_id: str
    title: str
    category: str
    relative_path: str
    resource_uri: str
    content: str
    headings: tuple[str, ...]
    routes: tuple[str, ...]
    related_docs: tuple[str, ...]

    def to_summary(self) -> dict[str, Any]:
        """Return a compact, JSON-serializable summary for search and listing."""
        return {
            "id": self.doc_id,
            "title": self.title,
            "category": self.category,
            "path": self.relative_path,
            "resource_uri": self.resource_uri,
            "routes": list(self.routes),
            "related_docs": list(self.related_docs),
        }


class ContractCatalog:
    """Indexes markdown documentation under docs/api for MCP access."""

    def __init__(self, docs_root: Path, namespace: str = _DOCS_NAMESPACE) -> None:
        self._docs_root = docs_root
        self._namespace = namespace
        self._docs_by_id: dict[str, ContractDoc] = {}
        self._docs_by_route: dict[str, list[ContractDoc]] = {}

    @property
    def namespace(self) -> str:
        """Return the MCP namespace used for resources."""
        return self._namespace

    @property
    def docs_root(self) -> Path:
        """Return the root documentation path."""
        return self._docs_root

    def load(self) -> "ContractCatalog":
        """Load and index all markdown files under the docs root."""
        self._docs_by_id.clear()
        self._docs_by_route.clear()

        for path in sorted(self._docs_root.rglob("*.md")):
            relative_path = path.relative_to(self._docs_root).as_posix()
            doc_id = relative_path.removesuffix(".md")
            category = relative_path.split("/", 1)[0] if "/" in relative_path else "meta"
            content = path.read_text(encoding="utf-8")
            headings = self._extract_headings(content)
            routes = self._extract_routes(content)
            related_docs = self._extract_related_docs(content)
            title = headings[0] if headings else path.stem.replace("-", " ").title()
            resource_uri = f"docs://{self._namespace}/{doc_id}"
            contract_doc = ContractDoc(
                doc_id=doc_id,
                title=title,
                category=category,
                relative_path=relative_path,
                resource_uri=resource_uri,
                content=content,
                headings=tuple(headings),
                routes=tuple(routes),
                related_docs=tuple(related_docs),
            )
            self._docs_by_id[doc_id] = contract_doc
            for route in routes:
                normalized_route = self._normalize_route(route)
                self._docs_by_route.setdefault(normalized_route, []).append(contract_doc)

        return self

    def list_docs(self, category: str | None = None) -> list[dict[str, Any]]:
        """Return sorted document summaries, optionally filtered by category."""
        docs = self._docs_by_id.values()
        if category:
            docs = [doc for doc in docs if doc.category == category]
        return [doc.to_summary() for doc in sorted(docs, key=lambda item: item.doc_id)]

    def get_doc(self, doc_id: str) -> ContractDoc | None:
        """Return a document by id or resource URI."""
        normalized_id = doc_id.removeprefix(f"docs://{self._namespace}/").removesuffix(".md")
        normalized_id = normalized_id.removeprefix("docs/api/")
        normalized_id = normalized_id.removeprefix("/")
        return self._docs_by_id.get(normalized_id)

    def find_docs(self, query: str, category: str | None = None, limit: int = 10) -> list[dict[str, Any]]:
        """Return simple ranked search results over titles, headings, routes, and content."""
        normalized_terms = [term for term in re.split(r"\s+", query.lower().strip()) if term]
        if not normalized_terms:
            return []

        scored: list[tuple[int, ContractDoc]] = []
        for doc in self._docs_by_id.values():
            if category and doc.category != category:
                continue
            haystack = "\n".join([doc.title, *doc.headings, *doc.routes, doc.content]).lower()
            score = sum(haystack.count(term) for term in normalized_terms)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: (-item[0], item[1].doc_id))
        return [
            {
                **doc.to_summary(),
                "score": score,
            }
            for score, doc in scored[:limit]
        ]

    def get_endpoint_by_route(self, route: str) -> dict[str, Any] | None:
        """Return the best matching endpoint contract for an HTTP route."""
        normalized_route = self._normalize_route(route)
        matches = self._docs_by_route.get(normalized_route, [])
        if not matches:
            return None

        primary = matches[0]
        related = self._collect_related(primary.related_docs)
        return {
            "route": normalized_route,
            "contract": primary.to_summary(),
            "related": related,
            "all_matches": [match.to_summary() for match in matches],
        }

    def get_contract_relations(self, doc_id: str) -> dict[str, Any] | None:
        """Return a document plus any related contracts referenced by it."""
        doc = self.get_doc(doc_id)
        if doc is None:
            return None
        related = self._collect_related(doc.related_docs)
        return {
            "contract": doc.to_summary(),
            "related": related,
        }

    def _collect_related(self, related_docs: Iterable[str]) -> list[dict[str, Any]]:
        related: list[dict[str, Any]] = []
        seen: set[str] = set()
        for related_doc in related_docs:
            normalized = related_doc.removeprefix("docs/api/").removesuffix(".md")
            if normalized in seen:
                continue
            candidate = self._docs_by_id.get(normalized)
            if candidate is None:
                continue
            related.append(candidate.to_summary())
            seen.add(normalized)
        return related

    @staticmethod
    def _extract_headings(content: str) -> list[str]:
        headings: list[str] = []
        for line in content.splitlines():
            if line.startswith("#"):
                headings.append(line.lstrip("#").strip())
        return headings

    @staticmethod
    def _extract_routes(content: str) -> list[str]:
        routes: list[str] = []
        for line in content.splitlines():
            match = _ROUTE_HEADING_RE.match(line.strip())
            if match:
                routes.append(match.group("route"))
        return routes

    @staticmethod
    def _extract_related_docs(content: str) -> list[str]:
        related: list[str] = []
        in_related_section = False
        for line in content.splitlines():
            stripped = line.strip()
            if stripped == "## Related Contracts" or stripped == "## Related Documents":
                in_related_section = True
                continue
            if in_related_section and stripped.startswith("## "):
                break
            if not in_related_section:
                continue
            match = _RELATED_DOC_RE.search(stripped)
            if match:
                related.append(match.group("doc"))
        return related

    @staticmethod
    def _normalize_route(route: str) -> str:
        method, _, path = route.strip().partition(" ")
        return f"{method.upper()} {path.strip()}"


def build_default_catalog(repo_root: Path | None = None) -> ContractCatalog:
    """Build a catalog rooted at this repository's docs/api directory."""
    package_root = Path(__file__).resolve().parents[2]
    resolved_root = repo_root or package_root
    docs_root = resolved_root / "docs" / "api"
    if not docs_root.exists():
        raise FileNotFoundError(f"Documentation root does not exist: {docs_root}")
    return ContractCatalog(docs_root=docs_root).load()
