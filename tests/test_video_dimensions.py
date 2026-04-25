"""Unit tests for videomerge.utils.video_dimensions."""

from __future__ import annotations

import pytest

from videomerge.utils.video_dimensions import (
    calculate_image_dimensions,
    calculate_video_dimensions,
)


# ──────────────────────────────────────────────────────────────────────────────
# calculate_video_dimensions — no cap, all 9 combinations
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("video_format", "target_resolution", "expected"),
    [
        ("9:16", "480p", (480, 854)),
        ("9:16", "720p", (720, 1280)),
        ("9:16", "1080p", (1080, 1920)),
        ("16:9", "480p", (854, 480)),
        ("16:9", "720p", (1280, 720)),
        ("16:9", "1080p", (1920, 1080)),
        ("1:1", "480p", (480, 480)),
        ("1:1", "720p", (720, 720)),
        ("1:1", "1080p", (1080, 1080)),
    ],
)
def test_calculate_video_dimensions_all_combinations(
    video_format: str, target_resolution: str, expected: tuple[int, int]
) -> None:
    assert calculate_video_dimensions(video_format, target_resolution) == expected


def test_calculate_video_dimensions_rejects_unsupported_format() -> None:
    with pytest.raises(ValueError, match="Unsupported video_format"):
        calculate_video_dimensions("4:5", "720p")


def test_calculate_video_dimensions_rejects_unsupported_resolution() -> None:
    with pytest.raises(ValueError, match="Unsupported target_resolution"):
        calculate_video_dimensions("9:16", "2160p")


# ──────────────────────────────────────────────────────────────────────────────
# calculate_image_dimensions — same table but with 720p cap
# ──────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    ("video_format", "target_resolution", "expected"),
    [
        # At or below 720p → returned as-is
        ("9:16", "480p", (480, 854)),
        ("9:16", "720p", (720, 1280)),
        ("16:9", "480p", (854, 480)),
        ("16:9", "720p", (1280, 720)),
        ("1:1", "480p", (480, 480)),
        ("1:1", "720p", (720, 720)),
        # 1080p entries must be capped to the 720p value (orientation preserved)
        ("9:16", "1080p", (720, 1280)),
        ("16:9", "1080p", (1280, 720)),
        ("1:1", "1080p", (720, 720)),
    ],
)
def test_calculate_image_dimensions_caps_at_720p(
    video_format: str, target_resolution: str, expected: tuple[int, int]
) -> None:
    assert calculate_image_dimensions(video_format, target_resolution) == expected


def test_calculate_image_dimensions_defaults_when_both_none() -> None:
    # None inputs → defaults to 9:16 / 720p
    assert calculate_image_dimensions(None, None) == (720, 1280)


def test_calculate_image_dimensions_defaults_when_format_invalid() -> None:
    # Invalid format falls back to 9:16
    assert calculate_image_dimensions("4:5", "720p") == (720, 1280)


def test_calculate_image_dimensions_defaults_when_resolution_invalid() -> None:
    # Invalid resolution falls back to 720p
    assert calculate_image_dimensions("9:16", "2160p") == (720, 1280)


def test_calculate_image_dimensions_defaults_when_both_invalid() -> None:
    assert calculate_image_dimensions("garbage", "garbage") == (720, 1280)


def test_calculate_image_dimensions_caps_landscape_1080p() -> None:
    # Sanity: a landscape 1080p request should not silently become portrait
    w, h = calculate_image_dimensions("16:9", "1080p")
    assert w > h  # still landscape
    assert (w, h) == (1280, 720)
