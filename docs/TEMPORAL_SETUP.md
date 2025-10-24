# Temporal Setup Guide

## Prerequisites

1. Docker and Docker Compose installed
2. Temporal Server running in Docker (via docker-compose)

## Initial Setup

### 1. Configure Search Attributes

**IMPORTANT:** This is a **one-time setup** that must be done after starting the Temporal container.

#### Option A: Using Docker Exec (Recommended)

```bash
# Ensure Temporal container is running
docker compose up -d temporal

# Wait for Temporal to be ready (30-60 seconds)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health
# Should show "SERVING"

# Add search attribute by running tctl inside the container
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes \
  --name TabarioRunId \
  --type Keyword
```

#### Option B: Using Host Machine CLI (If Installed)

If you have Temporal CLI installed directly on your host:

```bash
# Using modern Temporal CLI
temporal operator search-attribute create --name TabarioRunId --type Keyword --address 127.0.0.1:7233

# OR using legacy tctl
tctl --address 127.0.0.1:7233 admin cluster add-search-attributes --name TabarioRunId --type Keyword
```

#### Option C: Using Temporal Cloud UI

If you're using Temporal Cloud, you can configure this through the web UI:
1. Log in to Temporal Cloud
2. Go to **Namespace Settings**
3. Navigate to **Search Attributes**
4. Click **Add Search Attribute**
5. Name: `TabarioRunId`, Type: `Keyword`
6. Save

### 2. Verify Configuration

Check that the search attribute was added:

```bash
# Via Docker (recommended)
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster get-search-attributes | grep TabarioRunId

# Or if you have CLI on host
temporal operator search-attribute list --address 127.0.0.1:7233 | grep TabarioRunId
```

You should see `TabarioRunId` with type `Keyword` in the output.

## Running the Worker

Start the Temporal worker:

```bash
docker-compose up temporal-worker
```

Or run locally:

```bash
python -m videomerge.temporal.worker
```

## Testing Workflows

### Start a Test Workflow

```python
from temporalio.client import Client
from videomerge.temporal.workflows import VideoGenerationWorkflow
from videomerge.models import OrchestrateStartRequest

client = await Client.connect("localhost:7233")

request = OrchestrateStartRequest(
    run_id="test-run-123",
    # ... other fields
)

handle = await client.start_workflow(
    VideoGenerationWorkflow.run,
    request,
    id=f"test-run-123",
    task_queue="video-generation-task-queue",
)
```

### Search for Workflows

In Temporal UI, search for all workflows in a run:

```
TabarioRunId = "test-run-123"
```

## Troubleshooting

### Search Attribute Not Working

**Symptom:** Workflows start but searching by `TabarioRunId` returns no results.

**Solution:**
1. Verify the search attribute exists: `temporal operator search-attribute list`
2. Ensure you're searching in the correct namespace
3. Wait a few seconds for indexing (search attributes are eventually consistent)

### Worker Connection Issues

**Symptom:** Worker fails to connect to Temporal server.

**Solution:**
1. Check `TEMPORAL_SERVER_URL` in your environment/config
2. Verify Temporal server is running: `docker-compose ps`
3. Check network connectivity: `telnet localhost 7233`

### Child Workflows Not Starting

**Symptom:** Parent workflow starts but child workflows don't appear.

**Solution:**
1. Check worker logs for errors
2. Verify `ProcessSceneWorkflow` is registered in the worker
3. Check task queue name matches: `video-generation-task-queue`

## Monitoring

### View Workflow Hierarchy

1. Open parent workflow in Temporal UI
2. Go to **History** tab
3. Look for `ChildWorkflowExecutionStarted` events
4. Click on child workflow IDs to navigate

### Search by Run ID

To see all workflows (parent + children) for a specific run:

```
RunId = "your-run-id-here"
```

### Find Parent from Child

1. Open child workflow
2. Check **Memo** section
3. Find `parent_workflow_id`
4. Search for that workflow ID

## Additional Resources

- [Temporal Workflow Correlation Guide](./temporal-workflow-correlation.md)
- [Temporal Documentation](https://docs.temporal.io)
- [Search Attributes Guide](https://docs.temporal.io/visibility#search-attribute)
