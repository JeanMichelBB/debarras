import { useState } from 'react'
import { EMPTY_FILTERS } from './swipeLogic.js'
import { markOnboarded, saveFilters } from './storage.js'
import { useGenres } from './FiltersPanel.jsx'
import { useApp } from './ctx.jsx'

/** Optional. "Skip and start swiping" is always one tap away. */
export default function Onboarding({ onDone }) {
  const { t } = useApp()
  const genres = useGenres()
  const [media, setMedia] = useState('all')
  const [picked, setPicked] = useState([])

  const finish = (save) => {
    if (save) saveFilters({ ...EMPTY_FILTERS, media_type: media, genres: picked })
    markOnboarded()
    onDone()
  }
  const toggle = (id) => setPicked((p) => (p.includes(id) ? p.filter((g) => g !== id) : [...p, id]))

  return (
    <main className="onboarding">
      <h1>{t('onb_title')}</h1>
      <p>{t('onb_body')}</p>

      <fieldset className="field">
        <legend>{t('onb_type')}</legend>
        <div className="seg">
          {['all', 'movie', 'tv'].map((m) => (
            <button key={m} type="button" className={media === m ? 'on' : ''} onClick={() => setMedia(m)}>{t(`type_${m}`)}</button>
          ))}
        </div>
      </fieldset>

      <fieldset className="field">
        <legend>{t('onb_genres')}</legend>
        <div className="chips">
          {genres.map((g) => (
            <button key={g.id} type="button" className={`chip ${picked.includes(g.id) ? 'on' : ''}`} aria-pressed={picked.includes(g.id)} onClick={() => toggle(g.id)}>
              {g.name}
            </button>
          ))}
        </div>
      </fieldset>

      <div className="onboarding__actions">
        <button type="button" className="btn btn--primary btn--block" onClick={() => finish(true)}>{t('onb_start')}</button>
        <button type="button" className="linkbtn" onClick={() => finish(false)}>{t('onb_skip')}</button>
      </div>
    </main>
  )
}
