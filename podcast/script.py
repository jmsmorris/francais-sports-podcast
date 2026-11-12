"""Turn the day's articles into a B1-level French radio script with Claude."""
from __future__ import annotations

import json
import re

from . import config

SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["episode_title", "segments", "vocabulary"],
    "properties": {
        "episode_title": {"type": "string"},
        "segments": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "heading", "paragraphs", "source_urls"],
                "properties": {
                    "kind": {"type": "string", "enum": ["intro", "story", "vocabulary", "outro"]},
                    "heading": {"type": "string"},
                    "paragraphs": {"type": "array", "items": {"type": "string"}},
                    "source_urls": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
        "vocabulary": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["french", "english"],
                "properties": {"french": {"type": "string"}, "english": {"type": "string"}},
            },
        },
    },
}

SYSTEM = f"""Tu es l'auteur d'un balado quotidien pour des anglophones qui apprennent le français.
L'animateur s'appelle {config.HOST_NAME}. Il est chaleureux, calme, encourageant, un peu drôle, \
et il parle comme un ami qui aime le sport. Il vouvoie l'auditeur (« vous », jamais « tu »). \
Il commence toujours de la même façon : « Bonjour ! Ici {config.HOST_NAME}, et bienvenue à votre balado \
sportif du matin, en français facile. » Le reste de l'introduction varie.

Ta tâche : écrire le texte complet de l'épisode, à lire à voix haute, à partir des articles \
de Radio-Canada Sports fournis.

Moment d'écoute : l'épisode est enregistré tard le soir et l'auditeur l'écoute le lendemain matin. \
C'est le résumé de la journée sportive qui vient de se terminer (la date de l'épisode). \
Parle donc de cette journée au passé, comme d'« hier » ou « hier soir », ou nomme le jour \
(« lundi soir »). N'utilise pas « aujourd'hui » ou « ce soir » pour ces événements. \
Pour un match prévu le jour de l'écoute, dis « aujourd'hui » ou « ce soir ».

Niveau de langue : B1 (CECR).
- Phrases courtes (en moyenne 10 à 15 mots). Une idée par phrase.
- Temps : présent, passé composé, imparfait simple, futur proche. Évite le subjonctif rare, \
le passé simple et les tournures littéraires.
- Vocabulaire courant. Quand un mot sportif ou une expression québécoise est utile \
(ex. « rondelle », « prolongation », « lanceur »), garde-le et explique-le simplement en français \
la première fois.
- Répète les noms importants (équipes, joueurs) pour aider l'auditeur à suivre.
- Écris pour l'oreille : pas de parenthèses, pas de listes à puces, pas d'abréviations \
(écris « la Ligue nationale de hockey », puis « la LNH »). Écris les pointages en lettres \
(« cinq à quatre »), et les dates et grands nombres de façon naturelle à l'oral.
- Pas d'anglais dans le texte lu.

Contenu et priorités :
1. Hockey, 2. baseball, 3. sports olympiques (et athlètes olympiques canadiens). \
Ces trois thèmes doivent occuper la grande majorité de l'épisode. \
Utilise d'autres sports seulement s'il manque de nouvelles.
- Regroupe les articles sur le même sujet. Choisis environ 6 à 9 nouvelles.
- Reste fidèle aux faits des articles. N'invente rien : aucun pointage, aucune citation, aucun chiffre \
qui n'est pas dans les articles. Tu peux expliquer le contexte général d'un sport.
- Pour les chroniques d'opinion, dis clairement que c'est l'avis du chroniqueur.

Structure :
- "intro" : salutation du matin (« Bonjour ! »), présentation de {config.HOST_NAME}, la journée résumée (« voici ce qui s'est passé hier, » suivi du jour et de la date de l'épisode), aperçu des sujets.
- plusieurs "story" : chaque nouvelle en 2 à 4 paragraphes.
- "vocabulary" : « Les mots du jour » — 5 ou 6 mots ou expressions entendus dans l'épisode, \
chacun expliqué en français simple avec un exemple.
- "outro" : courte récapitulation et au revoir chaleureux, « à demain matin ».

Longueur : environ {config.TARGET_WORDS} mots au total pour tous les paragraphes \
(minimum {config.MIN_WORDS}, maximum {config.MAX_WORDS}). C'est important : l'épisode doit durer \
environ quinze minutes à une vitesse lente.

Le champ "vocabulary" (hors texte lu) donne la liste de ces mots avec leur traduction anglaise, \
pour les notes de l'épisode. "source_urls" : les URL des articles utilisés pour chaque segment."""


def word_count(script: dict) -> int:
    return sum(len(re.findall(r"\w+(?:['’]\w+)?", p)) for s in script["segments"] for p in s["paragraphs"])


def _articles_block(articles: list[dict]) -> str:
    parts = []
    for i, a in enumerate(articles, 1):
        parts.append(
            f"<article id=\"{i}\" topic=\"{a['topic']}\" published=\"{a['published']}\" url=\"{a['url']}\">\n"
            f"Titre : {a['title']}\nRésumé : {a.get('summary', '')}\n\n{a['body']}\n</article>"
        )
    return "\n\n".join(parts)


def _call(client, user_text: str) -> dict:
    with client.beta.messages.stream(
        model=config.CLAUDE_MODEL,
        max_tokens=32000,
        system=SYSTEM,
        messages=[{"role": "user", "content": user_text}],
        thinking={"type": "adaptive"},
        output_config={"effort": "high", "format": {"type": "json_schema", "schema": SCHEMA}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    ) as stream:
        msg = stream.get_final_message()
    if msg.stop_reason == "refusal":
        raise RuntimeError(f"Claude declined: {msg.stop_details}")
    if msg.stop_reason == "max_tokens":
        raise RuntimeError("Script was cut off (max_tokens)")
    return json.loads("".join(b.text for b in msg.content if b.type == "text"))


def _previous_block(previous: dict | None) -> str:
    if not previous:
        return ""
    lines = []
    for seg in previous["segments"]:
        if seg["kind"] == "story":
            lines.append(f"- {seg['heading']} : {' '.join(seg['paragraphs'])[:400]}")
    return (
        "\n\nÉpisode précédent (déjà entendu par l'auditeur) :\n" + "\n".join(lines) +
        "\n\nSi un des nouveaux articles poursuit un de ces sujets, c'est permis : présente-le "
        "comme une suite (par exemple « Dans l'épisode d'hier, on vous a parlé de… Il y a du nouveau. »), "
        "rappelle le contexte en une ou deux phrases seulement, et concentre-toi sur ce qui est nouveau. "
        "Ne répète pas des informations déjà données sans nouveauté."
    )


def write_script(articles: list[dict], date_fr: str, previous: dict | None = None) -> dict:
    import anthropic  # only the API fallback needs it; the cloud routine writes scripts itself

    client = anthropic.Anthropic()
    base = (f"Date de l'épisode (la journée résumée) : {date_fr}.{_previous_block(previous)}"
            f"\n\nArticles du jour :\n\n{_articles_block(articles)}")
    script = _call(client, base)
    for _ in range(2):
        n = word_count(script)
        print(f"Script: {n} words")
        if config.MIN_WORDS <= n <= config.MAX_WORDS:
            break
        direction = "trop court" if n < config.MIN_WORDS else "trop long"
        script = _call(client, base + (
            f"\n\nAttention : une première version faisait {n} mots, c'est {direction}. "
            f"Vise {config.TARGET_WORDS} mots (entre {config.MIN_WORDS} et {config.MAX_WORDS})."))
    return script
