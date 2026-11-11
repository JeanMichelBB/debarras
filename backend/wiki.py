"""Wikipedia "Behind the scenes" excerpts, no LLM.

IMDb ID -> Wikidata (property P345) -> en/fr Wikipedia article -> excerpts of the
Production / Development / Casting / Reception sections. Wikipedia text is CC BY-SA 4.0:
the response carries the source URL and license so the UI can credit it.
"""

import re
from datetime import timedelta
from urllib.parse import quote

import httpx
from sqlalchemy.orm import Session

import config
from database.models import FactCache, utcnow

# Heading stems, matched as substrings (real headings are e.g. "Reception and legacy",
# "Declining ratings"). One section is taken from each group: how it was made, how it landed.
MAKING = {
    "en": ["production", "development", "writing", "casting", "filming"],
    "fr": ["production", "développement", "genèse", "écriture", "tournage", "casting"],
}
RECEPTION = {
    "en": ["declin", "ratings", "reception", "critical"],
    "fr": ["accueil", "réception", "audience", "critique"],
}
HEAD_RE = re.compile(r"^(={2,4})\s*(.+?)\s*\1\s*$", re.M)
MIN_SECTION_CHARS = 80
EXCERPT_CHARS = 650

_client: httpx.AsyncClient | None = None


def _get_client() -> httpx.AsyncClient:
    global _client
    if _client is None:
        _client = httpx.AsyncClient(timeout=10.0, headers={"User-Agent": config.WIKI_USER_AGENT})
    return _client


def parse_sections(extract: str) -> list[tuple[str, str]]:
    """Split a plain-text Wikipedia extract (headings as '== Title ==') into (heading, text)."""
    matches = list(HEAD_RE.finditer(extract))
    out = []
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(extract)
        out.append((m.group(2).strip(), extract[m.end():end].strip()))
    return out


def excerpt(text: str, limit: int = EXCERPT_CHARS) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    return (cut[: last + 1] if last > limit * 0.5 else cut.rstrip() + "…")


def _first_match(sections: list[tuple[str, str]], stems: list[str]) -> tuple[str, str] | None:
    for stem in stems:  # earlier stems are more specific / more interesting
        for heading, text in sections:
            if stem in heading.lower() and len(text) >= MIN_SECTION_CHARS:
                return heading, text
    return None


def pick_sections(sections: list[tuple[str, str]], lang: str) -> list[dict]:
    """Up to two excerpts: one on how it was made, one on how it was received."""
    picked = []
    for group in (MAKING, RECEPTION):
        match = _first_match(sections, group.get(lang, group["en"]))
        if match:
            picked.append({"heading": match[0], "text": excerpt(match[1])})
    return picked


async def _wikipedia_titles(imdb_id: str) -> dict[str, str]:
    c = _get_client()
    r = await c.get("https://www.wikidata.org/w/api.php", params={
        "action": "query", "list": "search", "srsearch": f"haswbstatement:P345={imdb_id}", "format": "json",
    })
    r.raise_for_status()
    hits = r.json().get("query", {}).get("search", [])
    if not hits:
        return {}
    qid = hits[0]["title"]
    r = await c.get("https://www.wikidata.org/w/api.php", params={
        "action": "wbgetentities", "ids": qid, "props": "sitelinks", "sitefilter": "enwiki|frwiki", "format": "json",
    })
    r.raise_for_status()
    links = r.json().get("entities", {}).get(qid, {}).get("sitelinks", {})
    return {code: links[f"{code}wiki"]["title"] for code in ("en", "fr") if f"{code}wiki" in links}


async def _extract(lang: str, title: str) -> str:
    r = await _get_client().get(f"https://{lang}.wikipedia.org/w/api.php", params={
        "action": "query", "prop": "extracts", "explaintext": 1, "exsectionformat": "wiki",
        "titles": title, "redirects": 1, "format": "json",
    })
    r.raise_for_status()
    pages = r.json().get("query", {}).get("pages", {})
    return next(iter(pages.values()), {}).get("extract", "") or ""


GAME_WORDS = ("video game", "jeu vidéo")
SCREEN_WORDS = ("film", "movie", "television", "télévis", "series", "série", "miniseries")


def is_game_article(extract: str) -> bool:
    """Wikidata sometimes maps a film's IMDb ID to the game it came from.

    Looks at the first sentence of the lead: a game with no film/TV wording is rejected.
    """
    lead = extract.split("\n", 1)[0][:300].lower()
    return any(w in lead for w in GAME_WORDS) and not any(w in lead for w in SCREEN_WORDS)


async def fetch_facts(imdb_id: str, lang: str) -> dict | None:
    titles = await _wikipedia_titles(imdb_id)
    for code in [lang] + [c for c in ("en", "fr") if c != lang]:
        if code not in titles:
            continue
        text = await _extract(code, titles[code])
        if is_game_article(text):
            continue
        sections = pick_sections(parse_sections(text), code)
        if sections:
            title = titles[code]
            return {
                "source": "Wikipedia",
                "lang": code,
                "fallback_language": code != lang,
                "title": title,
                "url": f"https://{code}.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}",
                "license": "CC BY-SA 4.0",
                "license_url": "https://creativecommons.org/licenses/by-sa/4.0/",
                "sections": sections,
            }
    return None


async def get_facts(db: Session, media_type: str, tmdb_id: int, imdb_id: str | None, lang: str) -> dict | None:
    """Cached facts (including 'no article' results). Network errors are not cached."""
    row = db.get(FactCache, (media_type, tmdb_id, lang))
    if row and row.refreshed_at > utcnow() - timedelta(days=config.FACTS_TTL_DAYS):
        return row.data.get("facts")
    if not imdb_id:
        return None
    try:
        facts = await fetch_facts(imdb_id, lang)
    except httpx.HTTPError:
        return row.data.get("facts") if row else None
    if row:
        row.data, row.refreshed_at = {"facts": facts}, utcnow()
    else:
        db.add(FactCache(media_type=media_type, tmdb_id=tmdb_id, lang=lang, data={"facts": facts}, refreshed_at=utcnow()))
    db.commit()
    return facts
