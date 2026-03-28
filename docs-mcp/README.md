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

## Categories

The current catalog infers categories from the `docs/api` path:

- `endpoints`
- `workflows`
- `integrations`
- `data-contracts`
- `meta`

## Run Locally

Install dependencies first, then run the server over stdio:

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

## Future Enhancements

- add YAML frontmatter for stronger metadata
- add audience labels such as `public`, `admin`, `test`, and `integration`
- add validation that mounted FastAPI routes map to contract docs
- add semantic ranking instead of simple keyword counting
