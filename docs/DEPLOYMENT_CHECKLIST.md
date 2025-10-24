# Deployment Checklist

## Pre-Deployment Setup (One-Time)

### 1. Temporal Search Attributes Configuration

**When:** Before deploying the application for the first time to a new Temporal namespace.

**Where:** Run on your **host machine**, **CI/CD pipeline**, or via **Temporal Cloud UI** (NOT in the Docker container).

**How:**

#### Option A: Using Docker Exec (Recommended for Self-Hosted)

```bash
# Start Temporal container
docker compose up -d temporal

# Wait for it to be ready (30-60 seconds)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health

# Add search attribute via tctl inside container
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes \
  --name TabarioRunId \
  --type Keyword
```

#### Option B: Temporal Cloud UI

1. Log in to Temporal Cloud
2. Navigate to your namespace
3. Go to **Namespace Settings** → **Search Attributes**
4. Add: `TabarioRunId` (type: `Keyword`)

**Verify:**
```bash
# Via Docker
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster get-search-attributes | grep TabarioRunId

# Or if you have CLI on host
temporal operator search-attribute list --address 127.0.0.1:7233 | grep TabarioRunId
```

You should see `TabarioRunId` with type `Keyword` in the output.

---

## Deployment Steps

### 1. Build Docker Images
```powershell
docker-compose build
```

### 2. Start Services
```powershell
docker-compose up -d
```

### 3. Verify Services

**Check all containers are running:**
```powershell
docker-compose ps
```

Expected output:
- `temporal-server` - running
- `temporal-worker` - running
- `api` - running
- `redis` - running
- `comfyui` - running

**Check worker logs:**
```powershell
docker-compose logs -f temporal-worker
```

Look for:
```
Starting Temporal worker...
Worker started successfully
```

### 4. Test Workflow Execution

**Start a test workflow** (via API or Temporal CLI):
```bash
# Example using Temporal CLI
temporal workflow start \
  --task-queue video-generation-task-queue \
  --type VideoGenerationWorkflow \
  --workflow-id test-run-123 \
  --input '{"run_id": "test-run-123", ...}'
```

**Verify in Temporal UI:**
1. Open Temporal UI (usually http://localhost:8080)
2. Search for workflow: `WorkflowId = "test-run-123"`
3. Check that child workflows appear with pattern: `test-run-123-scene-0`, `test-run-123-scene-1`, etc.

### 5. Test Search Attributes

**In Temporal UI, search:**
```
TabarioRunId = "test-run-123"
```

**Expected:** Should return the parent workflow and all child workflows.

If no results appear:
- ✗ Search attribute not configured → Go back to Pre-Deployment Setup
- ✗ Workflows haven't been indexed yet → Wait 30 seconds and try again

---

## Post-Deployment Verification

### 1. Workflow Correlation Test

**Create a test workflow:**
```bash
curl -X POST http://localhost:8000/orchestrate/start \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "correlation-test-001",
    "prompts": [
      {"image_prompt": "test 1", "video_prompt": "test 1"},
      {"image_prompt": "test 2", "video_prompt": "test 2"}
    ],
    "script": "Test script",
    "language": "en"
  }'
```

**Verify in Temporal UI:**

1. **Search by TabarioRunId:**
   ```
   TabarioRunId = "correlation-test-001"
   ```
   Should return 3 workflows: 1 parent + 2 children

2. **Open a child workflow** (e.g., `correlation-test-001-scene-0`)
   - Check **Memo** section contains:
     - `parent_workflow_id`
     - `parent_run_id`
     - `scene_index`
     - `run_id`

3. **Open parent workflow** (`correlation-test-001`)
   - Check **History** tab for `ChildWorkflowExecutionStarted` events

### 2. Failure Scenario Test

**Trigger a failure** (e.g., invalid prompt):
```bash
curl -X POST http://localhost:8000/orchestrate/start \
  -H "Content-Type: application/json" \
  -d '{
    "run_id": "failure-test-001",
    "prompts": [{"image_prompt": "", "video_prompt": ""}],
    "script": "",
    "language": "en"
  }'
```

**Verify you can trace the failure:**
1. Find failed child workflow in Temporal UI
2. Check its **Memo** to find `parent_workflow_id`
3. Navigate to parent workflow
4. Confirm you can see the full context

---

## Troubleshooting

### Search Attribute Not Working

**Symptom:** Searching by `TabarioRunId` returns no results.

**Solutions:**
1. Verify attribute exists:
   ```bash
   temporal operator search-attribute list
   ```
2. Check you're in the correct namespace
3. Wait 30-60 seconds for indexing
4. Restart Temporal server if using local dev setup

### Worker Not Starting

**Symptom:** `temporal-worker` container exits or shows errors.

**Solutions:**
1. Check logs:
   ```powershell
   docker-compose logs temporal-worker
   ```
2. Verify `TEMPORAL_SERVER_URL` in environment
3. Ensure Temporal server is running and accessible
4. Check Python dependencies are installed

### Child Workflows Not Appearing

**Symptom:** Parent workflow starts but no child workflows.

**Solutions:**
1. Check worker is running and processing tasks
2. Verify task queue name: `video-generation-task-queue`
3. Check parent workflow logs for errors
4. Ensure `ProcessSceneWorkflow` is registered in worker

---

## Production Deployment Notes

### Infrastructure as Code

Add search attribute configuration to your IaC:

**Terraform Example:**
```hcl
resource "temporal_search_attribute" "tabario_run_id" {
  name = "TabarioRunId"
  type = "Keyword"
}
```

**Kubernetes Job Example:**
```yaml
apiVersion: batch/v1
kind: Job
metadata:
  name: temporal-setup-search-attributes
spec:
  template:
    spec:
      containers:
      - name: temporal-cli
        image: temporalio/admin-tools:latest
        command:
          - temporal
          - operator
          - search-attribute
          - create
          - --name
          - TabarioRunId
          - --type
          - Keyword
      restartPolicy: OnFailure
```

### CI/CD Integration

Add to your deployment pipeline:

```yaml
# GitHub Actions example
- name: Configure Temporal Search Attributes
  run: |
    temporal operator search-attribute create \
      --name TabarioRunId \
      --type Keyword \
      --address ${{ secrets.TEMPORAL_ADDRESS }} \
      --namespace ${{ secrets.TEMPORAL_NAMESPACE }}
  continue-on-error: true  # Ignore if already exists
```

---

## Rollback Procedure

If you need to rollback:

1. **Stop new workflows:**
   ```powershell
   docker-compose stop temporal-worker
   ```

2. **Let existing workflows complete:**
   - Monitor in Temporal UI
   - Wait for all workflows to finish or timeout

3. **Deploy previous version:**
   ```powershell
   git checkout <previous-version>
   docker-compose up -d --build
   ```

4. **Verify:**
   - Check worker logs
   - Test a simple workflow
   - Verify search still works

---

## Monitoring

### Key Metrics to Monitor

1. **Workflow Success Rate:**
   - Track completed vs failed workflows
   - Alert on failure rate > 5%

2. **Child Workflow Correlation:**
   - Verify all child workflows have parent info in memo
   - Alert if orphaned child workflows detected

3. **Search Attribute Performance:**
   - Monitor query response times
   - Alert if searches take > 5 seconds

4. **Worker Health:**
   - Monitor worker uptime
   - Alert if worker restarts > 3 times/hour

### Useful Queries

**Find all failed workflows in last 24h:**
```
ExecutionStatus = "Failed" AND StartTime > "2024-01-01T00:00:00Z"
```

**Find all workflows for a specific run:**
```
TabarioRunId = "your-run-id"
```

**Find orphaned child workflows (no parent):**
```
WorkflowType = "ProcessSceneWorkflow" AND WorkflowId CONTAINS "-scene-"
```
(Then manually check if parent exists)

---

## Additional Resources

- [Temporal Setup Guide](./TEMPORAL_SETUP.md)
- [Workflow Correlation Guide](./temporal-workflow-correlation.md)
- [Temporal Documentation](https://docs.temporal.io)
