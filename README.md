# Le sport en français facile

A daily French-learning podcast built from Radio-Canada Sports news. The focus is hockey, baseball and the Olympics.

Every night at 11 PM Toronto time (a recap of the day, for listening the next morning) it runs in two halves:

**1. A Claude cloud routine writes the script** (no API key; it runs on the Claude plan). It runs `python -m podcast.main --prepare`, which collects stories published in the last 24 hours that no earlier episode has used, from `ici.radio-canada.ca/sports` (the main page and the Olympic sports page). It then reads `out/<id>.brief.md`, writes a ~1,350-word B1-level French script to `scripts/<id>.json` (the host, "Martin", introduces himself every day, and each episode ends with "Les mots du jour"), checks it with `python -m podcast.main --check <id>`, and pushes to main. If the 11 PM run is missed, the routine's 6 AM run catches up on that night.

**2. This repo's GitHub Action voices it** when a script is pushed. It reads the script aloud with Google Cloud Text-to-Speech, using the same voice every day (`VOICE_NAME` in `podcast/config.py`). It synthesizes one sentence at a time and adds short fixed pauses (0.9 s after a sentence, 1.4 s after a paragraph, 2.3 s between stories; `PAUSE_*` in `podcast/config.py`). It uploads the MP3 as a GitHub Release, then updates `docs/feed.xml` and a transcript page that GitHub Pages serves.

**Subscribe:** https://jmsmorris.github.io/francais-sports-podcast/feed.xml

## Secrets
- `ANTHROPIC_API_KEY` (optional: only the manual "legacy" fallback uses it)
- `GOOGLE_TTS_API_KEY` (a Google Cloud API key restricted to the Text-to-Speech API)

## Manual runs
- **Actions → Daily episode → Run workflow** voices any script that is waiting. Tick *legacy* to scrape and write the script with the Anthropic API instead (needs `ANTHROPIC_API_KEY`), or give an episode id under *rerender* to re-record its audio.
- **Actions → Voice samples → Run workflow** renders a sample of every male fr-CA voice, which you can download from the run's artifacts.

## Local runs
```bash
pip install -r requirements.txt   # also needs ffmpeg
python -m podcast.main --scrape-only        # list today's stories
python -m podcast.main --force --no-upload  # make out/sport-francais-YYYY-MM-DD.mp3
```

The summaries are based on reporting by Radio-Canada. Its RSS is for personal use only, so this feed is meant for personal listening.
