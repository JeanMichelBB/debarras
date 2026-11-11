import { api } from './api.js'

export const EVT_SWIPE = 'debarras:swipe'
export const EVT_UNDO = 'debarras:undo'

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
  })
  emit(EVT_SWIPE, { status, item, source })
  return saved
}

/** Delete a decision (undo, or "remove from my lists"). */
export async function removeSwipe(item) {
  await api.undo(item.media_type, item.tmdb_id)
  emit(EVT_UNDO, { item })
}

export const sameTitle = (a, b) => a.media_type === b.media_type && a.tmdb_id === b.tmdb_id
