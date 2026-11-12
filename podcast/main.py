"""Daily podcast run, in two halves.

Cloud routine (Claude writes the script, no API key needed):
  python -m podcast.main --prepare     scrape -> pending/{id}.json + out/{id}.brief.md
  python -m podcast.main --check ID    validate scripts/{id}.json
GitHub Action (runs when a script is pushed):
  python -m podcast.main --render      audio + release + feed for every prepared script
Fallback / manual (needs ANTHROPIC_API_KEY):
  python -m podcast.main [--force]     all-in-one: scrape, script via API, audio, feed
  python -m podcast.main --scrape-only | --rerender ID
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config, feed, scrape

MONTHS = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août",
          "septembre", "octobre", "novembre", "décembre"]
DAYS = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
STALE_MINUTES = 90  # a prepared episode with no script after this long is abandoned and redone


def date_fr(d) -> str:
    day = "1er" if d.day == 1 else str(d.day)
    return f"{DAYS[d.weekday()]} {day} {MONTHS[d.month - 1]} {d.year}"


def upload(mp3: Path, tag: str, title: str) -> str:
    subprocess.run(["gh", "release", "delete", tag, "-R", config.REPO, "-y", "--cleanup-tag"],
                   capture_output=True)
    subprocess.run(["gh", "release", "create", tag, str(mp3), "-R", config.REPO,
                    "--title", title, "--notes", "Épisode audio. Notes et transcription : "
                    f"{config.SITE_URL}/transcripts/{tag.removeprefix('ep-')}.html"], check=True)
    return f"https://github.com/{config.REPO}/releases/download/{tag}/{mp3.name}"


def rerender(ep_id: str) -> int:
    """New audio for an existing episode, same script and same article list."""
    from . import tts

    episodes = feed.load_episodes()
    ep = next((e for e in episodes if e.get("id", e["date"]) == ep_id), None)
    path = config.SCRIPTS / f"{ep_id}.json"
    if not ep or not path.exists():
        print(f"No episode or saved script for {ep_id}")
        return 1
    script = json.loads(path.read_text())
    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    mp3 = out_dir / f"sport-francais-{ep_id}.mp3"
    stats = tts.render_paced(script, mp3)
    ep.update(audio_url=upload(mp3, f"ep-{ep_id}", ep["title"]), bytes=mp3.stat().st_size,
              duration_seconds=stats["duration_seconds"], stats=stats,
              guid=ep["guid"] + "-v2" if not ep["guid"].endswith("-v2") else ep["guid"])
    feed.write_transcript_page(ep, script)
    feed.save_episodes(episodes)
    feed.build_feed(episodes)
    print(f"Re-recorded {ep_id}: {stats['duration_seconds'] / 60:.1f} min, {stats['average_wpm']} wpm")
    return 0


# ---------- which night, what's already done ----------

def plan_day(now: datetime) -> tuple[date, datetime, datetime]:
    """The episode covers the day of the most recent 11 PM. GitHub/the scheduler can be late,
    so any later run catches up on a missed night. The news window ends at midnight after that
    day, so a morning catch-up covers that day only."""
    day = now.date() if now.hour >= config.PUBLISH_HOUR else (now - timedelta(days=1)).date()
    window_end = min(now, datetime.combine(day + timedelta(days=1), time(0), now.tzinfo))
    start = datetime.combine(day, time(config.PUBLISH_HOUR), now.tzinfo)
    return day, window_end, start


def load_pending(now: datetime) -> list[dict]:
    """Prepared episodes still waiting for audio: script written, or prepared recently
    (the routine is probably still writing it)."""
    out = []
    for p in sorted(config.PENDING.glob("*.json")):
        try:
            m = json.loads(p.read_text())
        except json.JSONDecodeError:
            continue
        fresh = now - datetime.fromisoformat(m["prepared_at"]) < timedelta(minutes=STALE_MINUTES)
        if (config.SCRIPTS / f"{m['id']}.json").exists() or fresh:
            out.append(m)
    return out


def already_done(day: date, start: datetime, episodes: list[dict], pending: list[dict]) -> bool:
    today = day.isoformat()
    if any(e["date"] == today and datetime.fromisoformat(e["published"]) >= start for e in episodes):
        return True
    return any(m["day"] == today and datetime.fromisoformat(m["prepared_at"]) >= start for m in pending)


def used_urls(episodes: list[dict], pending: list[dict]) -> set[str]:
    used = {u for e in episodes for u in e.get("source_urls", []) + e.get("considered_urls", [])}
    return used | {a["url"] for m in pending for a in m["articles"]}


def new_ep_id(today: str, now: datetime, episodes: list[dict], pending: list[dict]) -> str:
    taken = {e.get("id", e["date"]) for e in episodes} | {m["id"] for m in pending}
    return today if today not in taken else f"{today}-{now:%H%M}"


def last_script(episodes: list[dict]) -> dict | None:
    """The latest published episode's script, so follow-up stories can build on it."""
    if not episodes:
        return None
    last = max(episodes, key=lambda e: e["published"])
    path = config.SCRIPTS / f"{last.get('id', last['date'])}.json"
    return json.loads(path.read_text()) if path.exists() else None


# ---------- half 1: cloud routine ----------

def prepare(force: bool) -> int:
    from . import script as script_mod

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    day, window_end, start = plan_day(now)
    today = day.isoformat()
    episodes = feed.load_episodes()
    pending = load_pending(now)
    if not force and already_done(day, start, episodes, pending):
        print(f"NOTHING_TO_DO: the episode for {today} already exists or is being prepared.")
        return 0
    if now.date() != day:
        print(f"Catching up: the {today} episode was missed (it is {now:%a %H:%M} in Toronto).")
    ep_id = new_ep_id(today, now, episodes, pending)
    articles = scrape.collect(used_urls(episodes, pending), window_end)
    if len(articles) < 3:
        print(f"NOT_ENOUGH_STORIES: found {len(articles)} usable stories (need 3). "
              "Radio-Canada may be unreachable or quiet; nothing was prepared.")
        return 1

    config.PENDING.mkdir(exist_ok=True)
    meta = {"id": ep_id, "day": today, "date_fr": date_fr(day), "prepared_at": now.isoformat(),
            "articles": articles}
    (config.PENDING / f"{ep_id}.json").write_text(json.dumps(meta, ensure_ascii=False, indent=1))

    previous = script_mod._previous_block(last_script(episodes))
    brief = (
        f"# Brief pour l'épisode {ep_id}\n\n"
        f"## Instructions (à suivre à la lettre)\n\n{script_mod.SYSTEM}\n\n"
        f"## Format de sortie\n\nÉcris UN fichier JSON, scripts/{ep_id}.json, qui respecte ce schéma JSON "
        f"(aucune autre clé). Chaque \"source_urls\" ne contient que des URL des articles ci-dessous.\n\n"
        f"```json\n{json.dumps(script_mod.SCHEMA, indent=1)}\n```\n\n"
        f"## Date de l'épisode (la journée résumée) : {date_fr(day)}{previous}\n\n"
        f"## Articles ({len(articles)})\n\n{script_mod._articles_block(articles)}\n")
    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{ep_id}.brief.md").write_text(brief)
    print(f"PREPARED {ep_id}: {len(articles)} stories, {len(brief):,} characters of brief.")
    print(f"Read: out/{ep_id}.brief.md")
    print(f"Write: scripts/{ep_id}.json")
    print(f"Then run: python -m podcast.main --check {ep_id}")
    return 0


def check(ep_id: str) -> int:
    from .validate import validate

    path = config.SCRIPTS / f"{ep_id}.json"
    if not path.exists():
        print(f"MISSING: {path} does not exist.")
        return 1
    try:
        script = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        print(f"INVALID JSON: {e}")
        return 1
    meta_path = config.PENDING / f"{ep_id}.json"
    allowed = {a["url"] for a in json.loads(meta_path.read_text())["articles"]} if meta_path.exists() else None
    errors, warnings = validate(script, allowed)
    from .script import word_count
    for w in warnings:
        print(f"WARNING: {w}")
    for e in errors:
        print(f"ERROR: {e}")
    if errors:
        print("CHECK FAILED: fix the errors above and run the check again.")
        return 1
    print(f"CHECK OK: {word_count(script)} words, {sum(s['kind'] == 'story' for s in script['segments'])} stories.")
    return 0


# ---------- half 2: audio, upload, feed ----------

def publish_episode(ep_id: str, day: date, now: datetime, script: dict, articles: list[dict],
                    episodes: list[dict], no_upload: bool = False) -> list[dict] | None:
    from . import tts

    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    mp3 = out_dir / f"sport-francais-{ep_id}.mp3"
    stats = tts.render_paced(script, mp3)
    minutes = stats["duration_seconds"] / 60
    if not (config.MIN_MINUTES <= minutes <= config.MAX_MINUTES):
        print(f"WARNING: outside targets ({minutes:.1f} min, {stats['average_wpm']} wpm)")

    title = f"{date_fr(day).capitalize()} — {script['episode_title']}"
    if no_upload:
        print(f"Saved {mp3} ({minutes:.1f} min, {stats['average_wpm']} wpm). Not uploaded.")
        return None

    audio_url = upload(mp3, f"ep-{ep_id}", title)
    ep = {
        "id": ep_id,
        "date": day.isoformat(),
        "title": title,
        "guid": f"{config.REPO}/ep-{ep_id}",
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
    episodes = episodes + [ep]
    feed.write_transcript_page(ep, script)
    feed.save_episodes(episodes)
    feed.build_feed(episodes)
    print(f"Published: {title} ({minutes:.1f} min, {stats['average_wpm']} wpm)")
    return episodes


def render_pending() -> int:
    from .validate import validate

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    episodes = feed.load_episodes()
    done = {e.get("id", e["date"]) for e in episodes}
    status = 0
    made = 0
    for path in sorted(config.PENDING.glob("*.json")):
        meta = json.loads(path.read_text())
        ep_id = meta["id"]
        if ep_id in done:
            path.unlink()  # already published; tidy up
            continue
        script_path = config.SCRIPTS / f"{ep_id}.json"
        if not script_path.exists():
            print(f"{ep_id}: no script yet, skipping.")
            continue
        script = json.loads(script_path.read_text())
        errors, _ = validate(script, {a["url"] for a in meta["articles"]})
        if errors:
            print(f"{ep_id}: script failed validation, not voiced:\n  " + "\n  ".join(errors))
            status = 1
            continue
        result = publish_episode(ep_id, date.fromisoformat(meta["day"]), now, script, meta["articles"], episodes)
        episodes = result if result is not None else episodes
        path.unlink()
        made += 1
    print(f"Rendered {made} episode(s).")
    return status


# ---------- fallback: everything in one go with the Anthropic API ----------

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--scrape-only", action="store_true")
    ap.add_argument("--no-upload", action="store_true")
    ap.add_argument("--prepare", action="store_true", help="cloud routine: scrape and write the brief")
    ap.add_argument("--check", metavar="ID", help="validate scripts/ID.json")
    ap.add_argument("--render", action="store_true", help="voice and publish every prepared script")
    ap.add_argument("--rerender", metavar="ID", help="re-record an existing episode's audio")
    args = ap.parse_args()
    if args.rerender:
        return rerender(args.rerender)
    if args.prepare:
        return prepare(args.force)
    if args.check:
        return check(args.check)
    if args.render:
        return render_pending()

    now = datetime.now(ZoneInfo(config.TIMEZONE))
    day, window_end, start = plan_day(now)
    episodes = feed.load_episodes()
    pending = load_pending(now)
    if not args.force and not args.scrape_only and already_done(day, start, episodes, pending):
        print(f"It is {now:%H:%M} in Toronto; the episode for {day} already exists.")
        return 0
    ep_id = new_ep_id(day.isoformat(), now, episodes, pending)
    articles = scrape.collect(used_urls(episodes, pending), window_end)
    if args.scrape_only:
        for a in articles:
            print(f"[{a['topic']:10}] {a['published'][:16]} {a['title']}  ({len(a['body'])} chars)")
        return 0
    if len(articles) < 3:
        print("Not enough stories found; aborting so a bad episode isn't published.")
        return 1

    from . import script as script_mod

    script = script_mod.write_script(articles, date_fr(day), last_script(episodes))
    out_dir = config.ROOT / "out"
    out_dir.mkdir(exist_ok=True)
    (out_dir / f"{ep_id}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
    config.SCRIPTS.mkdir(exist_ok=True)  # kept in the repo so audio can be re-recorded later
    (config.SCRIPTS / f"{ep_id}.json").write_text(json.dumps(script, ensure_ascii=False, indent=2))
    publish_episode(ep_id, day, now, script, articles, episodes, args.no_upload)
    return 0


if __name__ == "__main__":
    sys.exit(main())
