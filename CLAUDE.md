# CLAUDE.md

## Project Overview

Debarras ("clearout") is a web app to sort your movie and TV backlog by swiping cards:
right = watched, up = want to watch, left = not now, down = details. Lists export to IMDb as CSV.

Status: spec in progress. Use cases are being finalized; do not build features that are not listed under "Use cases".

## Constraints (decided)

- **Free, non-commercial.** The app uses the free TMDb API tier: no ads, no paid tier, no paywalled features.
  TMDb and JustWatch attribution must appear in the footer ("This product uses the TMDb API but is not endorsed or certified by TMDb").
- **Donations: undecided.** Do not add a donation link until TMDb confirms in writing that a donation-funded app with no revenue goal counts as non-commercial.
- **No LLM in the core.** Filtering uses TMDb `/discover` parameters; queue order and taste scoring are plain rules and SQL. No per-call paid services. An LLM natural-language search is a possible phase-3 option only.
- **Cache TMDb data and refresh it periodically** (`CACHE_TTL_DAYS`), because TMDb limits how long data may be kept.
- **The TMDb key stays on the backend** (Doppler secret `TMDB_API_KEY`). The frontend only calls this app's own `/api` endpoints.
- **Privacy (Quebec Law 25 / GDPR):** account deletion and data export must exist before a public launch.

## Stack

Same as PopRoom / Apercu / BotWhy:
- Frontend: React + Vite (`/frontend`), nginx image, port 3002
- Backend: FastAPI + SQLAlchemy + pymysql (`/backend`), port 8002
- Database: shared MySQL in the cluster, database `debarras` (create by hand, see `sql/init.sql`)
- Deploy: Docker Hub images `jeanmichelbb/debarras-fe` and `-be`, Kustomize in `/k3s`, ArgoCD Image Updater, Doppler secrets, Traefik ingress, Cloudflare. Hosts: `debarras.sacenpapier.org` and `debarrasapi.sacenpapier.org`.

## Use cases (draft, to confirm)

Phase 1
1. Swipe right (watched), up (want), left (not now), down (details).
2. After "watched", one-tap rating: loved / fine / disliked.
3. Undo, and edit any past decision.
4. Queue order: finish franchise, then same director, then lead actors, then trending.
5. Bulk action: mark a whole franchise watched.
6. Filters: movie/TV, genre, year, minimum rating.
7. TV progress: all watched / some seasons / dropped.
8. Detail sheet: description, trailer, ratings, cast, reviews, where to watch, more by this director/actor, "Behind the scenes" facts from Wikipedia (e.g. why a series' second season changed).
9. Import an IMDb ratings or watchlist CSV (skip what is already decided).
10. Export one CSV per bucket for IMDb list import.
11. Accounts, account deletion, data export. Sign-up (decided): passkey-only (WebAuthn), no email or phone, with a one-time recovery code shown at sign-up and the option to add more passkeys. Passkeys are bound to the domain, so do not change `debarras.sacenpapier.org` after launch. The draft email/password `backend/auth.py` is obsolete and must be rewritten. Onboarding is optional: "Help us find your filters" (movie/TV, genres) or "Skip and start swiping" (skip is the default action).

11b. User trivia: signed-in users submit short facts (max ~280 chars) about a title, in FR or EN. Others upvote or report them. Shown in the detail sheet under "Behind the scenes", above the Wikipedia excerpt, ordered by votes.
   - Moderation: new facts are visible only after approval (admin queue) until a user has 3 approved facts, then they post directly. 3 reports hide a fact pending review. Per-user rate limit on submissions.
   - Source field is optional (link); no HTML, no links other than the source field.
   - Rules: users keep authorship but grant the app a license to display it; deleting an account deletes its trivia (or anonymizes it, to be decided).

Phase 2
12. Taste profile from director / actor / genre / keyword weights.
13. "Not now" titles resurface when they match the taste profile, with a "because you liked..." reason.
14. Tonight's pick from the want list (runtime, mood, streaming service).
15. Availability alerts, shared list with a partner, taste stats.

Decided:
- **Languages: French and English. Default English, no auto-detection; the user switches only in Settings.** UI is translated (i18n); TMDb requests use the user's language (`fr-CA` / `en-US`); fun facts fall back to English when the French article is missing.
- **Fun facts: "Behind the scenes" from Wikipedia, no LLM.** IMDb ID -> Wikidata (P345) -> en/fr Wikipedia article -> excerpt of the Production / Development / Casting / Reception sections, with a "read more" link. Wikipedia text is CC BY-SA: credit Wikipedia and link the article. Titles without an article show nothing.

## Version 1 scope (build first, then iterate)

In: passkey sign-up, FR/EN UI, optional onboarding, swipe (watched / want / not now) with undo, queue (franchise, director, cast, trending), filters (movie/TV, genre, year, rating), detail sheet (description, trailer, ratings, cast, where to watch, Wikipedia "Behind the scenes"), IMDb CSV import, CSV export per bucket, bucket browsing, account deletion and data export, attribution footer.

Out until v1 is used: user trivia, one-tap rating after "watched", franchise bulk action, TV season progress, all phase-2 items.

## API call strategy (TMDb, Wikidata, Wikipedia)

Principle: cache first, fetch lazily, prefetch gradually. TMDb's old per-key limit was removed in 2019; a soft ceiling of about 40 requests/second remains, enforced per IP (not per API key), and over-limit calls get HTTP 429. All users share the cluster's IP budget, so the limiter must be global. Stay far below it.
- `append_to_response` accepts up to 20 sub-requests (forum statement, not official docs): use one details call per title instead of several.
- Cache keys include the language (`lang`): French overviews are often empty, so fall back to `en-US` for missing fields and cache each language separately.
- Refresh cached titles using TMDb's `/movie/changes` and `/tv/changes` (once a day) instead of only a blind TTL; TTL stays as a fallback. (From memory: confirm in the TMDb docs before building.)

1. **Cards come from list endpoints** (discover, trending, collection, person credits, recommendations). They already return title, poster and overview, so no per-card details call.
2. **Details only when needed:** the detail sheet (swipe down) fetches `/{type}/{id}` with `append_to_response` in one call. After a short idle delay the app may prefetch details for the top card only.
3. **`imdb_id` is resolved lazily,** at export time or by a background job, not on every swipe. IDs never change, so they are cached forever.
4. **Cache layers:** in-memory TTL for hot lists (trending 1h, person credits and collections 24h-7d); MySQL `title_cache` for details (refresh after `CACHE_TTL_DAYS`); posters load straight from TMDb's image CDN (not counted against the API). Wikidata and Wikipedia results are cached for weeks.
5. **Shared cache:** one cache serves all users, so popular titles are fetched once and the hit rate rises with usage.
6. **Single-flight:** concurrent requests for the same key share one upstream call.
7. **Global rate limiter** (token bucket, well under TMDb's limit) with backoff on 429. If TMDb errors, serve stale cache instead of failing.
8. **Queue paging:** return 10-20 cards at a time; the frontend asks for the next batch when 5 remain.
9. **Imports run as a background job** with bounded concurrency (about 10-20 parallel `/find` calls), resumable, with progress shown. 1,000 rows should take about a minute.
10. **Wikipedia and Wikidata:** lazy (only when the sheet opens), with a proper User-Agent, and negative results cached too ("no article").

## Swipe states

| Status    | Gesture | Meaning                          | Resurfaces?        |
|-----------|---------|----------------------------------|--------------------|
| watched   | right   | seen it (optional rating 1-3)    | no                 |
| want      | up      | on my watchlist                  | no                 |
| not_now   | left    | don't know it / not now          | yes, in phase 2    |

## Data model (draft)

`users` (no email or phone), `passkeys` (credential_id, public_key, sign_count), `recovery_codes` (hashed, used_at), `title_cache` (slimmed TMDb JSON per title and language, with refreshed_at; key = media_type, tmdb_id, lang), `user_titles`
(user, media_type, tmdb_id, imdb_id, title, year, poster, status, rating, decided_at),
`trivia` (media_type, tmdb_id, user_id, lang, text, source_url, status pending/approved/hidden, created_at),
`trivia_votes` (trivia_id, user_id, unique), `trivia_reports` (trivia_id, user_id, reason, unique),
and in phase 2 a `taste_weights` table.

IMDb has no write API: the user imports the exported CSV into an IMDb custom list by hand.
