"""Listening samples: ways to make the voice say l'équipe / c'est cleanly. Writes samples/*.mp3."""
import re
import subprocess
import wave
from pathlib import Path

from . import config, tts

SENTENCES = [
    "L'équipe a gagné hier soir.",
    "C'est un très bon match.",
    "C'est la meilleure équipe de la ligue.",
    "Le Canadien dit que c'est l'équipe qui compte.",
    "Il dit qu'il veut gagner.",
    "Qu'est-ce qui s'est passé hier soir?",
    "C'était l'épisode d'hier, et ce n'est pas fini.",
]

# Quebec French IPA for the most common elisions in the scripts (c'est alone is 1 word in 80).
IPA = {"c'est": "sɛ", "l'équipe": "lekip", "s'est": "sɛ", "qu'il": "kil", "n'est": "nɛ", "c'était": "setɛ",
       "l'épisode": "lepizɔd", "d'hier": "djɛʁ", "qu'elle": "kɛl"}
CUSTOM = {"customPronunciations": {"pronunciations": [
    {"phrase": ph if i == 0 else ph.capitalize(), "phoneticEncoding": "PHONETIC_ENCODING_IPA", "pronunciation": ipa}
    for ph, ipa in IPA.items() for i in (0, 1)]}}
RESPELL = {"c'est": "cè", "l'équipe": "léquipe", "s'est": "sè", "qu'il": "quil", "n'est": "nè", "c'était": "cétait",
           "l'épisode": "lépisode", "d'hier": "dhier", "qu'elle": "quelle"}


def respell(s):
    for k, v in RESPELL.items():
        s = re.sub(re.escape(k), v, s, flags=re.I)
    return s


def slow(pcm: bytes, factor: float) -> bytes:
    r = subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "s16le", "-ar", str(config.SAMPLE_RATE), "-ac", "1",
                        "-i", "-", "-af", f"atempo={factor}", "-f", "s16le", "-ar", str(config.SAMPLE_RATE),
                        "-ac", "1", "-"], input=pcm, capture_output=True, check=True)
    return r.stdout


MOD = lambda s: s.replace("'", "ʼ")
# name: (text transform, rate, extra SynthesisInput fields, slow-down factor)
VARIANTS = {
    "1_current_straight_apostrophe": (lambda s: s, 0.85, None, None),
    "2_modifier_apostrophe": (MOD, 0.85, None, None),
    "3_modifier_apostrophe_faster_voice_then_slowed": (MOD, 1.0, None, 0.85),
    "4_phonetic_pronunciations_IPA": (lambda s: s, 0.85, CUSTOM, None),
    "5_respelled_without_apostrophe": (respell, 0.85, None, None),
}

out = Path("samples")
out.mkdir(exist_ok=True)
for name, (fn, rate, extra, factor) in VARIANTS.items():
    try:
        pcm = bytearray()
        for sent in SENTENCES:
            clip = tts.synth(fn(sent), rate=rate, clean=False, extra_input=extra)
            if factor:
                clip = slow(clip, factor)
            pcm += tts._silence(0.2) + tts._trim(clip) + tts._silence(1.0)
    except Exception as e:  # noqa: BLE001
        print(f"{name}: FAILED {str(e)[:300]}")
        continue
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE); w.writeframes(bytes(pcm))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(wav.with_suffix(".mp3"))], check=True)
    wav.unlink()
    print(f"{name}: wrote {len(pcm) / tts.BYTES_PER_SEC:.1f} s")
