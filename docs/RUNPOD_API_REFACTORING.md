# RunPod Worker API Refactoring Summary

## Overview
Refactored the codebase to use the new RunPod worker `/run` endpoint structure that expects `input.comfyui_workflow_name` instead of loading and sending full workflow JSON files.

## Changes Made

### 1. Created YAML Configuration File
**File**: `videomerge/image_style_mapping.yaml`

Maps user-facing `image_style` values to ComfyUI workflow names:
- `cinematic` → `image_qwen_t2i`
- `disney` → `image_disneyizt_t2i`
- `crayon-drawing` → `crayon-drawing`
- `anime` → `T2I_ChromaAnimaAIO`

This file can be easily updated to add or remove workflow mappings without code changes.

### 2. Updated Configuration Module
**File**: `videomerge/config.py`

- Added `yaml` import for loading the mapping file
- Created `_load_image_style_mapping()` function to load the YAML config
- Added `IMAGE_STYLE_TO_WORKFLOW_MAPPING` global constant
- Added `DEFAULT_I2V_WORKFLOW_NAME` constant (`video_wan2_2_14B_i2v`)
- Updated `_load_workflow_config()` to return the default I2V workflow name

### 3. Refactored RunPodComfyUIClient
**File**: `videomerge/services/comfyui_client.py`

#### Text-to-Image (T2I) Changes:
- **Removed**: Workflow JSON file loading logic
- **Changed**: Now requires `comfyui_workflow_name` parameter
- **New payload structure**:
  ```json
  {
    "input": {
      "prompt": "<text>",
      "width": 720,
      "height": 1024,
      "comfyui_workflow_name": "image_qwen_t2i",
      "comfy_org_api_key": "<key>"
    }
  }
  ```
- Raises `ValueError` if `comfyui_workflow_name` is not provided
- `template_path` parameter is now deprecated but kept for backward compatibility

#### Image-to-Video (I2V) Changes:
- **Removed**: Workflow JSON file loading logic
- **Added**: Optional `comfyui_workflow_name` parameter (defaults to `video_wan2_2_14B_i2v`)
- **New payload structure**:
  ```json
  {
    "input": {
      "prompt": "<text>",
      "image": "data:image/png;base64,<data>",
      "width": 480,
      "height": 640,
      "length": 81,
      "comfyui_workflow_name": "video_wan2_2_14B_i2v",
      "comfy_org_api_key": "<key>"
    }
  }
  ```
- `template_path` parameter is now deprecated but kept for backward compatibility

### 4. Updated Temporal Workflows
**File**: `videomerge/temporal/workflows.py`

- Imported `IMAGE_STYLE_TO_WORKFLOW_MAPPING` from config
- **Removed**: Hardcoded `if/elif` mapping for `cinematic` and `disney` styles
- **Changed**: Now uses `IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)` to dynamically map styles to workflow names
- Temporal parent and child workflow structure remains **EXACTLY the same** as requested

### 5. Updated Test Routes
**File**: `videomerge/routers/test_runs.py`

- Imported `IMAGE_STYLE_TO_WORKFLOW_MAPPING` from config
- **Removed**: Hardcoded `if/elif` mapping
- **Changed**: Now uses `IMAGE_STYLE_TO_WORKFLOW_MAPPING.get(image_style)` for consistency

### 6. Updated Unit Tests
**File**: `tests/test_comfyui_client.py`

- Updated `test_submit_text_to_image_success` to use `comfyui_workflow_name` parameter
- Renamed `test_submit_text_to_image_with_comfyui_workflow_name` to `test_submit_text_to_image_validates_payload`
- Added `test_submit_text_to_image_requires_workflow_name` to verify error handling
- Added `test_submit_image_to_video_validates_payload` to verify I2V payload structure
- All tests now validate the new API structure matches the OpenAPI specification

## API Compliance

The refactored code now fully complies with the RunPod Worker OpenAPI specification:

### Supported T2I Workflows
- `image_qwen_t2i`
- `image_disneyizt_t2i`
- `crayon-drawing`
- `T2I_ChromaAnimaAIO`
- `qwen-image-fast-runpod`

### Supported I2V Workflows
- `video_wan2_2_14B_i2v` (default)
- `I2V-Wan-2.2-Lightning-runpod`

## Backward Compatibility

### Local ComfyUI Client
- **No changes** to `LocalComfyUIClient` - it still uses workflow JSON files as before
- Local deployment continues to work exactly as it did

### RunPod Client
- `template_path` parameter is deprecated but still accepted (ignored)
- Old code will fail with a clear error message directing users to use `comfyui_workflow_name`

## Benefits

1. **Simplified API calls**: No more loading and parsing workflow JSON files for RunPod
2. **Centralized configuration**: All workflow mappings in one YAML file
3. **Easy maintenance**: Add/remove workflows by editing YAML, no code changes needed
4. **Better error messages**: Clear validation when required parameters are missing
5. **API compliance**: Matches the official RunPod worker OpenAPI specification
6. **Temporal workflows unchanged**: Parent and child workflow structure preserved exactly

## Testing

Run the updated tests:
```powershell
python -m pytest tests/test_comfyui_client.py -v
```

All tests should pass with the new API structure.

## Migration Guide

### For T2I Generation
**Before:**
```python
client.submit_text_to_image(
    prompt_text,
    template_path=Path("workflow.json"),
    image_width=720,
    image_height=1024
)
```

**After:**
```python
client.submit_text_to_image(
    prompt_text,
    comfyui_workflow_name="image_qwen_t2i",
    image_width=720,
    image_height=1024
)
```

### For I2V Generation
**Before:**
```python
client.submit_image_to_video(
    prompt_text,
    image_data,
    template_path=WORKFLOW_I2V_PATH
)
```

**After:**
```python
# Uses default workflow name automatically
client.submit_image_to_video(
    prompt_text,
    image_data,
    template_path=WORKFLOW_I2V_PATH  # Deprecated but still accepted
)

# Or explicitly specify workflow
client.submit_image_to_video(
    prompt_text,
    image_data,
    template_path=WORKFLOW_I2V_PATH,
    comfyui_workflow_name="I2V-Wan-2.2-Lightning-runpod"
)
```

## Files Modified

1. `videomerge/image_style_mapping.yaml` (NEW)
2. `videomerge/config.py`
3. `videomerge/services/comfyui_client.py`
4. `videomerge/temporal/workflows.py`
5. `videomerge/routers/test_runs.py`
6. `tests/test_comfyui_client.py`
7. `docs/RUNPOD_API_REFACTORING.md` (NEW - this file)

## Next Steps

1. Test the changes with actual RunPod endpoints
2. Update any documentation that references the old API structure
3. Consider adding more workflow mappings to the YAML file as needed
