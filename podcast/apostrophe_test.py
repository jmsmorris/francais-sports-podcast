"""A/B test: how the voice reads French elisions (l'équipe, c'est ...) with different input styles.

Renders the same sentences several ways, saves MP3s to samples/, and measures pauses *inside* each
clip (a gap in the middle of a clip is a stumble; the sentence edges are trimmed first).
"""
import json
import os
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor
import wave
from pathlib import Path

from . import config, tts

SENTENCES = [
    "L'équipe a gagné hier soir.",
    "C'est le temps de jeu en plus.",
    "Il a dit qu'il était content de l'équipe.",
    "J'ai vu que c'est important d'abord.",
    "Elle s'est blessée, mais ce n'est pas grave.",
    "C'est l'équipe de l'Alberta qui l'a emporté.",
    "Le Canadien a gagné hier soir contre Toronto.",  # control: no apostrophes, expect no pauses
]


def curly(s): return s.replace("'", "’")
def modifier(s): return s.replace("'", "ʼ")
def spaced(s): return re.sub(r"(?<=\b[lcjdnmstLCJDNMST])'|(?<=\bqu)'", "' ", s)
def same(s): return s
def joiner(s): return s.replace("'", "\u02bc\u2060")


# name: (text transform, speaking rate, slow-down factor applied after synthesis)
VARIANTS = {
    "a_straight_rate085": (same, 0.85, None),
    "c_modifier_rate085": (modifier, 0.85, None),
    "e_straight_rate100": (same, 1.0, None),
    "h_modifier_rate100": (modifier, 1.0, None),
    "i_modifier_rate090": (modifier, 0.9, None),
    "j_modifier_joiner_rate085": (joiner, 0.85, None),
    "k_modifier_rate100_slowed": (modifier, 1.0, 0.85),
}


def slow(pcm: bytes, factor: float) -> bytes:
    """Time-stretch (keeps pitch) with ffmpeg's atempo."""
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(config.SAMPLE_RATE), "-ac", "1",
                        "-i", "-", "-af", f"atempo={factor}", "-f", "s16le", "-ar", str(config.SAMPLE_RATE),
                        "-ac", "1", "-"], input=pcm, capture_output=True, check=True)
    return r.stdout


def inner_gaps(pcm: bytes, win_ms=10, quiet=250, min_ms=70) -> list[int]:
    """Lengths (ms) of silent runs inside the clip, after trimming its edges."""
    pcm = tts._trim(pcm, keep=0)
    s = memoryview(pcm).cast("h")
    w = int(config.SAMPLE_RATE * win_ms / 1000)
    runs, cur = [], 0
    for i in range(0, len(s) - w, w):
        peak = max(abs(x) for x in s[i:i + w])
        if peak < quiet:
            cur += win_ms
        else:
            if cur >= min_ms:
                runs.append(cur)
            cur = 0
    return runs


SCRIPT_FILE = os.environ.get("SCRIPT_FILE")
if SCRIPT_FILE:  # real-data check: sentences with elisions from an actual script, compared across variants
    script = json.loads(Path(SCRIPT_FILE).read_text())
    allsent = [x for g in script["segments"] for p in g["paragraphs"] for x in tts.split_sentences(p)]
    SENTENCES = [x for x in allsent if "'" in x][:70]
    VARIANTS = {k: VARIANTS[k] for k in ("a_straight_rate085", "c_modifier_rate085", "i_modifier_rate090", "h_modifier_rate100")}
    print(f"real script: {len(SENTENCES)} sentences with elisions")
    for name, (fn, rate, factor) in VARIANTS.items():
        with ThreadPoolExecutor(max_workers=6) as pool:
            clips = list(pool.map(lambda x: tts.synth(fn(x), rate=rate, clean=False), SENTENCES))
        per = [len(inner_gaps(c)) for c in clips]
        wpm = sum(len(x.split()) for x in SENTENCES) / (sum(len(tts._trim(c, keep=0)) for c in clips) / tts.BYTES_PER_SEC / 60)
        print(f"{name:26s} mid-sentence pauses: {sum(per):3d} in {sum(1 for n in per if n):2d}/{len(per)} sentences   speech {wpm:5.1f} wpm")
    raise SystemExit

out = Path("samples")
out.mkdir(exist_ok=True)
print(f"voice={config.VOICE_NAME}")
for name, (fn, rate, factor) in VARIANTS.items():
    pcm = bytearray()
    total_gaps, total_ms, n_gaps, detail = 0, 0.0, 0, []
    for sent in SENTENCES:
        clip = tts.synth(fn(sent), rate=rate, clean=False)
        if factor:
            clip = slow(clip, factor)
        gaps = inner_gaps(clip)
        detail.append(len(gaps))
        n_gaps += len(gaps)
        total_gaps += sum(gaps)
        total_ms += len(tts._trim(clip, keep=0)) / tts.BYTES_PER_SEC * 1000
        pcm += tts._trim(clip) + tts._silence(0.9)
    print(f"{name:28s} mid-sentence pauses: {n_gaps:2d} ({total_gaps:4d} ms)   speech {total_ms / 1000:5.1f} s  per sentence {detail}")
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE); w.writeframes(bytes(pcm))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(wav.with_suffix(".mp3"))],
                   check=True)
    wav.unlink()
