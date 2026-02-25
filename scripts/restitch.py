"""
Re-run the stitch + subtitle pipeline for an existing run_id.

Usage (from inside the container):
    python scripts/restitch.py <run_id> [--speed 1.2] [--language en]

Example:
    python scripts/restitch.py bbJhrrdSyPjr
    python scripts/restitch.py bbJhrrdSyPjr --speed 1.2 --language en
"""
import argparse
import sys
from pathlib import Path

# Ensure the project root is on sys.path so videomerge imports work
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from videomerge.config import DATA_SHARED_BASE, VIDEO_SPEED_FACTOR
from videomerge.services.stitcher import concat_videos_with_voiceover, generate_and_burn_subtitles
from videomerge.utils.logging import get_logger

logger = get_logger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Re-stitch clips and burn subtitles for a run_id.")
    parser.add_argument("run_id", help="The run ID to process (e.g. bbJhrrdSyPjr)")
    parser.add_argument("--speed", type=float, default=None,
                        help="Video speed factor (default: VIDEO_SPEED_FACTOR from .env)")
    parser.add_argument("--language", default="en",
                        help="Subtitle language passed to Whisper (default: en)")
    args = parser.parse_args()

    speed = args.speed if args.speed is not None else float(VIDEO_SPEED_FACTOR)
    run_dir = Path(DATA_SHARED_BASE) / args.run_id

    if not run_dir.exists():
        logger.error("Run directory not found: %s", run_dir)
        sys.exit(1)

    voiceover_path = run_dir / "voiceover.mp3"
    if not voiceover_path.exists():
        logger.error("voiceover.mp3 not found in %s", run_dir)
        sys.exit(1)

    # Collect all numbered video clips (000_*.mp4 ... NNN_*.mp4), sorted by prefix
    video_paths = sorted(
        [p for p in run_dir.glob("*.mp4") if p.stem.split("_")[0].isdigit()],
        key=lambda p: int(p.stem.split("_")[0]),
    )
    if not video_paths:
        logger.error("No numbered video clips found in %s", run_dir)
        sys.exit(1)

    logger.info("Found %d clips for run_id=%s (speed=%.2fx, language=%s)",
                len(video_paths), args.run_id, speed, args.language)
    for p in video_paths:
        logger.info("  %s", p.name)

    stitched_path = run_dir / "stitched_output.mp4"
    final_path = run_dir / "final_video.mp4"

    logger.info("Stitching clips...")
    concat_videos_with_voiceover(
        video_paths,
        voiceover_path,
        stitched_path,
        video_speed_factor=speed,
    )
    logger.info("Stitched output: %s (%.1f MB)", stitched_path, stitched_path.stat().st_size / 1_000_000)

    logger.info("Generating subtitles and burning into final video...")
    generate_and_burn_subtitles(
        stitched_path,
        final_path,
        language=args.language,
        audio_hint=voiceover_path,
    )
    logger.info("Done! Final video: %s (%.1f MB)", final_path, final_path.stat().st_size / 1_000_000)


if __name__ == "__main__":
    main()
