from __future__ import annotations

from dataclasses import dataclass
from math import isclose
from pathlib import Path
import re
from typing import Any, Iterable

import yaml


_DOCS_NAMESPACE = "tabario-core-api"
_ROUTE_HEADING_RE = re.compile(r"^##\s+`(?P<route>[A-Z]+\s+/[^`]+)`\s*$")
_RELATED_DOC_RE = re.compile(r"-\s+`(?P<doc>[^`]+\.md)`")
_FRONTMATTER_RE = re.compile(r"\A---\s*\r?\n(?P<frontmatter>.*?)(?:\r?\n)---\s*(?:\r?\n|\Z)", re.DOTALL)


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
    metadata: dict[str, Any]

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
            "metadata": self.metadata,
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
            raw_content = path.read_text(encoding="utf-8")
            frontmatter, content = self._parse_frontmatter(raw_content)
            headings = self._extract_headings(content)
            inferred_routes = self._extract_routes(content)
            inferred_related_docs = self._extract_related_docs(content)
            metadata = self._normalize_frontmatter(frontmatter)
            title = str(metadata.get("title") or (headings[0] if headings else path.stem.replace("-", " ").title()))
            category = str(metadata.get("category") or category)
            routes = tuple(self._unique_values([*self._coerce_string_list(metadata.get("routes")), *inferred_routes]))
            related_docs = tuple(
                self._unique_values([*self._coerce_string_list(metadata.get("related")), *inferred_related_docs])
            )
            resource_uri = f"docs://{self._namespace}/{doc_id}"
            contract_doc = ContractDoc(
                doc_id=doc_id,
                title=title,
                category=category,
                relative_path=relative_path,
                resource_uri=resource_uri,
                content=content,
                headings=tuple(headings),
                routes=routes,
                related_docs=related_docs,
                metadata=metadata,
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
        """Return semantically ranked search results over titles, routes, metadata, and content."""
        normalized_query = query.strip()
        if not normalized_query:
            return []

        query_terms = self._extract_search_terms(normalized_query)
        if not query_terms:
            return []

        scored: list[tuple[float, ContractDoc]] = []
        for doc in self._docs_by_id.values():
            if category and doc.category != category:
                continue

            score = self._score_doc(doc=doc, query=normalized_query, query_terms=query_terms)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: (-item[0], item[1].doc_id))
        return [
            {
                **doc.to_summary(),
                "score": round(score, 6),
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

    @staticmethod
    def _parse_frontmatter(raw_content: str) -> tuple[dict[str, Any], str]:
        match = _FRONTMATTER_RE.match(raw_content)
        if match is None:
            return {}, raw_content

        loaded = yaml.safe_load(match.group("frontmatter")) or {}
        if not isinstance(loaded, dict):
            raise ValueError("YAML frontmatter must be a mapping")
        content = raw_content[match.end():]
        return loaded, content

    def _normalize_frontmatter(self, frontmatter: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {}
        for key, value in frontmatter.items():
            if key in {"routes", "related", "tags", "workflows", "models", "integrations", "audience"}:
                normalized[key] = self._coerce_string_list(value)
                continue
            normalized[key] = value
        return normalized

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

    def _score_doc(self, doc: ContractDoc, query: str, query_terms: tuple[str, ...]) -> float:
        """Score a document for a free-text query using weighted semantic heuristics."""
        weighted_sections = self._build_weighted_sections(doc)
        total_score = 0.0
        matched_terms: set[str] = set()

        for text, weight in weighted_sections:
            section_score, section_matches = self._score_text_section(text=text, query_terms=query_terms, weight=weight)
            total_score += section_score
            matched_terms.update(section_matches)

        phrase_score = self._score_phrase_matches(doc=doc, query=query)
        total_score += phrase_score

        route_bonus = self._score_route_semantics(doc=doc, query_terms=query_terms)
        total_score += route_bonus

        coverage = len(matched_terms) / len(query_terms)
        if matched_terms:
            total_score += coverage * 3.0
            if isclose(coverage, 1.0):
                total_score += 2.0

        return total_score

    def _build_weighted_sections(self, doc: ContractDoc) -> list[tuple[str, float]]:
        """Build weighted searchable sections for a contract document."""
        metadata_values = self._flatten_metadata_values(doc.metadata)
        return [
            (doc.title, 7.0),
            (" ".join(doc.headings), 5.0),
            (" ".join(doc.routes), 8.0),
            (doc.doc_id.replace("/", " ").replace("-", " "), 4.5),
            (" ".join(doc.related_docs), 2.5),
            (" ".join(metadata_values), 3.5),
            (doc.content, 1.5),
        ]

    def _score_text_section(self, text: str, query_terms: tuple[str, ...], weight: float) -> tuple[float, set[str]]:
        """Score one document section against query terms and return matched normalized terms."""
        normalized_text = self._normalize_search_text(text)
        if not normalized_text:
            return 0.0, set()

        text_terms = self._extract_search_terms(normalized_text)
        if not text_terms:
            return 0.0, set()

        text_term_set = set(text_terms)
        text_bigrams = set(self._build_ngrams(text_terms, size=2))
        text_char_ngrams = self._build_char_ngrams(normalized_text)
        score = 0.0
        matched_terms: set[str] = set()

        for term in query_terms:
            if term in text_term_set:
                score += weight * 2.2
                matched_terms.add(term)
                continue

            if any(candidate.startswith(term) or term.startswith(candidate) for candidate in text_term_set if len(candidate) >= 3):
                score += weight * 1.1
                matched_terms.add(term)
                continue

            term_char_ngrams = self._build_char_ngrams(term)
            if term_char_ngrams and self._jaccard_similarity(term_char_ngrams, text_char_ngrams) >= 0.55:
                score += weight * 0.8
                matched_terms.add(term)

        query_bigrams = set(self._build_ngrams(query_terms, size=2))
        if query_bigrams:
            overlap = len(query_bigrams & text_bigrams)
            score += overlap * weight * 1.8

        return score, matched_terms

    def _score_phrase_matches(self, doc: ContractDoc, query: str) -> float:
        """Boost exact or near-exact phrase matches in high-signal fields."""
        normalized_query = self._normalize_search_text(query)
        if not normalized_query:
            return 0.0

        phrase_fields = [
            (doc.title, 10.0),
            (" ".join(doc.routes), 12.0),
            (" ".join(doc.headings), 7.0),
            (doc.doc_id.replace("/", " "), 6.0),
        ]
        score = 0.0
        for field_value, weight in phrase_fields:
            normalized_field = self._normalize_search_text(field_value)
            if not normalized_field:
                continue
            if normalized_query in normalized_field:
                score += weight
                continue
            if self._token_sequence_overlap(normalized_query, normalized_field) >= 0.75:
                score += weight * 0.65
        return score

    def _score_route_semantics(self, doc: ContractDoc, query_terms: tuple[str, ...]) -> float:
        """Boost documents whose route or path semantics align with the query intent."""
        doc_terms = set(self._extract_search_terms(doc.doc_id))
        for route in doc.routes:
            doc_terms.update(self._extract_search_terms(route))
        for related_doc in doc.related_docs:
            doc_terms.update(self._extract_search_terms(related_doc))

        shared_terms = doc_terms & set(query_terms)
        if not shared_terms:
            return 0.0
        return len(shared_terms) * 1.7

    def _flatten_metadata_values(self, metadata: dict[str, Any]) -> list[str]:
        """Flatten metadata values into searchable string fragments."""
        flattened: list[str] = []
        for value in metadata.values():
            if isinstance(value, list):
                flattened.extend(str(item) for item in value if str(item).strip())
                continue
            if value is None:
                continue
            text = str(value).strip()
            if text:
                flattened.append(text)
        return flattened

    @staticmethod
    def _extract_search_terms(text: str) -> tuple[str, ...]:
        """Normalize free text into compact semantic search terms."""
        normalized_text = ContractCatalog._normalize_search_text(text)
        if not normalized_text:
            return ()

        raw_terms = re.findall(r"[a-z0-9]+", normalized_text)
        terms = [ContractCatalog._normalize_term(term) for term in raw_terms]
        unique_terms = ContractCatalog._unique_values(terms)
        return tuple(unique_terms)

    @staticmethod
    def _normalize_search_text(text: str) -> str:
        """Normalize text for semantic matching across paths, routes, and prose."""
        lowered_text = text.lower().replace("_", " ").replace("-", " ").replace("/", " ")
        return re.sub(r"\s+", " ", lowered_text).strip()

    @staticmethod
    def _normalize_term(term: str) -> str:
        """Normalize one token into a lightweight semantic root form."""
        normalized = term.lower().strip()
        if len(normalized) <= 3:
            return normalized

        suffixes = ("ations", "ation", "ments", "ment", "ingly", "edly", "ings", "ing", "ers", "ies", "ied", "ed", "es", "s")
        for suffix in suffixes:
            if normalized.endswith(suffix) and len(normalized) - len(suffix) >= 3:
                if suffix in {"ies", "ied"}:
                    return f"{normalized[:-3]}y"
                return normalized[: -len(suffix)]
        return normalized

    @staticmethod
    def _build_ngrams(terms: Iterable[str], size: int) -> tuple[str, ...]:
        """Build contiguous token n-grams from normalized terms."""
        sequence = [term for term in terms if term]
        if len(sequence) < size:
            return ()
        return tuple(" ".join(sequence[index : index + size]) for index in range(len(sequence) - size + 1))

    @staticmethod
    def _build_char_ngrams(text: str, size: int = 3) -> set[str]:
        """Build normalized character n-grams for fuzzy matching."""
        collapsed = re.sub(r"\s+", "", text)
        if len(collapsed) < size:
            return {collapsed} if collapsed else set()
        return {collapsed[index : index + size] for index in range(len(collapsed) - size + 1)}

    @staticmethod
    def _jaccard_similarity(left: set[str], right: set[str]) -> float:
        """Return Jaccard similarity for two token sets."""
        if not left or not right:
            return 0.0
        return len(left & right) / len(left | right)

    @staticmethod
    def _token_sequence_overlap(query: str, text: str) -> float:
        """Return normalized overlap between query and text token sequences."""
        query_terms = query.split()
        text_terms = text.split()
        if not query_terms or not text_terms:
            return 0.0
        shared = sum(1 for term in query_terms if term in text_terms)
        return shared / len(query_terms)

    @staticmethod
    def _normalize_route(route: str) -> str:
        method, _, path = route.strip().partition(" ")
        return f"{method.upper()} {path.strip()}"

    @staticmethod
    def _coerce_string_list(value: Any) -> list[str]:
        if value is None:
            return []
        if isinstance(value, str):
            return [value]
        if isinstance(value, list):
            return [str(item) for item in value if str(item).strip()]
        return [str(value)]

    @staticmethod
    def _unique_values(values: Iterable[str]) -> list[str]:
        unique: list[str] = []
        seen: set[str] = set()
        for value in values:
            normalized = value.strip()
            if not normalized or normalized in seen:
                continue
            unique.append(normalized)
            seen.add(normalized)
        return unique


def build_default_catalog(repo_root: Path | None = None) -> ContractCatalog:
    """Build a catalog rooted at this repository's docs/api directory."""
    package_root = Path(__file__).resolve().parents[2]
    resolved_root = repo_root or package_root
    docs_root = resolved_root / "docs" / "api"
    if not docs_root.exists():
        raise FileNotFoundError(f"Documentation root does not exist: {docs_root}")
    return ContractCatalog(docs_root=docs_root).load()
