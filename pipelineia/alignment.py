"""Sous-titres fondés sur les repères audio, sans confondre texte et normalisation."""
import hashlib
import json
import math
import re
from pathlib import Path


def aligned_timeline(script: dict, audio: Path, measured: float,
                     speech_seconds: float, duration: float) -> tuple[list[dict] | None, str]:
    """Vérifie le fichier et adapte les temps ElevenLabs au tempo du montage."""
    path = Path(audio).with_suffix(".alignment.json")
    if not path.is_file():
        return None, "missing"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict) or data.get("provider") != "elevenlabs":
            return None, "invalid"
        scenes = script["scenes"]
        text = " ".join(scene["narration"] for scene in scenes)
        alignment = data["alignment"]
        chars = alignment["characters"]
        starts = alignment["character_start_times_seconds"]
        ends = alignment["character_end_times_seconds"]
        if not all(isinstance(value, list) for value in (chars, starts, ends)):
            return None, "invalid"
        if not chars or len(chars) != len(starts) or len(chars) != len(ends):
            return None, "invalid"
        if not all(isinstance(char, str) and char for char in chars):
            return None, "invalid"
        if data.get("text") != text or "".join(chars) != text:
            return None, "text_mismatch"
        digest = hashlib.sha256()
        with Path(audio).open("rb") as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(block)
        if data.get("audio_sha256") != digest.hexdigest():
            return None, "audio_mismatch"
        if any(isinstance(t, bool) or not isinstance(t, (float, int)) or not math.isfinite(t) or t < 0 for t in starts + ends):
            return None, "invalid_times"
        if any(end < start for start, end in zip(starts, ends)):
            return None, "invalid_times"
        if any(a > b for values in (starts, ends) for a, b in zip(values, values[1:])):
            return None, "invalid_times"
        if ends[-1] > measured + .1 or measured <= 0 or speech_seconds <= 0:
            return None, "invalid_times"
        # Certains alignements regroupent plusieurs points Unicode par élément.
        char_starts = [start for char, start in zip(chars, starts) for _ in char]
        scale = speech_seconds / measured
        timeline = []
        offset = 0
        for index, scene in enumerate(scenes):
            words = list(re.finditer(r"\S+", scene["narration"]))
            for chunk_start in range(0, len(words), 9):
                chunk = words[chunk_start:chunk_start + 9]
                start = round(char_starts[offset + chunk[0].start()] * scale, 4)
                timeline.append({"start": start, "caption": " ".join(word.group() for word in chunk), "scene": index})
            offset += len(scene["narration"]) + 1
        if not timeline:
            return None, "invalid"
        timeline[0]["start"] = 0.0
        for index, cue in enumerate(timeline):
            cue["end"] = timeline[index + 1]["start"] if index + 1 < len(timeline) else duration
            if cue["end"] <= cue["start"] or cue["end"] > duration:
                return None, "invalid_times"
        return timeline, "verified"
    except (ValueError, TypeError, KeyError, IndexError, OSError, AttributeError):
        return None, "invalid"
