# Docs MCP Server

This package exposes `docs/api` as an MCP server for the `tabario-core-api` documentation namespace.

## Layout

- `docs-mcp/docs_mcp/`: importable Python package
- `docs-mcp/run.py`: top-level launcher script

## Namespace

Resource URIs use:

```text
docs://tabario-core-api/...
```

Examples:

- `docs://tabario-core-api/index`
- `docs://tabario-core-api/endpoints/orchestrate`
- `docs://tabario-core-api/workflows/video-generation-workflow`
- `docs://tabario-core-api/integrations/supabase-storage`
- `docs://tabario-core-api/versioning`

## Exposed Tools

- `list_contracts(category=None)`
- `read_contract(doc_id)`
- `find_contracts(query, category=None, limit=10)`
- `get_endpoint_by_route(route)`
- `get_contract_relations(doc_id)`

## Design Goals

This MCP server is designed to expose contract documentation in a way that is reliable for both humans and agents.

A well-designed MCP server should make it easy to:

- discover the right document quickly
- identify which document is authoritative for a route, workflow, or integration
- follow relationships between contracts without guessing
- return stable, structured metadata instead of forcing consumers to infer everything from raw markdown

In this project, two important design choices support those goals:

- **YAML frontmatter** for explicit metadata
- **semantic ranking** for better contract retrieval

## Categories

The current catalog infers categories from the `docs/api` path:

- `endpoints`
- `workflows`
- `integrations`
- `data-contracts`
- `meta`

## Run Locally

Install the docs MCP dependencies separately from the main application requirements:

```powershell
python -m pip install -r .\docs-mcp\requirements.txt
```

Then run the server over stdio:

```powershell
python .\docs-mcp\run.py
```

If you want to run the inner package directly, set `PYTHONPATH` to include `docs-mcp` and use:

```powershell
$env:PYTHONPATH = ".\docs-mcp"
python -m docs_mcp
```

## Notes

- the server indexes markdown under `docs/api`
- resource and tool ids use the `tabario-core-api` namespace to avoid collisions with docs from other projects
- route lookup is based on headings like ``## `POST /orchestrate/start` ``
- related document lookup is based on `## Related Contracts` and `## Related Documents` sections
- YAML frontmatter is supported and merged with inferred metadata from headings and sections
- `find_contracts(...)` uses semantic ranking across titles, routes, headings, metadata, and content rather than simple keyword counting

## YAML Frontmatter

YAML frontmatter gives each markdown document an explicit metadata layer.

In the context of a good MCP server, this matters because raw markdown alone is often not structured enough for strong retrieval. A document may describe an endpoint or workflow correctly, but without explicit metadata an agent has to guess:

- what category the document belongs to
- which routes it owns
- which workflows or integrations it is related to
- whether the document is meant for public, admin, test, or internal use

Frontmatter makes those relationships explicit and stable.

That improves MCP behavior in several ways:

- **better discovery**
  - tools can list and filter contracts using metadata rather than only filenames or headings
- **better retrieval accuracy**
  - route, workflow, tag, and audience metadata help the search layer find the right document
- **better interoperability**
  - agents and downstream tools can consume normalized metadata without custom parsing rules per document
- **better maintainability**
  - authors can add or refine meaning without rewriting the document body structure

You can add optional YAML frontmatter at the top of any contract markdown file:

```md
---
title: Orchestrate Endpoints
category: endpoints
routes:
  - POST /orchestrate/start
  - POST /orchestrate/generate-images
related:
  - workflows/video-generation-workflow.md
  - data-contracts/request-models.md
tags:
  - orchestration
  - public
audience:
  - public
kind: endpoint_contract
---
```

Supported frontmatter fields today:

- `title`
- `category`
- `routes`
- `related`
- `tags`
- `audience`
- `workflows`
- `models`
- `integrations`
- `kind`

Behavior:

- `title` and `category` override inferred values
- `routes` are merged with route headings found in the markdown body
- `related` is merged with related docs discovered in `## Related Contracts` and `## Related Documents`
- array-like fields are normalized into string lists and exposed in each document's `metadata`
- the markdown content returned by the MCP server excludes the frontmatter block

## Search Ranking

The `find_contracts(...)` tool uses a dependency-free semantic ranking strategy.

In the context of a good MCP server, search quality is not a convenience feature; it is part of the server's contract design.

If retrieval is weak, an agent may read the wrong contract first, miss the authoritative endpoint doc, or confuse a workflow contract with an integration contract. That leads to worse answers even if the docs themselves are correct.

Semantic ranking is used here so the server can rank results by likely intent, not just by how many times a string appears in a file.

This is especially important for technical documentation because:

- the most relevant doc is often the one with the best structural match, not the highest raw word frequency
- titles, routes, headings, tags, and related-doc metadata usually carry more meaning than repeated prose
- users and agents often search with approximate language such as `subtitle generation` or `start orchestration workflow`, not exact document titles

Signals considered today:

- high-weight matches in document `title`
- explicit route matches from `routes`
- heading matches
- frontmatter metadata such as `tags`, `audience`, `workflows`, `models`, and `integrations`
- normalized path and related-doc references
- lower-weight matches in full markdown body content

The ranker also boosts:

- exact or near-exact phrase matches
- query-term coverage across multiple fields
- lightweight inflection and fuzzy matching for related word forms

This gives the MCP server a better chance of returning:

- the endpoint contract that owns a route
- the workflow contract behind that endpoint
- the integration or webhook contract that defines the surrounding behavior

## Future Enhancements

- add audience labels such as `public`, `admin`, `test`, and `integration`
- add validation that mounted FastAPI routes map to contract docs
