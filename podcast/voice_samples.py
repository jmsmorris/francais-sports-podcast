"""Render the same short French passage in every male fr-CA Google voice."""
import os
import re
import subprocess
import wave
from pathlib import Path

import requests

from . import config, tts

TEXT = ("Bonjour et bienvenue ! Je m'appelle Martin, et voici les nouvelles du sport en français facile. "
        "Hier soir, le Canadien de Montréal a gagné en prolongation contre le Mammoth de l'Utah. "
        "Le pointage final : cinq à quatre. Cole Caufield a marqué le but gagnant après seulement trente secondes. "
        "Une prolongation, c'est une période supplémentaire, quand le match est égal.")

voices = requests.get("https://texttospeech.googleapis.com/v1/voices", params={"languageCode": "fr-CA"},
                      headers={"X-Goog-Api-Key": os.environ["GOOGLE_TTS_API_KEY"]}, timeout=30).json()["voices"]
male = sorted(v["name"] for v in voices if v.get("ssmlGender") == "MALE")
print("Male fr-CA voices:", male)
out = Path("samples")
out.mkdir(exist_ok=True)
for name in male:
    if re.search(r"Standard", name):
        continue  # robotic; skip
    try:
        pcm = bytearray()
        for s in tts.split_sentences(TEXT):
            pcm += tts.synth(s, voice=name)
            pcm += tts._silence(0.7)
    except Exception as e:  # noqa: BLE001
        print(name, "failed:", e)
        continue
    wav = out / f"{name}.wav"
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(config.SAMPLE_RATE); w.writeframes(bytes(pcm))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(wav), "-b:a", "96k", str(wav.with_suffix(".mp3"))], check=True)
    wav.unlink()
    print("wrote", name)
