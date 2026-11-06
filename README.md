# Le sport en français facile

A daily French-learning podcast built from Radio-Canada Sports news. The focus is hockey, baseball and the Olympics.

Every day at 5 PM Toronto time, a GitHub Action does this:

1. Collects stories published in the last 24 hours that no earlier episode has used, from `ici.radio-canada.ca/sports` (the RSS feed, the main page and the Olympic sports page).
2. Asks Claude (`claude-opus-5-5`) to write a ~1,350-word script in B1-level French. The host, "Martin", introduces himself every day, and each episode ends with a "Les mots du jour" vocabulary segment.
3. Reads it aloud with Google Cloud Text-to-Speech, using the same voice every day (`VOICE_NAME` in `podcast/config.py`). It synthesizes one sentence at a time and adds short fixed pauses (0.9 s after a sentence, 1.4 s after a paragraph, 2.3 s between stories). These are set by `PAUSE_*` in `podcast/config.py`.
4. Uploads the MP3 as a GitHub Release, then updates `docs/feed.xml` and a transcript page that GitHub Pages serves.

**Subscribe:** https://jmsmorris.github.io/francais-sports-podcast/feed.xml

## Secrets
- `ANTHROPIC_API_KEY`
- `GOOGLE_TTS_API_KEY` (a Google Cloud API key restricted to the Text-to-Speech API)

## Manual runs
- **Actions → Daily episode → Run workflow** makes today's episode now.
- **Actions → Voice samples → Run workflow** renders a sample of every male fr-CA voice, which you can download from the run's artifacts.

## Local runs
```bash
pip install -r requirements.txt   # also needs ffmpeg
python -m podcast.main --scrape-only        # list today's stories
python -m podcast.main --force --no-upload  # make out/sport-francais-YYYY-MM-DD.mp3
```

The summaries are based on reporting by Radio-Canada. Its RSS is for personal use only, so this feed is meant for personal listening.
