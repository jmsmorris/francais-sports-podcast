"""Checks a script written by Claude (cloud routine) before it is committed and voiced."""
from __future__ import annotations

import re

from . import config
from .script import word_count

SEGMENT_KEYS = {"kind", "heading", "paragraphs", "source_urls"}
KINDS = {"intro", "story", "vocabulary", "outro"}


def validate(script: dict, allowed_urls: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors must be fixed; warnings are advice."""
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(script, dict) or set(script) != {"episode_title", "segments", "vocabulary"}:
        return ['Top level must be an object with exactly: "episode_title", "segments", "vocabulary".'], []
    if not isinstance(script["episode_title"], str) or not script["episode_title"].strip():
        errors.append("episode_title must be a non-empty string.")
    segs = script["segments"]
    if not isinstance(segs, list) or not segs:
        return errors + ["segments must be a non-empty list."], warnings
    for i, seg in enumerate(segs):
        if not isinstance(seg, dict) or set(seg) != SEGMENT_KEYS:
            errors.append(f"segments[{i}] must have exactly the keys {sorted(SEGMENT_KEYS)}.")
            continue
        if seg["kind"] not in KINDS:
            errors.append(f"segments[{i}].kind must be one of {sorted(KINDS)}.")
        if not isinstance(seg["heading"], str) or not seg["heading"].strip():
            errors.append(f"segments[{i}].heading must be a non-empty string.")
        paras = seg["paragraphs"]
        if not isinstance(paras, list) or not paras or not all(isinstance(p, str) and p.strip() for p in paras):
            errors.append(f"segments[{i}].paragraphs must be a non-empty list of non-empty strings.")
        if not isinstance(seg["source_urls"], list) or not all(isinstance(u, str) for u in seg["source_urls"]):
            errors.append(f"segments[{i}].source_urls must be a list of strings.")
        elif allowed_urls is not None:
            for u in seg["source_urls"]:
                if u not in allowed_urls:
                    errors.append(f"segments[{i}] cites a URL that is not in the brief: {u}")
    if errors:
        return errors, warnings

    kinds = [s["kind"] for s in segs]
    if kinds[0] != "intro":
        errors.append('The first segment must be kind "intro".')
    if kinds[-1] != "outro":
        errors.append('The last segment must be kind "outro".')
    if kinds.count("vocabulary") != 1:
        errors.append('Exactly one segment of kind "vocabulary" ("Les mots du jour") is required.')
    stories = kinds.count("story")
    if not 4 <= stories <= 10:
        errors.append(f'Use about 6 to 9 "story" segments (4 to 10 allowed); found {stories}.')
    for s in segs:
        if s["kind"] == "story" and not s["source_urls"]:
            errors.append(f'Story "{s["heading"]}" needs its source_urls.')

    vocab = script["vocabulary"]
    if (not isinstance(vocab, list) or not 5 <= len(vocab) <= 8
            or not all(isinstance(v, dict) and set(v) == {"french", "english"}
                       and all(isinstance(x, str) and x.strip() for x in v.values()) for v in vocab)):
        errors.append('"vocabulary" must be 5 to 8 objects {"french": ..., "english": ...}.')

    n = word_count(script)
    if not config.MIN_WORDS <= n <= config.MAX_WORDS:
        errors.append(f"The spoken text has {n} words; it must be between {config.MIN_WORDS} and "
                      f"{config.MAX_WORDS} (target {config.TARGET_WORDS}).")

    text = "\n".join(p for s in segs for p in s["paragraphs"])
    if re.search(r"[()\[\]*#•_]|^\s*[-–]\s", text, re.M):
        errors.append("The spoken text must have no parentheses, brackets, markdown or bullet characters.")
    if re.search(r"https?://", text):
        errors.append("No URLs in the spoken text.")
    digits = re.findall(r"\d+", text)
    if len(digits) > 6:
        warnings.append(f"{len(digits)} digit groups in the spoken text; spell scores and numbers out in words.")
    sentences = [x for x in re.split(r"(?<=[.!?…])\s+", text) if x.strip()]
    if sentences:
        avg = n / len(sentences)
        if avg > 18:
            warnings.append(f"Sentences average {avg:.0f} words; B1 listeners need about 10 to 15.")
    return errors, warnings
