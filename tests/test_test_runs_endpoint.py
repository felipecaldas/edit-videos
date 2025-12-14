import json
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient

from videomerge.main import create_app


class DummyComfyClient:
    def __init__(self, *, kind: str, tmp_dir: Path) -> None:
        self.kind = kind
        self.tmp_dir = tmp_dir
        self.submitted: List[Dict[str, Any]] = []

    def submit_text_to_image(
        self,
        prompt_text: str,
        *,
        template_path: Path,
        client_id: str | None = None,
        image_width: int | None = None,
        image_height: int | None = None,
    ) -> str:
        self.submitted.append(
            {
                "kind": "t2i",
                "prompt": prompt_text,
                "template": str(template_path),
                "image_width": image_width,
                "image_height": image_height,
            }
        )
        return "img-job-1"

    def submit_image_to_video(
        self,
        prompt_text: str,
        image_input: str,
        *,
        template_path: Path,
        client_id: str | None = None,
        run_id: str | None = None,
    ) -> str:
        self.submitted.append(
            {
                "kind": "i2v",
                "prompt": prompt_text,
                "image_input": image_input,
                "template": str(template_path),
                "run_id": run_id,
            }
        )
        return "vid-job-1"

    def poll_until_complete(self, prompt_id: str, *, timeout_s: int, poll_interval_s: float, prefer_node_ids=None):
        if self.kind == "image":
            return ["dummy_image.png"]
        return ["dummy_video.mp4"]

    def fetch_output_bytes(self, hint: str):
        if hint.endswith(".png"):
            return hint, b"png-bytes"
        return hint, b"mp4-bytes"

    def upload_image_to_input(self, filename: str, content: bytes, overwrite: bool = True) -> str:
        return filename


@pytest.mark.asyncio
async def test_tests_run_endpoint_creates_outputs(monkeypatch, tmp_path: Path) -> None:
    app = create_app()

    # Patch DATA_SHARED_BASE to temporary directory
    import videomerge.routers.test_runs as test_runs_router

    test_runs_router.DATA_SHARED_BASE = tmp_path

    recorded: Dict[str, Any] = {}

    async def fake_generate_scene_prompts(run_id: str, script: str, image_style: str | None = None):
        recorded["run_id"] = run_id
        recorded["script"] = script
        recorded["image_style"] = image_style
        return [
            {"image_prompt": "img prompt 1", "video_prompt": "vid prompt 1"},
            {"image_prompt": "img prompt 2", "video_prompt": "vid prompt 2"},
        ]

    monkeypatch.setattr(test_runs_router, "generate_scene_prompts", fake_generate_scene_prompts)

    img_client = DummyComfyClient(kind="image", tmp_dir=tmp_path)
    vid_client = DummyComfyClient(kind="video", tmp_dir=tmp_path)

    def fake_get_client(client_type, force_refresh: bool = False):
        # client_type is an Enum in prod code; compare by .value when available
        value = getattr(client_type, "value", str(client_type))
        return img_client if value == "image" else vid_client

    monkeypatch.setattr(test_runs_router, "get_comfyui_client", fake_get_client)

    client = TestClient(app)
    resp = client.post(
        "/tests/run",
        json={"script": "Hello world", "language": "en"},
    )
    assert resp.status_code == 200

    data = resp.json()
    assert "guid" in data
    assert "output_dir" in data
    assert data["scene_prompts"][0]["image_prompt"] == "img prompt 1"

    out_dir = Path(data["output_dir"])
    assert out_dir.exists()

    # voiceover metadata should be written (but no voiceover mp3)
    meta = json.loads((out_dir / "voiceover_metadata.json").read_text(encoding="utf-8"))
    assert "audio_duration" in meta

    image_files = [Path(p) for p in data["image_files"]]
    video_files = [Path(p) for p in data["video_files"]]

    assert len(image_files) == 2
    assert len(video_files) == 2

    assert all(p.exists() for p in image_files)
    assert all(p.exists() for p in video_files)

    # ensure unique naming pattern and correct folder placement
    assert all(str(p).startswith(str(out_dir)) for p in image_files + video_files)
    assert len({p.name for p in image_files + video_files}) == 4

    assert recorded["image_style"] == "cinematic"
