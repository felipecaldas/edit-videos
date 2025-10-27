#!/usr/bin/env python3
"""
Standalone script to test RunPod image generation using the same code as temporal worker.
This script will:
1. Submit an image generation request to RunPod
2. Poll the status endpoint until completion or failure
3. Print the results and detailed debugging information
"""

import asyncio
import json
import logging
import os
import sys
import time
from pathlib import Path

# Add the project root to Python path
sys.path.insert(0, str(Path(__file__).parent))

from videomerge.config import (
    COMFYUI_URL,
    RUN_ENV,
    RUNPOD_IMAGE_INSTANCE_ID,
    RUNPOD_API_KEY,
    WORKFLOW_I2V_PATH,
    get_image_workflows,
)
from videomerge.services.comfyui_client import (
    ComfyUIClient,
    RunPodComfyUIClient,
    ClientType,
    get_image_client,
)

# Configure logging to see all debug messages
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

def test_runpod_image_generation():
    """Test RunPod image generation using the same code as temporal worker."""
    
    print("=" * 80)
    print("RUNPOD IMAGE GENERATION TEST")
    print("=" * 80)
    
    # Print configuration
    print(f"Configuration:")
    print(f"  RUN_ENV: {RUN_ENV}")
    print(f"  COMFYUI_URL: {COMFYUI_URL}")
    print(f"  RUNPOD_IMAGE_INSTANCE_ID: {RUNPOD_IMAGE_INSTANCE_ID}")
    print(f"  RUNPOD_API_KEY: {RUNPOD_API_KEY[:20]}..." if RUNPOD_API_KEY else "  RUNPOD_API_KEY: NOT SET")
    print()
    
    if RUN_ENV != "runpod":
        print("ERROR: This test requires RUN_ENV=runpod")
        return False
    
    if not RUNPOD_IMAGE_INSTANCE_ID:
        print("ERROR: RUNPOD_IMAGE_INSTANCE_ID is not set")
        return False
    
    if not RUNPOD_API_KEY:
        print("ERROR: RUNPOD_API_KEY is not set")
        return False
    
    try:
        # Get the image client (same as temporal worker)
        print("Creating RunPod image client...")
        client = get_image_client()
        print(f"Client type: {type(client).__name__}")
        print(f"Client instance ID: {client.instance_id}")
        print()
        
        # Get the workflow path (same as temporal worker)
        workflows = get_image_workflows()
        workflow_name = "runpod-fluxdev"  # Use the fluxdev workflow that matches Postman
        workflow_filename = workflows[workflow_name]
        workflow_path = Path("videomerge/comfyui-workflows") / workflow_filename
        
        print(f"Using workflow: {workflow_filename}")
        print(f"Workflow path: {workflow_path}")
        print()
        
        # Test prompt
        prompt_text = "A simple test image of a red apple on a wooden table, photorealistic, 4K"
        print(f"Test prompt: {prompt_text}")
        print()
        
        # Submit the image generation request (same as temporal worker)
        print("Submitting image generation request...")
        start_time = time.time()
        
        # This is the exact same code as in temporal/activities.py
        prompt_id = client.submit_text_to_image(prompt_text, template_path=workflow_path)
        
        submit_time = time.time() - start_time
        print(f"✓ Request submitted successfully!")
        print(f"  Prompt ID: {prompt_id}")
        print(f"  Submit time: {submit_time:.2f}s")
        print()
        
        # Poll for completion (same as temporal worker)
        print("Polling for completion...")
        poll_start_time = time.time()
        
        # This is the exact same polling code as in temporal/activities.py
        filenames = client.poll_until_complete(prompt_id, timeout_s=600, poll_interval_s=15)
        
        poll_time = time.time() - poll_start_time
        total_time = time.time() - start_time
        
        print(f"✓ Polling completed!")
        print(f"  Poll time: {poll_time:.2f}s")
        print(f"  Total time: {total_time:.2f}s")
        print(f"  Results: {filenames}")
        print()
        
        if filenames:
            print(f"✓ SUCCESS: Generated {len(filenames)} image(s)")
            for i, filename in enumerate(filenames):
                print(f"  Image {i+1}: {filename}")
                if filename.startswith("data:image/"):
                    print(f"    Base64 data length: {len(filename)} characters")
                    print(f"    Data type: {filename.split(':')[1].split(';')[0]}")
        else:
            print("✗ FAILURE: No images generated")
            return False
            
        return True
        
    except Exception as e:
        print(f"✗ ERROR: {type(e).__name__}: {e}")
        print("\nFull exception details:")
        import traceback
        traceback.print_exc()
        return False

def test_direct_runpod_api():
    """Test RunPod API directly without our client code."""
    print("\n" + "=" * 80)
    print("DIRECT RUNPOD API TEST")
    print("=" * 80)
    
    import requests
    
    # Test the exact payload from your Postman request
    workflow_path = Path("videomerge/comfyui-workflows/runpod-t2i-fluxdev.json")
    
    try:
        # Load and modify the workflow
        with open(workflow_path, 'r') as f:
            workflow_str = f.read()
        
        prompt_text = "A simple test image of a red apple on a wooden table, photorealistic, 4K"
        escaped_prompt = json.dumps(prompt_text)[1:-1]
        final_workflow_str = workflow_str.replace("{{ POSITIVE_PROMPT }}", escaped_prompt)
        payload = json.loads(final_workflow_str)
        
        # Make the request
        url = f"{COMFYUI_URL}/v2/{RUNPOD_IMAGE_INSTANCE_ID}/run"
        headers = {
            "Accept": "*/*",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {RUNPOD_API_KEY}",
            "User-Agent": "test-script/1.0"
        }
        
        print(f"URL: {url}")
        print(f"Headers: {json.dumps(headers, indent=2)}")
        print(f"Payload: {json.dumps(payload, indent=2)}")
        print()
        
        print("Making direct API request...")
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        
        print(f"Response status: {response.status_code}")
        print(f"Response headers: {dict(response.headers)}")
        print(f"Response body: {response.text}")
        
        if response.ok:
            data = response.json()
            job_id = data.get("id")
            print(f"✓ Job submitted: {job_id}")
            
            # Test polling
            if job_id:
                print(f"\nTesting polling for job {job_id}...")
                for i in range(10):  # Try 10 times
                    time.sleep(5)
                    status_url = f"{COMFYUI_URL}/v2/{RUNPOD_IMAGE_INSTANCE_ID}/status/{job_id}"
                    status_response = requests.get(status_url, headers=headers, timeout=15)
                    
                    if status_response.ok:
                        status_data = status_response.json()
                        status = status_data.get("status")
                        print(f"Poll {i+1}: Status = {status}")
                        
                        if status == "COMPLETED":
                            print("✓ Job completed successfully!")
                            print(f"Output: {json.dumps(status_data.get('output', {}), indent=2)}")
                            break
                        elif status == "FAILED":
                            error = status_data.get("error", "Unknown error")
                            print(f"✗ Job failed: {error}")
                            break
                    else:
                        print(f"Poll {i+1}: Error {status_response.status_code}: {status_response.text}")
        else:
            print("✗ Request failed")
            return False
            
    except Exception as e:
        print(f"✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True

if __name__ == "__main__":
    print("Starting RunPod image generation test...")
    print()
    
    # Test 1: Using our temporal worker code
    success1 = test_runpod_image_generation()
    
    # Test 2: Direct API call
    success2 = test_direct_runpod_api()
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Temporal worker code test: {'✓ PASSED' if success1 else '✗ FAILED'}")
    print(f"Direct API test: {'✓ PASSED' if success2 else '✗ FAILED'}")
    
    if success1 and success2:
        print("\n✓ All tests passed!")
        sys.exit(0)
    else:
        print("\n✗ Some tests failed!")
        sys.exit(1)
