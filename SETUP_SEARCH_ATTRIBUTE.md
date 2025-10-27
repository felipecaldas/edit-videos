# Quick Setup: Temporal Search Attribute

## Step 1: Wait for Temporal to be Ready

After starting containers, wait for Temporal to initialize (30-60 seconds):

```bash
# Check if ready (use temporal hostname from inside container)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health
```

You should see `SERVING`. If you get "connection refused", wait longer.

## Step 2: Add Search Attribute

Run this **once**:

```bash
echo "Y" | sudo docker exec -i video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes --name TabarioRunId --type Keyword
```

That's it! Now you can search workflows by `TabarioRunId` in the Temporal UI to find all workflows (parent + children) for a specific run.

## Verify

```bash
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster get-search-attributes | grep TabarioRunId
```

You should see `TabarioRunId` with type `Keyword` in the output.

## Usage in Temporal UI

Search for all workflows in a run:
```
TabarioRunId = "your-run-id-here"
```

Example:
```
TabarioRunId = "tabario-user-13289527-075a-42da-9ddb-357f8634553b"
```

---

For more details, see:
- [Quick Start Guide (Fedora)](docs/QUICK_START_FEDORA.md)
- [Workflow Correlation Guide](docs/temporal-workflow-correlation.md)
