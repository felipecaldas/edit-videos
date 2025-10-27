#!/usr/bin/env python3
"""
Test the complete image->video flow using the same code as temporal worker.
This simulates the exact flow that happens in the temporal workflow.
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
    RUNPOD_VIDEO_INSTANCE_ID,
    RUNPOD_API_KEY,
    WORKFLOW_I2V_PATH,
    get_image_workflows,
)
from videomerge.services.comfyui_client import (
    get_image_client,
    get_video_client,
    ClientType,
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

async def test_complete_flow():
    """Test the complete image->video generation flow."""
    
    print("=" * 80)
    print("COMPLETE IMAGE->VIDEO FLOW TEST")
    print("=" * 80)
    
    if RUN_ENV != "runpod":
        print("ERROR: This test requires RUN_ENV=runpod")
        return False
    
    try:
        # Step 1: Generate image (same as temporal worker)
        print("\n📸 STEP 1: Generating image...")
        workflows = get_image_workflows()
        workflow_filename = workflows["default"]  # Uses runpod-t2i-fluxdev.json
        workflow_path = Path("videomerge/comfyui-workflows") / workflow_filename
        
        image_client = get_image_client()
        prompt_text = "A person running in a park, cinematic style"
        
        print(f"Using workflow: {workflow_filename}")
        print(f"Prompt: {prompt_text}")
        
        # Submit image generation
        prompt_id = await asyncio.to_thread(
            image_client.submit_text_to_image, 
            prompt_text, 
            template_path=workflow_path
        )
        print(f"✓ Image job submitted: {prompt_id}")
        
        # Poll for completion
        filenames = await asyncio.to_thread(
            image_client.poll_until_complete, 
            prompt_id, 
            timeout_s=600, 
            poll_interval_s=15
        )
        
        if not filenames:
            print("✗ Image generation failed: No output files")
            return False
        
        image_hint = filenames[0]  # This should be a base64 string for RunPod
        print(f"✓ Image generated: {image_hint[:50]}...")
        
        # Step 2: Process image for video (same as temporal worker)
        print("\n🔄 STEP 2: Processing image for video generation...")
        
        # This simulates the upload_image_for_video_generation activity
        if image_hint.startswith("data:image/"):
            print("✓ Using RunPod base64 image directly")
            processed_image = image_hint
        else:
            print("✗ Expected base64 image from RunPod")
            return False
        
        # Step 3: Generate video (same as temporal worker)
        print("\n🎬 STEP 3: Generating video...")
        video_prompt = "A person running in a park, cinematic style, smooth motion"
        
        video_client = get_video_client()
        print(f"Using video workflow: {WORKFLOW_I2V_PATH.name}")
        print(f"Video prompt: {video_prompt}")
        
        # Submit video generation
        video_prompt_id = await asyncio.to_thread(
            video_client.submit_image_to_video,
            video_prompt,
            processed_image,  # This is the base64 string
            template_path=WORKFLOW_I2V_PATH,
        )
        print(f"✓ Video job submitted: {video_prompt_id}")
        
        # Poll for completion
        video_filenames = await asyncio.to_thread(
            video_client.poll_until_complete,
            video_prompt_id,
            timeout_s=600,
            poll_interval_s=15
        )
        
        if not video_filenames:
            print("✗ Video generation failed: No output files")
            return False
        
        print(f"✓ Video generated: {video_filenames}")
        
        # Success!
        print("\n🎉 COMPLETE FLOW SUCCESS!")
        print(f"✓ Image: {image_hint[:50]}...")
        print(f"✓ Video: {video_filenames}")
        
        return True
        
    except Exception as e:
        print(f"\n✗ ERROR: {type(e).__name__}: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    print("Starting complete image->video flow test...")
    
    success = asyncio.run(test_complete_flow())
    
    print("\n" + "=" * 80)
    print("SUMMARY")
    print("=" * 80)
    print(f"Complete flow test: {'✓ PASSED' if success else '✗ FAILED'}")
    
    if success:
        print("\n✓ The complete RunPod image->video flow works!")
        sys.exit(0)
    else:
        print("\n✗ Complete flow test failed!")
        sys.exit(1)
