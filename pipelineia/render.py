"""Montage FFmpeg de cartes originales et de sous-titres, sans API visuelle payante."""

from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import subprocess
import wave
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image, ImageDraw, ImageFont

from .speech import ffmpeg_binary
from .alignment import aligned_timeline

LOGGER = logging.getLogger(__name__)
DEFAULT_FORMATS = {"vertical": {"width": 1080, "height": 1920},
                   "square": {"width": 1080, "height": 1080},
                   "landscape": {"width": 1920, "height": 1080}}


def audio_duration(path: Path) -> float:
    """Mesure la durée WAV ou d'un format reconnu par FFmpeg."""
    try:
        with wave.open(str(path)) as audio:
            return audio.getnframes() / audio.getframerate()
    except (wave.Error, EOFError):
        result = subprocess.run([ffmpeg_binary(), "-hide_banner", "-i", str(path)],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=30)
        match = re.search(r"Duration: (\d+):(\d+):(\d+(?:\.\d+)?)", result.stderr)
        if not match:
            raise ValueError("Impossible de mesurer la durée de narration.")
        return int(match[1]) * 3600 + int(match[2]) * 60 + float(match[3])


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Charge une police système lisible, y compris sous Windows."""
    names = ["DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf",
             "C:/Windows/Fonts/arialbd.ttf" if bold else "C:/Windows/Fonts/arial.ttf",
             "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
             "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
    for name in names:
        try:
            return ImageFont.truetype(name, size=size)
        except OSError:
            continue
    return ImageFont.load_default(size=size)


def _wrap(text: str, font: ImageFont.FreeTypeFont, width: int) -> str:
    """Répartit des mots sans dépasser la zone de texte."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        candidate = f"{line} {word}".strip()
        if font.getlength(candidate) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return "\n".join(lines)


def _fit(text: str, width: int, max_height: int, initial: int, bold: bool = False) -> tuple:
    """Réduit la taille d'un texte long pour préserver la mise en page."""
    initial = max(8, initial)
    for size in range(initial, max(4, initial // 3) - 1, -1):
        font = _font(size, bold)
        wrapped = _wrap(text, font, width)
        spacing = int(size * .25)
        if len(wrapped.splitlines()) * (size + spacing) <= max_height:
            return wrapped, font, spacing
    raise ValueError("Texte trop long pour la carte vidéo; raccourcissez on_screen ou la narration.")


def _card(path: Path, width: int, height: int, script: dict, scene: dict,
          caption: str, index: int, count: int, demo: bool) -> None:
    """Dessine une carte éditoriale, avec marges pour les interfaces sociales."""
    image = Image.new("RGB", (width, height), "#09111f")
    draw = ImageDraw.Draw(image)
    scale = min(width, height) / 1080
    margin = int(width * .09)
    usable = width - margin * 2
    # Trame originale légère : aucune image d'article réutilisée sans licence.
    for x in range(-height, width, max(20, int(110 * scale))):
        draw.line((x, 0, x + height, height), fill="#11263a", width=max(1, int(scale)))
    draw.ellipse((int(width * .57), int(height * .16), int(width * 1.3), int(height * .75)),
                 outline="#1b3c52", width=max(2, int(6 * scale)))
    draw.rounded_rectangle((margin, int(height * .105), margin + int(250 * scale), int(height * .105 + 52 * scale)),
                           radius=int(14 * scale), fill="#6ce9cc")
    draw.text((margin + int(16 * scale), int(height * .105 + 10 * scale)), "ACTU IA / 60 S",
              font=_font(max(12, int(25 * scale)), True), fill="#09111f")
    if script.get("demo") or demo:
        label = "DÉMONSTRATION · PAS UNE ACTUALITÉ"
        if demo:
            label += " · VOIX SILENCIEUSE"
        text, font, spacing = _fit(label, usable, int(height * .06), int(22 * scale), True)
        draw.multiline_text((margin, int(height * .17)), text,
                            font=font, spacing=spacing, fill="#ffbc76")
    headline = script.get("hook", "") if index == 0 else scene.get("on_screen", script.get("title", ""))
    headline = headline or script.get("title", "Actualité IA")
    text, font, spacing = _fit(headline, usable, int(height * .31), int(76 * scale), True)
    draw.multiline_text((margin, int(height * .245)), text, font=font, spacing=spacing, fill="#f3f6ff")
    draw.text((margin, int(height * .58)), f"{index + 1:02d} / {count:02d}",
              font=_font(max(13, int(28 * scale))), fill="#6ce9cc")
    caption_box = (margin - int(20 * scale), int(height * .65), width - margin + int(20 * scale), int(height * .835))
    draw.rounded_rectangle(caption_box, radius=max(4, int(22 * scale)), fill="#172b40")
    text, font, spacing = _fit(caption, usable - int(20 * scale), int(height * .15), int(45 * scale), True)
    draw.multiline_text((margin + int(10 * scale), int(height * .675)), text, font=font,
                        spacing=spacing, fill="white")
    source_ids = set(scene.get("source_ids", []))
    domains = list(dict.fromkeys(urlparse(source.get("url", "")).netloc.removeprefix("www.")
                                for source in script.get("sources", []) if source.get("id") in source_ids))
    attribution = "Sources : " + ", ".join(domains) if domains else "Sources dans la description"
    text, font, spacing = _fit(attribution, usable, int(height * .06), int(23 * scale))
    draw.multiline_text((margin, int(height * .87)), text, font=font, spacing=spacing, fill="#a8b8c9")
    image.save(path)


def _stamp(seconds: float) -> str:
    """Formate un instant au format SRT."""
    millis = round(seconds * 1000)
    return f"{millis // 3600000:02d}:{millis // 60000 % 60:02d}:{millis // 1000 % 60:02d},{millis % 1000:03d}"


def build_timeline(script: dict, speech_seconds: float, duration: float) -> list[dict]:
    """Estime les sous-titres par proportion de mots, sans prétendre à un alignement acoustique."""
    scenes = script.get("scenes", [])
    total_words = sum(len(scene.get("narration", "").split()) for scene in scenes)
    if not scenes or total_words == 0:
        raise ValueError("Le script ne contient aucune narration.")
    timeline: list[dict] = []
    cursor = 0.0
    for index, scene in enumerate(scenes):
        words = scene.get("narration", "").split()
        if not words:
            raise ValueError("Chaque scène doit contenir une narration.")
        for start in range(0, len(words), 9):
            chunk = words[start:start + 9]
            end = cursor + speech_seconds * len(chunk) / total_words
            timeline.append({"start": round(cursor, 4), "end": round(end, 4),
                             "caption": " ".join(chunk), "scene": index})
            cursor = end
    timeline[-1]["end"] = duration
    return timeline


def render_episode(script: dict, audio: Path, output_dir: Path, config: dict,
                   formats: list[str] | None = None) -> dict[str, Path]:
    """Produit des MP4 H.264/AAC de durée exacte avec une voix ajustée sans la couper."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    video = config.get("video", {})
    duration = float(video.get("duration_seconds", 60))
    fps = int(video.get("fps", 30))
    if duration <= 2 or fps <= 0:
        raise ValueError("Durée vidéo et cadence invalides.")
    speech_seconds = duration - 2
    measured = audio_duration(Path(audio))
    tempo = measured / speech_seconds
    if not .65 <= tempo <= 1.45:
        raise ValueError(f"Voix de {measured:.1f}s incompatible avec {duration:.0f}s "
                         "sans accélération excessive; régénérez le script ou ajustez speech.rate.")
    timeline, alignment_status = aligned_timeline(script, Path(audio), measured, speech_seconds, duration)
    method = "elevenlabs_character_alignment" if timeline is not None else "estimated_word_proportions"
    if timeline is None:
        timeline = build_timeline(script, speech_seconds, duration)
    (output_dir / "captions.srt").write_text("\n\n".join(
        f"{i}\n{_stamp(cue['start'])} --> {_stamp(cue['end'])}\n{cue['caption']}"
        for i, cue in enumerate(timeline, 1)) + "\n", encoding="utf-8")
    (output_dir / "timing.json").write_text(json.dumps({"method": method, "alignment_status": alignment_status,
        "input_audio_seconds": measured, "tempo": tempo, "duration_seconds": duration,
        "cues": timeline}, ensure_ascii=False, indent=2), encoding="utf-8")
    available = video.get("formats", DEFAULT_FORMATS)
    selected = formats or list(available)
    if not selected:
        raise ValueError("Sélectionnez au moins un format.")
    unknown = set(selected) - set(available)
    if unknown:
        raise ValueError(f"Formats inconnus : {', '.join(sorted(unknown))}")
    outputs: dict[str, Path] = {}
    for name in selected:
        dimensions = available[name]
        width, height = int(dimensions["width"]), int(dimensions["height"])
        if width < 120 or height < 120 or width % 2 or height % 2:
            raise ValueError("Dimensions vidéo paires d'au moins 120 pixels requises.")
        frames_dir = output_dir / f"frames-{name}"
        frames_dir.mkdir(exist_ok=True)
        concat: list[str] = []
        for i, cue in enumerate(timeline):
            path = frames_dir / f"{i:04d}.png"
            _card(path, width, height, script, script["scenes"][cue["scene"]],
                  cue["caption"], cue["scene"], len(script["scenes"]),
                  config.get("speech", {}).get("provider") == "demo")
            concat.extend([f"file '{path.name}'", f"duration {cue['end'] - cue['start']:.4f}"])
        concat.append(f"file '{len(timeline) - 1:04d}.png'")
        manifest = frames_dir / "concat.txt"
        manifest.write_text("\n".join(concat) + "\n", encoding="utf-8")
        destination = output_dir / f"{name}.mp4"
        progress_height = max(4, int(height * .004))
        command = [ffmpeg_binary(), "-hide_banner", "-loglevel", "error", "-y", "-f", "concat",
                   "-safe", "0", "-i", str(manifest.resolve()), "-i", str(Path(audio).resolve()),
                   "-f", "lavfi", "-i", f"color=c=0x6ce9cc:s={width}x{progress_height}:r={fps}",
                   "-filter_complex",
                   f"[0:v]fps={fps},scale={width}:{height},setsar=1[base];"
                   f"[base][2:v]overlay=x='-overlay_w+main_w*t/{duration}':y=main_h-overlay_h:shortest=1[v];"
                   f"[1:a]atempo={tempo:.8f},apad,atrim=duration={duration},"
                   "loudnorm=I=-16:TP=-1.5:LRA=11[a]",
                   "-map", "[v]", "-map", "[a]", "-t", str(duration), "-c:v", "libx264",
                   "-preset", str(video.get("preset", "veryfast")), "-crf", str(video.get("crf", 23)),
                   "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "128k", "-ar", "48000",
                   "-movflags", "+faststart", str(destination.resolve())]
        result = subprocess.run(command, capture_output=True, text=True, encoding="utf-8",
                                errors="replace", timeout=int(video.get("render_timeout_seconds", 900)))
        if result.returncode:
            destination.unlink(missing_ok=True)
            raise RuntimeError(f"Échec FFmpeg : {result.stderr[-2000:]}")
        shutil.copyfile(frames_dir / "0000.png", output_dir / f"{name}-cover.png")
        outputs[name] = destination
        LOGGER.info("Vidéo %s créée : %s", name, destination)
    return outputs


def main() -> None:
    """Monte un épisode à partir du script JSON et d'une narration audio."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("script", type=Path)
    parser.add_argument("audio", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--config", type=Path, default=Path("config.yaml"))
    args = parser.parse_args()
    import yaml

    render_episode(json.loads(args.script.read_text(encoding="utf-8")), args.audio, args.output,
                   yaml.safe_load(args.config.read_text(encoding="utf-8")))


if __name__ == "__main__":
    main()
