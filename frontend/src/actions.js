import { api } from './api.js'

export const EVT_SWIPE = 'debarras:swipe'
export const EVT_UNDO = 'debarras:undo'
export const EVT_REWATCH = 'debarras:rewatch'

const emit = (name, detail) => window.dispatchEvent(new CustomEvent(name, { detail }))

/** Save a decision and tell the rest of the app (deck, lists, counts) about it. */
export async function commitSwipe(status, item, source = 'deck') {
  const saved = await api.swipe({
    media_type: item.media_type,
    tmdb_id: item.tmdb_id,
    status,
    title: item.title || '',
    year: item.year || undefined,
    poster: item.poster || undefined,
    genre_ids: item.genre_ids?.length ? item.genre_ids : undefined,
    release_date: item.release_date || undefined,
  })
  emit(EVT_SWIPE, { status, item, source })
  return saved
}

/** Flag a Seen title as worth a rewatch, or clear the flag. */
export async function setRewatch(item, rewatch) {
  const saved = await api.setRewatch(item.media_type, item.tmdb_id, rewatch)
  emit(EVT_REWATCH, { item, rewatch })
  return saved
}

/** Delete a decision (undo, or "remove from my lists"). */
export async function removeSwipe(item) {
  await api.undo(item.media_type, item.tmdb_id)
  emit(EVT_UNDO, { item })
}

export const sameTitle = (a, b) => a.media_type === b.media_type && a.tmdb_id === b.tmdb_id
