# Quick Start Guide - Fedora Server

This guide is specifically for your Fedora server setup where everything runs in Docker containers.

## Initial Setup (One-Time)

### 1. Start Temporal Container

```bash
cd /path/to/edit-videos
docker compose up -d temporal postgres
```

**Wait for Temporal to be ready** (this can take 30-60 seconds):

```bash
# Check if Temporal is ready (use temporal hostname from inside container)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health
```

You should see `SERVING` in the output. If you get "connection refused", wait a bit longer and try again.

### 2. Configure Search Attributes

```bash
# Add the TabarioRunId search attribute
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes --name TabarioRunId --type Keyword
```

**What this does:**
- Executes `tctl` command inside the Temporal container
- Adds the `TabarioRunId` search attribute (type: Keyword)
- No need to install Temporal CLI on your Fedora host
- Run this **once** per Temporal namespace

**Verify it worked:**
```bash
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster get-search-attributes | grep TabarioRunId
```

You should see `TabarioRunId` in the output.

### 3. Start All Services

```bash
docker compose up -d
```

This starts:
- `temporal` - Temporal server
- `temporal-ui` - Temporal web UI
- `temporal-worker` - Your workflow worker
- `video-merger` - Your API service
- `postgres` - Database
- Any other services in your compose file

## Daily Operations

### Start Services

```bash
docker compose up -d
```

### Stop Services

```bash
docker compose down
```

### View Logs

```bash
# All services
docker compose logs -f

# Specific service
docker compose logs -f temporal-worker
docker compose logs -f video-merger
```

### Restart a Service

```bash
# After code changes
docker compose restart temporal-worker
docker compose restart video-merger
```

## Accessing Services

- **Temporal UI**: http://192.168.68.52:8087 (or your server IP)
- **API**: http://192.168.68.52:8086 (or your server IP)
- **Temporal gRPC**: localhost:7233 (internal)

## Workflow Correlation

### Search for All Workflows in a Run

In Temporal UI, use the search:
```
TabarioRunId = "your-run-id-here"
```

Example:
```
TabarioRunId = "tabario-user-13289527-075a-42da-9ddb-357f8634553b"
```

This will show all workflows for that run:
- 1 parent workflow (`VideoGenerationWorkflow`)
- Multiple child workflows (scene-0, scene-1, scene-2, etc.)

### Find Parent from Child

1. Open the child workflow in Temporal UI
2. Go to **Summary** tab
3. Look at **Memo** section
4. Find `parent_workflow_id`
5. Search for that workflow ID

### Identify Failed Scene

If a child workflow fails:
- Workflow ID: `...-scene-5` → Scene 5 failed
- Check memo: `scene_index = "5"`
- Navigate to parent to see full context

## Troubleshooting

### Search Attribute Not Working

**Problem:** Searching by `TabarioRunId` returns no results.

**Solution:**
```bash
# First, check if Temporal is ready
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health

# If you see "SERVING", add the search attribute
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes \
  --name TabarioRunId \
  --type Keyword
```

**If you get "connection refused":**
- Temporal is still starting up, wait 30-60 seconds
- Check logs: `docker logs video-editor-temporal-1`
- Restart if needed: `docker compose restart temporal`

### Worker Not Processing Workflows

**Problem:** Workflows stuck in "Running" state.

**Check worker logs:**
```bash
docker compose logs -f temporal-worker
```

**Common issues:**
- Worker container crashed → Check logs for Python errors
- Wrong task queue → Verify `video-generation-task-queue`
- Temporal server not reachable → Check network connectivity

**Restart worker:**
```bash
docker compose restart temporal-worker
```

### Container Won't Start

**Check status:**
```bash
docker compose ps
```

**Check logs:**
```bash
docker compose logs temporal
docker compose logs postgres
```

**Common issues:**
- Port already in use → Check with `netstat -tulpn | grep 7233`
- Database not ready → Wait for postgres healthcheck
- Volume permissions → Check `/mnt/tp-share/n8n-shared` permissions

### Rebuild After Code Changes

```bash
# Rebuild and restart
docker compose up -d --build

# Or specific service
docker compose up -d --build temporal-worker
```

## Maintenance

### View Database

```bash
docker exec -it video-editor-postgres-1 psql -U temporal -d temporal
```

### Clean Up Old Workflows

Use Temporal UI to:
1. Filter by date range
2. Terminate old workflows
3. Or let them expire based on retention policy

### Update Temporal Version

Edit `docker-compose.yml` or `docker-compose.local.yml`:
```yaml
temporal:
  image: temporalio/auto-setup:1.29.0  # Update version here
```

Then:
```bash
docker compose pull temporal
docker compose up -d temporal
```

## Production Checklist

Before deploying to production:

- [ ] Search attribute configured (`TabarioRunId`)
- [ ] All services start successfully
- [ ] Test workflow completes end-to-end
- [ ] Search by `TabarioRunId` returns results
- [ ] Worker logs show no errors
- [ ] Temporal UI accessible
- [ ] API health check passes: `curl http://localhost:8086/health`

## Additional Resources

- [Full Temporal Setup Guide](./TEMPORAL_SETUP.md)
- [Workflow Correlation Guide](./temporal-workflow-correlation.md)
- [Deployment Checklist](./DEPLOYMENT_CHECKLIST.md)
