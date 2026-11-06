"""Google Cloud Text-to-Speech, one sentence at a time, with paced pauses.

Each sentence is synthesized separately, its built-in silence trimmed, and fixed
pauses (config.PAUSE_*) inserted, so the voice keeps its natural speed and the
pauses are exactly as long as configured.
"""
from __future__ import annotations

import base64
import io
import os
import re
import subprocess
import time
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests

from . import config

API = "https://texttospeech.googleapis.com/v1/text:synthesize"
BYTES_PER_SEC = config.SAMPLE_RATE * 2  # 16-bit mono


def split_sentences(paragraph: str) -> list[str]:
    parts = re.split(r"(?<=[.!?…»])\s+(?=[A-ZÀ-ÖØ-Þ«0-9])", paragraph.strip())
    return [p.strip() for p in parts if p.strip()]


def synth(text: str, voice: str = config.VOICE_NAME, rate: float = config.SPEAKING_RATE) -> bytes:
    """Return raw 16-bit mono PCM for one sentence."""
    body = {
        "input": {"text": text},
        "voice": {"languageCode": config.VOICE_LANGUAGE, "name": voice},
        "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": config.SAMPLE_RATE,
                        "speakingRate": rate},
    }
    headers = {"X-Goog-Api-Key": os.environ["GOOGLE_TTS_API_KEY"]}
    for attempt in range(5):
        r = requests.post(API, json=body, headers=headers, timeout=60)
        if r.status_code == 200:
            with wave.open(io.BytesIO(base64.b64decode(r.json()["audioContent"]))) as w:
                return w.readframes(w.getnframes())
        if r.status_code in (429, 500, 502, 503, 504) and attempt < 4:
            time.sleep(2 ** attempt)
            continue
        raise RuntimeError(f"Google TTS error {r.status_code}: {r.text[:500]}")
    raise RuntimeError("unreachable")


def _silence(seconds: float) -> bytes:
    return b"\x00\x00" * int(seconds * config.SAMPLE_RATE)


def _trim(pcm: bytes, threshold: int = 300, keep: float = 0.05) -> bytes:
    """Cut leading/trailing near-silence from 16-bit mono PCM, keeping a 50 ms cushion."""
    samples = memoryview(pcm).cast("h")
    n = len(samples)
    start = next((i for i in range(n) if abs(samples[i]) > threshold), 0)
    end = next((i for i in range(n - 1, -1, -1) if abs(samples[i]) > threshold), n - 1)
    pad = int(keep * config.SAMPLE_RATE)
    return bytes(pcm[max(0, start - pad) * 2: min(n, end + 1 + pad) * 2])


def render(script: dict, out_mp3: Path, rate: float = config.SPEAKING_RATE) -> dict:
    """Synthesize the whole script; return timing stats."""
    # Flatten into (sentence, gap_type) where gap_type is what follows the sentence.
    units: list[tuple[str, str]] = []
    for si, seg in enumerate(script["segments"]):
        paras = [p for p in seg["paragraphs"] if p.strip()]
        for pi, para in enumerate(paras):
            sents = split_sentences(para)
            for i, s in enumerate(sents):
                last_sent = i == len(sents) - 1
                last_para = pi == len(paras) - 1
                gap = "segment" if (last_sent and last_para) else "paragraph" if last_sent else "sentence"
                units.append((s, gap))
    units[-1] = (units[-1][0], "end")

    with ThreadPoolExecutor(max_workers=6) as pool:
        clips = list(pool.map(lambda u: synth(u[0], rate=rate), units))

    # Google pads each clip with its own silence; trim it so the pauses below are exactly what you hear.
    clips = [_trim(c) for c in clips]
    words = sum(len(re.findall(r"\w+(?:['’]\w+)?", u[0])) for u in units)
    speech_sec = sum(len(c) for c in clips) / BYTES_PER_SEC
    speech_wpm = words / (speech_sec / 60)

    pauses = {"sentence": config.PAUSE_SENTENCE, "paragraph": config.PAUSE_PARAGRAPH,
              "segment": config.PAUSE_SEGMENT, "end": 0.0}
    pcm = bytearray(_silence(0.8))
    for clip, (_, gap) in zip(clips, units):
        pcm += clip
        pcm += _silence(pauses[gap])
    pcm += _silence(1.5)
    total_sec = len(pcm) / BYTES_PER_SEC
    stats = {
        "words": words, "sentences": len(units), "speech_seconds": round(speech_sec, 1),
        "speech_wpm": round(speech_wpm, 1), "sentence_pause": config.PAUSE_SENTENCE,
        "duration_seconds": round(total_sec, 1), "average_wpm": round(words / (total_sec / 60), 1),
        "voice": config.VOICE_NAME, "speaking_rate": rate,
    }

    wav_path = out_mp3.with_suffix(".wav")
    with wave.open(str(wav_path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(config.SAMPLE_RATE)
        w.writeframes(bytes(pcm))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav_path),
                    "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ac", "1",
                    "-b:a", config.MP3_BITRATE, str(out_mp3)], check=True)
    wav_path.unlink()
    return stats


def render_paced(script: dict, out_mp3: Path) -> dict:
    """Render at the fixed voice speed and fixed pauses (no automatic slowing)."""
    stats = render(script, out_mp3, config.SPEAKING_RATE)
    print("Audio:", stats)
    return stats
