# Temporal Workflow Parent-Child Correlation Guide

## Overview

This document explains how to correlate child workflows back to their parent workflows in the Temporal UI, which is critical for debugging and operational visibility in production.

## Correlation Mechanisms Implemented

### 1. **Workflow ID Naming Convention**
Child workflows use a predictable naming pattern:
```
{run_id}-scene-{scene_index}
```

**Example:**
- Parent: `tabario-user-13289527-075a-42da-9ddb-357f8634553b`
- Children: 
  - `tabario-user-13289527-075a-42da-9ddb-357f8634553b-scene-0`
  - `tabario-user-13289527-075a-42da-9ddb-357f8634553b-scene-1`
  - etc.

### 2. **Memo Fields**
Each child workflow includes memo metadata:
- `parent_workflow_id`: The workflow ID of the parent
- `parent_run_id`: The run ID of the parent
- `scene_index`: Which scene this child is processing
- `run_id`: The overall run identifier

### 3. **Search Attributes**
Both parent and child workflows are tagged with:
- `TabarioRunId`: Contains the `run_id` for easy searching across all related workflows (parent + all children)

### 4. **Parent Workflow Info**
Child workflows log their parent information at startup for traceability.

## How to Find Parent from Child in Temporal UI

### Method 1: View Memo Fields
1. Open the **child workflow** in Temporal UI
2. Navigate to the **"Summary"** or **"Input and Results"** tab
3. Look for the **"Memo"** section
4. Find `parent_workflow_id` and `parent_run_id`
5. Click or search for that workflow ID to navigate to the parent

### Method 2: Check Workflow Logs
1. Open the **child workflow** in Temporal UI
2. Go to the **"History"** tab
3. Look for log entries at the start of execution
4. Find the log: `"Child workflow scene-X started by parent: workflow_id=..., run_id=..."`

### Method 3: Use Workflow ID Pattern
If you have a child workflow ID like:
```
tabario-user-13289527-075a-42da-9ddb-357f8634553b-scene-2
```

Remove the `-scene-X` suffix to get the parent workflow ID:
```
tabario-user-13289527-075a-42da-9ddb-357f8634553b
```

## How to Find Children from Parent in Temporal UI

### Method 1: Search by Run ID (Recommended)
1. In Temporal UI, go to **"Workflows"** page
2. Use the **Advanced Search** with:
   ```
   TabarioRunId = "your-run-id-here"
   ```
3. This will show the parent workflow AND all child workflows for that run

### Method 2: Search by Workflow ID Pattern
1. In Temporal UI, go to **"Workflows"** page
2. Use the search filter:
   ```
   WorkflowId STARTS_WITH "your-parent-workflow-id-scene-"
   ```

### Method 3: View Parent Workflow Details
1. Open the **parent workflow** in Temporal UI
2. Go to the **"Pending Activities"** or **"History"** tab
3. Look for `ChildWorkflowExecutionStarted` events
4. Each event contains the child workflow ID and run ID

## Production Debugging Scenarios

### Scenario 1: A Child Workflow Failed
**Problem:** Child workflow `tabario-user-13289527-075a-42da-9ddb-357f8634553b-scene-5` failed.

**Steps:**
1. Open the failed child workflow in Temporal UI
2. Check the **Memo** section → find `parent_workflow_id`
3. Navigate to the parent workflow
4. Check parent's history to see if other children also failed
5. Review parent's input to understand the full context

### Scenario 2: Find All Workflows for a Specific Run
**Problem:** Need to see all workflows (parent + children) for run ID `tabario-user-13289527-075a-42da-9ddb-357f8634553b`.

**Steps:**
1. Search using: `TabarioRunId = "tabario-user-13289527-075a-42da-9ddb-357f8634553b"`
2. Or search using: `WorkflowId STARTS_WITH "tabario-user-13289527-075a-42da-9ddb-357f8634553b"`

### Scenario 3: Identify Which Scene Failed
**Problem:** One scene processing failed, need to know which one.

**Steps:**
1. Look at the child workflow ID: `...-scene-5` → Scene 5 failed
2. Check the child's memo: `scene_index = "5"`
3. Review the parent's input to see what prompt was used for scene 5

## Search Attribute Configuration

**IMPORTANT:** The `TabarioRunId` search attribute must be configured in your Temporal cluster **before workflows can use it**. This is a **one-time setup**.

### Option 1: Using Docker Exec (Recommended for Self-Hosted)

```bash
# Ensure Temporal container is running
docker compose up -d temporal

# Wait for Temporal to be ready (30-60 seconds)
docker exec video-editor-temporal-1 tctl --address temporal:7233 cluster health

# Add search attribute via tctl inside container
docker exec video-editor-temporal-1 tctl --address temporal:7233 admin cluster add-search-attributes \
  --name TabarioRunId \
  --type Keyword
```

### Option 2: Using Temporal Cloud UI

For Temporal Cloud deployments:

1. Log in to Temporal Cloud
2. Go to **Namespace Settings**
3. Navigate to **Search Attributes**
4. Click **Add Search Attribute**
5. Name: `TabarioRunId`, Type: `Keyword`
6. Save

### Option 3: Using Host Machine CLI (If Installed)

If you have Temporal CLI installed directly on your host:

```bash
# Modern Temporal CLI
temporal operator search-attribute create --name TabarioRunId --type Keyword --address 127.0.0.1:7233

# Legacy tctl
tctl --address 127.0.0.1:7233 admin cluster add-search-attributes --name TabarioRunId --type Keyword
```

**Important Notes:**
- Use type `Keyword` (not `String`) for exact matching on IDs - provides better performance
- This only needs to be done once per Temporal namespace
- For self-hosted Temporal in Docker, use `docker exec` (Option 1)
- For production, add this to your infrastructure-as-code or deployment pipeline

## Best Practices

1. **Always check memo fields first** - They provide the most direct parent-child link
2. **Use consistent naming** - The `{run_id}-scene-{index}` pattern makes correlation obvious
3. **Enable workflow logging** - Logs provide additional context for debugging
4. **Monitor search attributes** - Ensure they're properly indexed for fast queries
5. **Document your workflow hierarchy** - Keep this guide updated as workflows evolve

## Additional Resources

- [Temporal Child Workflows Documentation](https://docs.temporal.io/workflows#child-workflow)
- [Temporal Search Attributes](https://docs.temporal.io/visibility#search-attribute)
- [Temporal Memo Fields](https://docs.temporal.io/workflows#memo)
