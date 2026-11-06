"""Google Cloud Text-to-Speech, one sentence at a time, with paced pauses.

Each sentence is synthesized separately so we know exactly how long the speech is.
The pauses between sentences are then sized so the episode averages TARGET_WPM
(and never more than MAX_WPM) — slow, with breathing room after every sentence.
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

    words = sum(len(re.findall(r"\w+(?:['’]\w+)?", u[0])) for u in units)
    speech_sec = sum(len(c) for c in clips) / BYTES_PER_SEC
    speech_wpm = words / (speech_sec / 60)

    # Gaps are weighted: sentence 1x, paragraph 2x, segment 3.5x.
    weights = {"sentence": 1.0, "paragraph": 2.0, "segment": 3.5, "end": 0.0}
    total_weight = sum(weights[g] for _, g in units)
    target_total = words / config.TARGET_WPM * 60
    target_total = min(max(target_total, config.MIN_MINUTES * 60 + 30), config.MAX_MINUTES * 60 - 30)
    base_gap = (target_total - speech_sec) / total_weight if total_weight else 0
    base_gap = min(max(base_gap, 0.45), 1.8)  # keep it natural: never rushed, never awkward

    pcm = bytearray(_silence(0.8))
    for clip, (_, gap) in zip(clips, units):
        pcm += clip
        pcm += _silence(base_gap * weights[gap])
    pcm += _silence(1.5)
    total_sec = len(pcm) / BYTES_PER_SEC
    stats = {
        "words": words, "sentences": len(units), "speech_seconds": round(speech_sec, 1),
        "speech_wpm": round(speech_wpm, 1), "gap_seconds": round(base_gap, 2),
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
    """Render, slowing the voice itself if pauses alone can't meet the WPM ceiling."""
    rate = config.SPEAKING_RATE
    for _ in range(3):
        stats = render(script, out_mp3, rate)
        print("Audio:", stats)
        if stats["average_wpm"] <= config.MAX_WPM:
            return stats
        rate = round(rate * config.TARGET_WPM / stats["average_wpm"], 2)
        rate = max(rate, 0.7)
    return stats
