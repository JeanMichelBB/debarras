// Pure swipe rules, kept free of React so they can be unit tested.

export const THRESHOLD = 110 // px of drag needed to commit
export const PREVIEW = 48 // px of drag before the stamp starts to show

export const STATUSES = ['watched', 'want', 'not_now']

/** Where a committed card flies to, per decision. */
export const FLY = {
  watched: { x: 620, y: 40 },
  want: { x: 0, y: -760 },
  not_now: { x: -620, y: 40 },
}

/**
 * Map a drag offset to a decision.
 * right = watched, up = want, left = not_now, down = details.
 * The dominant axis wins, so a diagonal drag does one thing, not two.
 * Returns null when the drag is too short.
 */
export function decide({ x, y }, threshold = THRESHOLD) {
  if (Math.abs(x) >= Math.abs(y)) {
    if (x >= threshold) return 'watched'
    if (x <= -threshold) return 'not_now'
    return null
  }
  if (y <= -threshold) return 'want'
  if (y >= threshold) return 'details'
  return null
}

/** Offset plus a little of the release velocity, so a quick flick counts. */
export function withMomentum(offset, velocity, factor = 0.15) {
  return { x: offset.x + velocity.x * factor, y: offset.y + velocity.y * factor }
}

const KEYS = {
  ArrowRight: 'watched',
  ArrowUp: 'want',
  ArrowLeft: 'not_now',
  ArrowDown: 'details',
}

export function decisionForKey(key) {
  return KEYS[key] ?? null
}

/** Query-string params for /titles/queue from the saved filter state. */
export function filterParams(f) {
  const p = {}
  if (f.media_type && f.media_type !== 'all') p.media_type = f.media_type
  if (f.genres?.length) p.genres = f.genres.join(',')
  if (f.year_min) p.year_min = f.year_min
  if (f.year_max) p.year_max = f.year_max
  if (f.min_rating) p.min_rating = f.min_rating
  return p
}

export const EMPTY_FILTERS = { media_type: 'all', genres: [], year_min: '', year_max: '', min_rating: '' }

export function countActiveFilters(f) {
  return (
    (f.media_type && f.media_type !== 'all' ? 1 : 0) +
    (f.genres?.length || 0) +
    (f.year_min ? 1 : 0) +
    (f.year_max ? 1 : 0) +
    (f.min_rating ? 1 : 0)
  )
}
