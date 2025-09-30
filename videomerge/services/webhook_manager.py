# videomerge/services/webhook_manager.py
import asyncio
import httpx
import json
from typing import Dict, Optional
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class WebhookManager:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_webhook(self, webhook_url: str, job_data: Dict, event_type: str = "job_completed") -> bool:
        """Send webhook notification to N8N"""
        try:
            payload = {
                "event": event_type,
                "timestamp": asyncio.get_event_loop().time(),
                "data": job_data
            }

            response = await self._client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"}
            )

            if response.status_code == 200:
                logger.info(f"Webhook sent successfully to {webhook_url} for job {job_data.get('job_id')} (event: {event_type})")
                return True
            else:
                logger.error(f"Webhook failed with status {response.status_code}: {response.text}")
                return False

        except Exception as e:
            logger.error(f"Error sending webhook to {webhook_url}: {e}")
            return False

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()


# Global instance
webhook_manager = WebhookManager()
