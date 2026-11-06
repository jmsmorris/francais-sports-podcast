"""Build the podcast RSS feed and per-episode transcript pages."""
from __future__ import annotations

import html
import json
from datetime import datetime
from email.utils import format_datetime
from xml.sax.saxutils import escape

from . import config


def load_episodes() -> list[dict]:
    if config.EPISODES_JSON.exists():
        return json.loads(config.EPISODES_JSON.read_text())
    return []


def save_episodes(eps: list[dict]) -> None:
    config.EPISODES_JSON.write_text(json.dumps(eps, ensure_ascii=False, indent=2))


def notes_html(script: dict) -> str:
    out = []
    for seg in script["segments"]:
        if seg["kind"] == "vocabulary":
            continue
        out.append(f"<h3>{html.escape(seg['heading'])}</h3>")
        out += [f"<p>{html.escape(p)}</p>" for p in seg["paragraphs"]]
    vocab = "".join(f"<li><b>{html.escape(v['french'])}</b> — {html.escape(v['english'])}</li>"
                    for v in script.get("vocabulary", []))
    if vocab:
        out.append(f"<h3>Les mots du jour</h3><ul>{vocab}</ul>")
    srcs = sorted({u for s in script["segments"] for u in s.get("source_urls", [])})
    if srcs:
        out.append("<h3>Sources (Radio-Canada Sports)</h3><ul>" +
                   "".join(f'<li><a href="{html.escape(u)}">{html.escape(u)}</a></li>' for u in srcs) + "</ul>")
    return "\n".join(out)


def write_transcript_page(ep: dict, script: dict) -> None:
    config.TRANSCRIPTS.mkdir(parents=True, exist_ok=True)
    page = f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{html.escape(ep['title'])}</title>
<style>body{{font:18px/1.6 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
@media (prefers-color-scheme:dark){{body{{color:#eee;background:#141414}}a{{color:#8cf}}}}audio{{width:100%}}</style>
</head><body><h1>{html.escape(ep['title'])}</h1>
<audio controls preload="none" src="{html.escape(ep['audio_url'])}"></audio>
{notes_html(script)}
<p><a href="../index.html">← Tous les épisodes</a></p></body></html>"""
    (config.TRANSCRIPTS / f"{ep.get('id', ep['date'])}.html").write_text(page)


def build_feed(eps: list[dict]) -> None:
    eps = sorted(eps, key=lambda e: e["published"], reverse=True)
    cover = f"{config.SITE_URL}/cover.png"
    items = []
    for e in eps:
        pub = format_datetime(datetime.fromisoformat(e["published"]))
        items.append(f"""    <item>
      <title>{escape(e['title'])}</title>
      <guid isPermaLink="false">{escape(e['guid'])}</guid>
      <pubDate>{pub}</pubDate>
      <enclosure url="{escape(e['audio_url'])}" length="{e['bytes']}" type="audio/mpeg"/>
      <itunes:duration>{int(e['duration_seconds'])}</itunes:duration>
      <itunes:episodeType>full</itunes:episodeType>
      <itunes:explicit>false</itunes:explicit>
      <link>{config.SITE_URL}/transcripts/{e.get('id', e['date'])}.html</link>
      <podcast:transcript url="{config.SITE_URL}/transcripts/{e.get('id', e['date'])}.html" type="text/html" language="fr"/>
      <description><![CDATA[{e['notes_html']}]]></description>
      <content:encoded><![CDATA[{e['notes_html']}]]></content:encoded>
    </item>""")
    owner = (f"<itunes:owner><itunes:name>{escape(config.SHOW_AUTHOR)}</itunes:name>"
             f"<itunes:email>{escape(config.OWNER_EMAIL)}</itunes:email></itunes:owner>") if config.OWNER_EMAIL else ""
    xml = f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0" xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd"
     xmlns:content="http://purl.org/rss/1.0/modules/content/"
     xmlns:podcast="https://podcastindex.org/namespace/1.0"
     xmlns:atom="http://www.w3.org/2005/Atom">
  <channel>
    <title>{escape(config.SHOW_TITLE)}</title>
    <link>{config.SITE_URL}/</link>
    <atom:link href="{config.SITE_URL}/feed.xml" rel="self" type="application/rss+xml"/>
    <language>fr-ca</language>
    <description>{escape(config.SHOW_DESCRIPTION)}</description>
    <itunes:summary>{escape(config.SHOW_DESCRIPTION)}</itunes:summary>
    <itunes:author>{escape(config.SHOW_AUTHOR)}</itunes:author>
    {owner}
    <itunes:image href="{cover}"/>
    <image><url>{cover}</url><title>{escape(config.SHOW_TITLE)}</title><link>{config.SITE_URL}/</link></image>
    <itunes:category text="Education"><itunes:category text="Language Learning"/></itunes:category>
    <itunes:category text="Sports"/>
    <itunes:explicit>false</itunes:explicit>
    <itunes:type>episodic</itunes:type>
    <podcast:locked>yes</podcast:locked>
{chr(10).join(items)}
  </channel>
</rss>
"""
    config.FEED_XML.write_text(xml)

    rows = "".join(f'<li><a href="transcripts/{e.get("id", e["date"])}.html">{html.escape(e["title"])}</a> '
                   f'<small>({round(e["duration_seconds"] / 60)} min)</small></li>' for e in eps)
    (config.DOCS / "index.html").write_text(f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{html.escape(config.SHOW_TITLE)}</title>
<style>body{{font:18px/1.6 system-ui,sans-serif;max-width:42rem;margin:2rem auto;padding:0 1rem;color:#222;background:#fff}}
@media (prefers-color-scheme:dark){{body{{color:#eee;background:#141414}}a{{color:#8cf}}}}img{{max-width:200px;border-radius:12px}}code{{word-break:break-all}}</style>
</head><body><img src="cover.png" alt=""><h1>{html.escape(config.SHOW_TITLE)}</h1>
<p>{html.escape(config.SHOW_DESCRIPTION)}</p>
<p>Abonnez-vous dans votre application de balados avec ce lien :<br><code>{config.SITE_URL}/feed.xml</code></p>
<h2>Épisodes</h2><ul>{rows}</ul></body></html>""")
