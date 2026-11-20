"""A/B test: do French elisions (l'équipe, c'est ...) make the voice stumble? Which input style helps?

Short comma-free sentences, each with exactly one elision, plus control sentences with none. A "stumble"
is a silent gap of 70 ms or more inside a sentence (edges trimmed). The controls show the false-positive rate.
"""
import os
import subprocess
import wave
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import config, tts

ELISION = [
    "L'équipe a gagné hier soir.", "C'est un très bon match.", "L'entraîneur est content du résultat.",
    "Il dit qu'il veut gagner.", "Elle s'est blessée au genou.", "Ce n'est pas grave du tout.",
    "Le gardien a fait l'arrêt.", "Nous avons vu l'équipe jouer.", "C'est la meilleure équipe de la ligue.",
    "L'attaquant a marqué deux buts.", "Il n'a pas joué hier soir.", "Voici l'histoire du match.",
    "J'ai regardé le match hier.", "C'est quand le match commence.", "L'Alberta a battu le Manitoba.",
    "On s'attend à un match serré.", "L'Impact joue samedi soir.", "Qu'est-ce qui s'est passé.",
    "D'abord le hockey puis le baseball.", "L'équipe canadienne a gagné la médaille.",
    "C'est le temps de jeu en plus.", "L'entraîneur a parlé de l'équipe.", "Le Canadien n'a pas gagné hier.",
    "C'est une bonne nouvelle pour l'équipe.",
]
CONTROL = [
    "Le Canadien a gagné hier soir.", "Le match commence samedi soir.", "Le gardien a fait un bel arrêt.",
    "Nous avons vu les Oilers jouer.", "Le hockey est un sport rapide.", "Les Jets ont battu les Flames.",
    "Cette équipe joue très bien.", "Le lanceur a retiré dix frappeurs.", "Montréal reçoit Toronto samedi.",
    "La rondelle a frappé le poteau.", "Tout le monde attend le match.", "Cette histoire est incroyable.",
]


def modifier(s): return s.replace("'", "ʼ")
def same(s): return s


# name: (text transform, speaking rate)
VARIANTS = {
    "a_straight_rate085": (same, 0.85),
    "c_modifier_rate085": (modifier, 0.85),
    "i_modifier_rate090": (modifier, 0.90),
    "e_straight_rate100": (same, 1.00),
    "h_modifier_rate100": (modifier, 1.00),
}


def inner_gaps(pcm: bytes, win_ms=10, quiet=250, min_ms=70) -> list[int]:
    s = memoryview(tts._trim(pcm, keep=0)).cast("h")
    w = int(config.SAMPLE_RATE * win_ms / 1000)
    runs, cur = [], 0
    for i in range(0, len(s) - w, w):
        if max(abs(x) for x in s[i:i + w]) < quiet:
            cur += win_ms
        else:
            if cur >= min_ms:
                runs.append(cur)
            cur = 0
    return runs


def render(texts, fn, rate):
    with ThreadPoolExecutor(max_workers=3) as pool:  # gentle: Google answers 429 above a few parallel calls
        return list(pool.map(lambda t: tts.synth(fn(t), rate=rate, clean=False), texts))


out = Path("samples")
out.mkdir(exist_ok=True)
print(f"voice={config.VOICE_NAME}  {len(ELISION)} elision sentences, {len(CONTROL)} controls")
for name, (fn, rate) in VARIANTS.items():
    el, ct = render(ELISION, fn, rate), render(CONTROL, fn, rate)
    e_n = [len(inner_gaps(c)) for c in el]
    c_n = [len(inner_gaps(c)) for c in ct]
    wpm = sum(len(t.split()) for t in ELISION) / (sum(len(tts._trim(c, keep=0)) for c in el) / tts.BYTES_PER_SEC / 60)
    print(f"{name:22s} elision: {sum(1 for n in e_n if n):2d}/{len(e_n)} sentences with a mid-sentence pause"
          f"   control: {sum(1 for n in c_n if n):2d}/{len(c_n)}   speech {wpm:5.1f} wpm")
    pcm = bytearray()
    for c in el[:8]:
        pcm += tts._trim(c) + tts._silence(0.9)
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE); w.writeframes(bytes(pcm))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(wav.with_suffix(".mp3"))], check=True)
    wav.unlink()
