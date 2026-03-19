# videomerge/services/webhook_manager.py
import asyncio
import httpx
from typing import Dict, Optional
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


class WebhookManager:
    def __init__(self):
        self._client = httpx.AsyncClient(timeout=30.0)

    async def send_webhook(self, webhook_url: str, job_data: Dict, event_type: str = "job_completed") -> bool:
        """Send webhook notification to N8N"""
        payload = {
            "event": event_type,
            "timestamp": asyncio.get_event_loop().time(),
            "data": job_data,
        }

        try:
            response = await self._client.post(
                webhook_url,
                json=payload,
                headers={"Content-Type": "application/json"},
            )

            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                logger.error(
                    "Webhook failed with status %s for %s (event: %s): %s",
                    response.status_code,
                    webhook_url,
                    event_type,
                    response.text,
                )
                raise RuntimeError(
                    f"Webhook request failed with status {response.status_code}: {response.text}"
                ) from exc

            logger.info(
                "Webhook sent successfully to %s for workflow %s (event: %s)",
                webhook_url,
                job_data.get("workflow_id"),
                event_type,
            )
            return True

        except httpx.HTTPError as exc:
            logger.error("Error sending webhook to %s: %s", webhook_url, exc)
            raise RuntimeError(f"Error sending webhook to {webhook_url}: {exc}") from exc

    async def close(self):
        """Close HTTP client"""
        await self._client.aclose()


# Global instance
webhook_manager = WebhookManager()
