"""Settings for the daily French sports podcast. Change values here, not in the code."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"  # served by GitHub Pages
EPISODES_JSON = DOCS / "episodes.json"
FEED_XML = DOCS / "feed.xml"
TRANSCRIPTS = DOCS / "transcripts"
SCRIPTS = ROOT / "scripts"  # saved episode scripts (JSON)

TIMEZONE = "America/Toronto"
PUBLISH_HOUR = 17  # 5 PM local time

# ---- Show ----
SHOW_TITLE = "Le sport en français facile"
SHOW_AUTHOR = "Le sport en français facile"
SHOW_DESCRIPTION = (
    "Chaque jour à 17 h : les nouvelles du hockey, du baseball et des sports olympiques, "
    "racontées en français simple (niveau B1), lentement, pour apprendre le français. "
    "Résumés basés sur les reportages de Radio-Canada Sports."
)
HOST_NAME = "Martin"  # the narrator introduces himself with this name every day
REPO = "jmsmorris/francais-sports-podcast"
SITE_URL = "https://jmsmorris.github.io/francais-sports-podcast"
OWNER_EMAIL = ""  # optional; some directories (Apple) want one

# ---- Sources ----
SOURCE_PAGES = [
    "https://ici.radio-canada.ca/sports",
    "https://ici.radio-canada.ca/sports/sports-olympiques",
]
SOURCE_RSS = ["https://ici.radio-canada.ca/info/rss/sports/en-continu"]
FOCUS_SPORTS = ["hockey", "baseball", "olympiques"]
LOOKBACK_HOURS = 24       # only stories newer than this; never widened
MAX_ARTICLES_TO_FETCH = 70

# ---- Script ----
CLAUDE_MODEL = "claude-opus-5-5"
TARGET_WORDS = 1350
MIN_WORDS = 1150
MAX_WORDS = 1550

# ---- Voice ----
# Same voice every day = same "person". Change only if you want a new narrator.
VOICE_NAME = "fr-CA-Chirp3-HD-Achird"  # Google describes Achird as "friendly"
VOICE_LANGUAGE = "fr-CA"
SPEAKING_RATE = 0.85       # Google speakingRate for each sentence (1.0 = normal)
# Pauses after each sentence / paragraph / story (seconds). Voice speed stays natural;
# with these pauses episodes average roughly 110-120 words per minute.
PAUSE_SENTENCE = 0.9
PAUSE_PARAGRAPH = 1.4
PAUSE_SEGMENT = 2.3
MIN_MINUTES, MAX_MINUTES = 10.0, 18.0
SAMPLE_RATE = 24000
MP3_BITRATE = "64k"        # mono speech; ~7 MB per 15 min
