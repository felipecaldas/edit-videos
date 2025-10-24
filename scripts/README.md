# Setup Scripts

This directory may contain setup scripts for configuring external dependencies.

## Temporal Search Attributes Setup

The `TabarioRunId` search attribute is required for parent-child workflow correlation in Temporal.

### Recommended Setup Method

Use `docker exec` to run `tctl` directly inside the Temporal container:

```bash
# Ensure Temporal container is running
docker compose up -d temporal

# Wait for Temporal to be ready (30-60 seconds)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health

# Add the TabarioRunId search attribute
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes \
  --name TabarioRunId \
  --type Keyword
```

### Why This Approach?

- **Simple**: One command, no scripts to maintain
- **Transparent**: You can see exactly what's being executed
- **No dependencies**: No need to install Temporal CLI on your host
- **Works everywhere**: Same command works on any system with Docker

### When to Run

- **Once per Temporal namespace** before deploying the application
- After starting the Temporal container for the first time
- Can be run multiple times safely (idempotent - will show "already exists" if present)

### Verify

```bash
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster get-search-attributes | grep TabarioRunId
```

You should see `TabarioRunId` with type `Keyword` in the output.

### Alternative: Temporal Cloud UI

If using Temporal Cloud:
1. Go to Namespace Settings
2. Navigate to Search Attributes
3. Add `TabarioRunId` (type: `Keyword`)

### Related Documentation

- [Quick Start Guide (Fedora)](../docs/QUICK_START_FEDORA.md)
- [Temporal Setup Guide](../docs/TEMPORAL_SETUP.md)
- [Workflow Correlation Guide](../docs/temporal-workflow-correlation.md)
- [Deployment Checklist](../docs/DEPLOYMENT_CHECKLIST.md)
