import { useEffect, useMemo, useState } from 'react'
import { api } from './api.js'
import { EMPTY_FILTERS } from './swipeLogic.js'
import { Sheet } from './ui.jsx'
import { useApp } from './ctx.jsx'

/** Merge TMDb's movie and TV genre lists by id. */
export function mergeGenres(g) {
  const map = new Map()
  for (const x of [...(g?.movie || []), ...(g?.tv || [])]) if (!map.has(x.id)) map.set(x.id, x.name)
  return [...map].map(([id, name]) => ({ id, name })).sort((a, b) => a.name.localeCompare(b.name))
}

export function useGenres() {
  const { lang } = useApp()
  const [genres, setGenres] = useState([])
  useEffect(() => {
    let live = true
    api.genres().then((g) => live && setGenres(mergeGenres(g))).catch(() => {})
    return () => {
      live = false
    }
  }, [lang])
  return genres
}

export default function FiltersPanel({ value, onApply, onClose }) {
  const { t } = useApp()
  const genres = useGenres()
  const [f, setF] = useState(value)
  const years = useMemo(() => {
    const now = new Date().getFullYear()
    return Array.from({ length: now - 1929 }, (_, i) => String(now - i))
  }, [])
  const set = (patch) => setF((p) => ({ ...p, ...patch }))
  const toggleGenre = (id) =>
    set({ genres: f.genres.includes(id) ? f.genres.filter((g) => g !== id) : [...f.genres, id] })

  return (
    <Sheet onClose={onClose} title={t('filters')}>
      <h2 className="sheet__title">{t('filters')}</h2>

      <fieldset className="field">
        <legend>{t('f_type')}</legend>
        <div className="seg">
          {['all', 'movie', 'tv'].map((m) => (
            <button key={m} type="button" className={f.media_type === m ? 'on' : ''} onClick={() => set({ media_type: m })}>
              {t(`type_${m}`)}
            </button>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend>{t('f_genres')}</legend>
        <div className="chips">
          {genres.map((g) => (
            <button
              key={g.id}
              type="button"
              className={`chip ${f.genres.includes(g.id) ? 'on' : ''}`}
              aria-pressed={f.genres.includes(g.id)}
              onClick={() => toggleGenre(g.id)}
            >
              {g.name}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="field-row">
        <label className="field">
          <span>{t('f_year_from')}</span>
          <select value={f.year_min} onChange={(e) => set({ year_min: e.target.value })}>
            <option value="">{t('f_any')}</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label className="field">
          <span>{t('f_year_to')}</span>
          <select value={f.year_max} onChange={(e) => set({ year_max: e.target.value })}>
            <option value="">{t('f_any')}</option>
            {years.map((y) => <option key={y} value={y}>{y}</option>)}
          </select>
        </label>
        <label className="field">
          <span>{t('f_rating')}</span>
          <select value={f.min_rating} onChange={(e) => set({ min_rating: e.target.value })}>
            <option value="">{t('f_any')}</option>
            {[5, 6, 7, 8].map((r) => <option key={r} value={r}>{r}+</option>)}
          </select>
        </label>
      </div>

      <div className="actions">
        <button type="button" className="btn btn--ghost" onClick={() => setF({ ...EMPTY_FILTERS })}>{t('f_reset')}</button>
        <button type="button" className="btn btn--primary" onClick={() => onApply(f)}>{t('f_apply')}</button>
      </div>
    </Sheet>
  )
}
