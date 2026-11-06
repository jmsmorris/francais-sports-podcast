"""Daily run: scrape -> script -> audio -> GitHub Release -> feed.

python -m podcast.main            # scheduled run (only acts after 5 PM Toronto time, once per day)
python -m podcast.main --force    # make today's episode now
python -m podcast.main --scrape-only
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, feed, scrape

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]


def date_fr(d: datetime) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return f"{DAYS[d.weekday()]} {day} {MONTHS[d.month - 1]} {d.year}"


def upload(mp3: Path, tag: str, title: str) -> str:
    subprocess.run(["gh", "release", "delete", tag, "-R", config.REPO, "-y", "--cleanup-tag"],
                   capture_output=True)
    subprocess.run(["gh", "release", "create", tag, str(mp3), "-R", config.REPO,
                    "--title", title, "--notes", "Épisode audio. Notes et transcription : "
                    f"{config.SITE_URL}/transcripts/{tag.removeprefix('ep-')}.html"], check=True)
    return f"https://github.com/{config.REPO}/releases/download/{tag}/{mp3.name}"


def rerender(date: str) -> int:
    """New audio for an existing episode, same script and same article list."""
    from . import tts

    episodes = feed.load_episodes()
    ep = next((e for e in episodes if e["date"] == date), None)
    path = config.SCRIPTS / f"{date}.json"
    if not ep or not path.exists():
        print(f"No episode or saved script for {date}")
        return 1
    script = json.loads(path.read_text())
    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    mp3 = out_dir / f"sport-francais-{date}.mp3"
    stats = tts.render_paced(script, mp3)
    ep.update(audio_url=upload(mp3, f"ep-{date}", ep["title"]), bytes=mp3.stat().st_size,
              duration_seconds=stats["duration_seconds"], stats=stats,
              guid=ep["guid"] + "-v2" if not ep["guid"].endswith("-v2") else ep["guid"])
    feed.write_transcript_page(ep, script)
    feed.save_episodes(episodes)
    feed.build_feed(episodes)
    print(f"Re-recorded {date}: {stats['duration_seconds'] / 60:.1f} min, {stats['average_wpm']} wpm")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--scrape-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--rerender", metavar="YYYY-MM-DD",
                    help="re-record an existing episode's audio from its saved script")
    args = ap.parse_args()
    if args.rerender:
        return rerender(args.rerender)

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    today = now.date().isoformat()
    episodes = feed.load_episodes()

    if not args.force and not args.scrape_only:
        if now.hour < config.PUBLISH_HOUR:
            print(f"It is {now:%H:%M} in Toronto; waiting for {config.PUBLISH_HOUR}:00.")
            return 0
        if any(e["date"] == today for e in episodes):
            print("Today's episode already exists.")
            return 0

    used = {u for e in episodes for u in e.get("source_urls", []) + e.get("considered_urls", [])}
    articles = scrape.collect(used)
    if args.scrape_only:
        for a in articles:
            print(f"[{a['topic']:10}] {a['published'][:16]} {a['title']}  ({len(a['body'])} chars)")
        return 0
    if len(articles) < 3:
        print("Not enough stories found; aborting so a bad episode isn't published.")
        return 1

    from . import script as script_mod, tts  # imported late so --scrape-only needs no keys

    script = script_mod.write_script(articles, date_fr(now))
    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{today}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
    config.SCRIPTS.mkdir(exist_ok=True)  # kept in the repo so audio can be re-recorded later
    (config.SCRIPTS / f"{today}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))

    mp3 = out_dir / f"sport-francais-{today}.mp3"
    stats = tts.render_paced(script, mp3)
    minutes = stats["duration_seconds"] / 60
    if not (config.MIN_MINUTES <= minutes <= config.MAX_MINUTES):
        print(f"WARNING: outside targets ({minutes:.1f} min, {stats['average_wpm']} wpm)")

    title = f"{date_fr(now).capitalize()} — {script['episode_title']}"
    if args.no_upload:
        print(f"Saved {mp3} ({minutes:.1f} min, {stats['average_wpm']} wpm). Not uploaded.")
        return 0

    audio_url = upload(mp3, f"ep-{today}", title)
    ep = {
        "date": today,
        "title": title,
        "guid": f"{config.REPO}/ep-{today}",
        "published": now.isoformat(),
        "audio_url": audio_url,
        "bytes": mp3.stat().st_size,
        "duration_seconds": stats["duration_seconds"],
        "stats": stats,
        "source_urls": sorted({u for s in script["segments"] for u in s.get("source_urls", [])}),
        # Every article handed to Claude counts as used, so nothing can come back tomorrow.
        "considered_urls": sorted(a["url"] for a in articles),
        "notes_html": feed.notes_html(script),
    }
    episodes = [e for e in episodes if e["date"] != today] + [ep]
    feed.write_transcript_page(ep, script)
    feed.save_episodes(episodes)
    feed.build_feed(episodes)
    print(f"Published: {title} ({minutes:.1f} min, {stats['average_wpm']} wpm)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
