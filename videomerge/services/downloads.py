from pathlib import Path
from fastapi import HTTPException
import shutil
import requests


def is_url(s: str) -> bool:
    return s.lower().startswith("http://") or s.lower().startswith("https://")


def download_to_path(url: str, file_path: Path) -> None:
    """Download a file from URL to the specified path (no strict content-type enforcement)."""
    try:
        with requests.get(url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(file_path, 'wb') as f:
                for chunk in r.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download from URL {url}: {str(e)}")


def download_video(url: str, file_path: Path) -> None:
    """Download video from URL to specified path with simple content-type check."""
    try:
        response = requests.get(url, stream=True, timeout=30)
        response.raise_for_status()
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('video/'):
            raise HTTPException(status_code=400, detail=f"URL does not point to a video file. Content-Type: {content_type}")
        with open(file_path, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
    except requests.RequestException as e:
        raise HTTPException(status_code=400, detail=f"Failed to download video from URL: {str(e)}")


def obtain_source_to_path(src: str, dest_path: Path) -> None:
    """Copy from local path or download from URL into dest_path."""
    try:
        if is_url(src):
            download_to_path(src, dest_path)
        else:
            source_path = Path(src)
            if not source_path.exists():
                raise HTTPException(status_code=400, detail=f"Source path does not exist: {src}")
            shutil.copyfile(source_path, dest_path)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to obtain source '{src}': {str(e)}")
