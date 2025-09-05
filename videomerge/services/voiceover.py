from pathlib import Path
from typing import Optional
import requests
from fastapi import HTTPException

from videomerge.config import VOICEOVER_SERVICE_URL, VOICEOVER_API_KEY
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def synthesize_voice(text: str, output_path: Path, timeout: int = 480) -> Path:
    """Call the external voiceover service to synthesize speech and save to output_path.

    - Uses VOICEOVER_SERVICE_URL from environment, endpoint: /synthesize/clone_voice
    - Sends JSON body: {"text": <script>}
    - Expects audio bytes in response with an audio/* content-type.
    """
    if not text or not text.strip():
        raise HTTPException(status_code=400, detail="Text for voice synthesis cannot be empty")

    base_url = VOICEOVER_SERVICE_URL.rstrip("/")
    url = f"{base_url}/synthesize/clone_voice"
    headers = {"Accept": "*/*", "Content-Type": "application/json"}
    if VOICEOVER_API_KEY:
        headers["Authorization"] = f"Bearer {VOICEOVER_API_KEY}"

    logger.info("[voiceover] Requesting synthesis from %s", url)

    try:
        with requests.post(url, json={"text": text}, headers=headers, stream=True, timeout=timeout) as r:
            r.raise_for_status()
            ctype = (r.headers.get("content-type") or "").lower()
            if not (ctype.startswith("audio/") or ctype in ("application/octet-stream",)):
                # Try parsing as JSON error
                try:
                    data = r.json()
                    raise HTTPException(status_code=502, detail=f"Voiceover service returned non-audio response: {data}")
                except Exception:
                    raise HTTPException(status_code=502, detail=f"Voiceover service returned non-audio response. content-type={ctype}")

            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, "wb") as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

        if output_path.stat().st_size == 0:
            raise HTTPException(status_code=502, detail="Voiceover audio generated is empty")

        logger.info("[voiceover] Saved audio to %s (%s bytes)", output_path, output_path.stat().st_size)
        return output_path
    except requests.RequestException as e:
        logger.exception("[voiceover] Request failed: %s", e)
        raise HTTPException(status_code=502, detail=f"Voiceover service request failed: {str(e)}")
