"""Collect recent sports stories from ici.radio-canada.ca/sports."""
from __future__ import annotations

import html
import json
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta, timezone

import requests

from . import config

UA = "Mozilla/5.0 (compatible; french-sports-podcast/1.0; personal language-learning feed)"
ARTICLE_RE = re.compile(r"https://ici\.radio-canada\.ca/(?:sports|nouvelle)/\d{6,}/[a-z0-9\-]+")

# Keyword fallback when the page has no "Sport" metadata.
TOPIC_KEYWORDS = {
    "hockey": ["hockey", "lnh", "canadien", "rondelle", "coupe stanley", "lphf", "oilers",
               "maple leafs", "sénateurs", "jets", "canucks", "flames", "lhjmq"],
    "baseball": ["baseball", "mlb", "blue jays", "série mondiale", "lanceur", "coup de circuit",
                 "frappeur", "dodgers", "yankees", "receveur", "marbre"],
    "olympiques": ["olympique", "olympiques", "jo ", "milan", "cortina", "paralympique",
                   "patinage", "courte piste", "longue piste", "ski", "bobsleigh", "luge",
                   "judo", "natation", "athlétisme", "plongeon", "biathlon", "curling",
                   "snowboard", "planche à neige", "canada olympique"],
}
OLYMPIC_SPORT_TAGS = {"patinage-vitesse", "patinage-artistique", "ski", "ski-alpin", "natation",
                      "athletisme", "judo", "plongeon", "biathlon", "curling", "bobsleigh",
                      "luge", "snowboard", "sports-olympiques", "olympiques", "cyclisme",
                      "aviron", "canoe-kayak", "gymnastique", "halterophilie", "lutte", "boxe"}


def _get(url: str) -> str:
    for attempt in range(3):
        try:
            r = requests.get(url, headers={"User-Agent": UA}, timeout=30)
            r.raise_for_status()
            return r.text
        except requests.RequestException:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))
    return ""


def _clean(text: str) -> str:
    text = html.unescape(re.sub(r"<[^>]+>", " ", text or ""))
    return re.sub(r"\s+", " ", text).strip()


def candidate_urls() -> dict[str, dict]:
    """URL -> partial info (title/summary/date from RSS when available)."""
    found: dict[str, dict] = {}
    for rss in config.SOURCE_RSS:
        try:
            root = ET.fromstring(_get(rss).encode())
        except Exception as e:  # noqa: BLE001
            print(f"RSS failed {rss}: {e}")
            continue
        for item in root.iter("item"):
            link = (item.findtext("link") or "").strip()
            if not link:
                continue
            found[link] = {
                "url": link,
                "title": _clean(item.findtext("title")),
                "summary": _clean(item.findtext("description")),
                "rss_date": item.findtext("pubDate"),
            }
    for page in config.SOURCE_PAGES:
        try:
            for link in set(ARTICLE_RE.findall(_get(page))):
                found.setdefault(link, {"url": link})
        except Exception as e:  # noqa: BLE001
            print(f"Page failed {page}: {e}")
    return found


def _news_article(page: str) -> dict | None:
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            data = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        stack = [data]
        while stack:
            o = stack.pop()
            if isinstance(o, dict):
                if o.get("@type") in ("NewsArticle", "ReportageNewsArticle", "AnalysisNewsArticle",
                                      "OpinionNewsArticle", "Article") and o.get("articleBody"):
                    return o
                stack.extend(o.values())
            elif isinstance(o, list):
                stack.extend(o)
    return None


OLYMPIC_HINTS = ("ski", "patinage", "olymp", "biathlon", "bobsleigh", "luge", "judo", "natation",
                 "athletisme", "plongeon", "curling", "snowboard", "halterophilie", "aviron",
                 "canoe", "gymnastique", "lutte", "boxe", "cyclisme", "escrime", "triathlon")


def _topic(sport_tag: str, text: str) -> str:
    tags = [t.strip().lower() for t in (sport_tag or "").split(",") if t.strip()]
    if any("hockey" in t for t in tags):
        return "hockey"
    if any("baseball" in t for t in tags):
        return "baseball"
    if any(t in OLYMPIC_SPORT_TAGS or any(h in t for h in OLYMPIC_HINTS) for t in tags):
        return "olympiques"
    if tags:  # Radio-Canada tagged it with another sport (tennis, soccer...): trust that
        return tags[0]
    low = f" {text.lower()} "
    scores = {t: sum(low.count(k) for k in kws) for t, kws in TOPIC_KEYWORDS.items()}
    best = max(scores, key=scores.get)
    return best if scores[best] >= 2 else "autre"


def fetch_article(info: dict) -> dict | None:
    url = info["url"]
    if "/videos/" in url or "/balado" in url:
        # No article body; keep the RSS blurb if we have one.
        if not info.get("summary") or not info.get("rss_date"):
            return None
        published = datetime.strptime(info["rss_date"].strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
        text = f'{info["title"]}. {info["summary"]}'
        return {**info, "published": published.isoformat(), "body": info["summary"],
                "topic": _topic("", text), "kind": "video"}
    page = _get(url)
    art = _news_article(page)
    if not art:
        return None
    published = datetime.fromisoformat(art.get("datePublished"))
    sport = re.search(r'"Sport":"([^"]*)"', page)
    sport_tag = sport.group(1) if sport else ""
    headline = _clean(art.get("headline")) or info.get("title", "")
    body = _clean(art.get("articleBody"))
    body = re.split(r"À lire aussi ?:", body)[0].strip()
    return {
        "url": url,
        "title": headline,
        "summary": _clean(art.get("description")) or info.get("summary", ""),
        "published": published.isoformat(),
        "body": body[:6000],
        "sport_tag": sport_tag,
        "topic": _topic(sport_tag, f"{headline} {body[:1500]}"),
        "kind": "article",
    }


def collect(already_used: set[str], now: datetime | None = None) -> list[dict]:
    """Stories published in the last LOOKBACK_HOURS that no earlier episode used."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(hours=config.LOOKBACK_HOURS)
    cands = [c for c in candidate_urls().values() if c["url"] not in already_used]
    fresh_cands = []
    for c in cands:  # RSS items carry a date: skip old ones without downloading them
        if c.get("rss_date"):
            try:
                d = datetime.strptime(c["rss_date"].strip(), "%a, %d %b %Y %H:%M:%S %Z").replace(tzinfo=timezone.utc)
                if d < cutoff:
                    continue
            except ValueError:
                pass
        fresh_cands.append(c)
    print(f"{len(fresh_cands)} unused candidate links")
    articles = []
    for info in fresh_cands[: config.MAX_ARTICLES_TO_FETCH]:
        try:
            a = fetch_article(info)
        except Exception as e:  # noqa: BLE001
            print(f"skip {info['url']}: {e}")
            continue
        time.sleep(0.4)  # be polite
        if not a or len(a["body"]) < (80 if a["kind"] == "video" else 150):
            continue
        if datetime.fromisoformat(a["published"]) < cutoff:
            continue
        articles.append(a)

    order = {t: i for i, t in enumerate(config.FOCUS_SPORTS)}
    articles.sort(key=lambda a: a["published"], reverse=True)
    articles.sort(key=lambda a: order.get(a["topic"], 9))
    print("Topics:", {t: sum(a["topic"] == t for a in articles) for t in {a["topic"] for a in articles}})
    return articles
