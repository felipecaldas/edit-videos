import json
import subprocess
from pathlib import Path
from typing import List, Optional
from fastapi import HTTPException
from faster_whisper import WhisperModel

from videomerge.config import SUBTITLE_CONFIG_PATH


def load_subtitle_config() -> dict:
    defaults = {
        "font_name": "DejaVu Sans",
        "font_size": 22,
        "bold": 1,
        "outline": 2,
        "shadow": 1,
        "primary_colour_ass": "&H0000FFFF",
        "outline_colour_ass": "&H00000000",
        "margin_v": 80,
        "margin_top": 100,
        "margin_bottom": 100,
        "margin_middle": 80,
    }
    try:
        if SUBTITLE_CONFIG_PATH.exists():
            with open(SUBTITLE_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict):
                    defaults.update(data)
    except Exception:
        # Fallback to defaults silently; logging handled by caller
        pass
    return defaults


def _format_timestamp_srt(seconds: float) -> str:
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    ms = int((seconds - int(seconds)) * 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def write_srt_from_chunks(chunks, out_path: Path) -> None:
    with open(out_path, "w", encoding="utf-8") as f:
        for i, c in enumerate(chunks, start=1):
            start = _format_timestamp_srt(c["start"])
            end = _format_timestamp_srt(c["end"])
            text = (c["text"] or "").strip()
            f.write(f"{i}\n{start} --> {end}\n{text}\n\n")


def run_whisper_segments(input_path: Path, language: str = "pt", model_size: str = "small"):
    model = WhisperModel(model_size, device="cpu", compute_type="int8")
    segments, _info = model.transcribe(
        str(input_path),
        language=language,
        task="transcribe",
        vad_filter=True,
        word_timestamps=True,
    )
    return list(segments)


def _clean_chunk_text(tokens: List[str], is_last_in_segment: bool) -> str:
    cleaned = [t.strip().strip('\"\'\u201c\u201d\u2018\u2019') for t in tokens]
    text = " ".join(cleaned)
    text = " ".join(text.split())
    if not is_last_in_segment:
        while len(text) > 0 and text[-1] in ",.;:!?…":
            text = text[:-1].rstrip()
    return text


def build_chunks_from_words(segments, max_words: int = 4, min_chunk_duration: float = 0.6):
    chunks = []
    for seg in segments:
        words = getattr(seg, "words", None)
        if not words:
            tokens = (seg.text or "").split()
            if not tokens:
                continue
            total = len(tokens)
            start = float(seg.start or 0.0)
            seg_dur = max(0.0, float(seg.end or start) - start)
            i = 0
            while i < total:
                group = tokens[i:i+max_words]
                frac = len(group) / total
                end = start + seg_dur * frac
                if len(group) >= 3:
                    left = group[:2]
                    right = group[2:]
                    is_last = (i + len(group)) >= total
                    left_text = _clean_chunk_text(left, False)
                    right_text = _clean_chunk_text(right, is_last)
                    text = f"{left_text}\n{right_text}".strip()
                else:
                    text = _clean_chunk_text(group, (i + len(group)) >= total)
                chunks.append({"start": start, "end": end, "text": text})
                start = end
                i += len(group)
            continue
        i = 0
        n = len(words)
        while i < n:
            j = min(i + max_words, n)
            group = words[i:j]
            start = float(group[0].start)
            end = float(group[-1].end)
            while (end - start) < min_chunk_duration and j < n:
                j += 1
                group = words[i:j]
                end = float(group[-1].end)
            raw_tokens = [w.word.strip() for w in group]
            if len(raw_tokens) >= 3:
                left = raw_tokens[:2]
                right = raw_tokens[2:]
                is_last = (j >= n)
                left_text = _clean_chunk_text(left, False)
                right_text = _clean_chunk_text(right, is_last)
                text = f"{left_text}\n{right_text}".strip()
            else:
                text = _clean_chunk_text(raw_tokens, (j >= n))
            chunks.append({"start": start, "end": end, "text": text})
            i = j
    return chunks


def _alignment_for_position(pos: str) -> int:
    p = (pos or "bottom").lower()
    if p == "top":
        return 8
    if p == "middle":
        return 5
    return 2


def burn_subtitles(input_video: Path, srt_path: Path, output_path: Path, position: str, margin_v: Optional[int] = None):
    alignment = _alignment_for_position(position)
    cfg = load_subtitle_config()
    if margin_v is not None:
        mv = margin_v
    else:
        pos = (position or "bottom").lower()
        if pos == "top":
            mv = cfg.get("margin_top", cfg.get("margin_v", 80))
        elif pos == "middle":
            mv = cfg.get("margin_middle", cfg.get("margin_v", 80))
        else:
            mv = cfg.get("margin_bottom", cfg.get("margin_v", 80))
    font_name = cfg.get("font_name", "DejaVu Sans")
    font_size = cfg.get("font_size", 22)
    bold = cfg.get("bold", 1)
    outline = cfg.get("outline", 2)
    shadow = cfg.get("shadow", 1)
    primary = cfg.get("primary_colour_ass", "&H0000FFFF")
    outline_col = cfg.get("outline_colour_ass", "&H00000000")

    style = (
        f"Alignment={alignment},MarginV={mv},FontName={font_name},"
        f"FontSize={font_size},Bold={bold},Outline={outline},Shadow={shadow},"
        f"PrimaryColour={primary},OutlineColour={outline_col}"
    )
    sub_filter = f"subtitles='{srt_path.resolve().as_posix()}':force_style='{style}'"
    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error', '-y',
        '-i', str(input_video),
        '-vf', sub_filter,
        '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '23',
        '-c:a', 'aac',
        '-movflags', '+faststart',
        str(output_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HTTPException(status_code=500, detail=f"FFmpeg burn-in error: {result.stderr}")
