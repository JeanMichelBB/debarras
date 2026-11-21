import { useEffect, useState } from 'react'
import { api } from './api.js'
import { Sheet, Spinner } from './ui.jsx'
import { useApp } from './ctx.jsx'

const TASTE_AT = 25

function Badges({ data }) {
  const { t } = useApp()
  if (!data) return null
  const name = (k) => t(`badge_${k.replace(/-/g, '_')}`)
  const hint = (k) => (['every-decade', 'rewatch-lover'].includes(k) ? t(`badge_${k.replace(/-/g, '_')}_hint`) : undefined)
  return (
    <section className="taste__block">
      <h3>{t('badges_title')}</h3>
      <ul className="marks">
        {data.badges.map((b) => (
          <li key={b.key} className={`mark${b.earned ? ' on' : ''}`} title={hint(b.key)}>
            <span>{name(b.key)}</span>
            {!b.earned && <small>{t('badge_progress', { have: b.have, need: b.need })}</small>}
          </li>
        ))}
        {data.collections.map((c) => (
          <li key={c.key} className="mark on"><span>{t('badge_collection', { name: c.name })}</span></li>
        ))}
      </ul>
    </section>
  )
}

/** What the user keeps, counted from their own swipes. Shown at 25 swipes, fuller at 100. */
export default function Taste({ onClose, onMore }) {
  const { t, lang } = useApp()
  const [d, setD] = useState(null)
  const [badges, setBadges] = useState(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    api.taste().then(setD).catch(() => setFailed(true))
    api.badges().then(setBadges).catch(() => {}) // marks are a bonus: the card works without them
  }, [])

  const top = d?.genres?.[0]?.n || 1
  return (
    <Sheet onClose={onClose} title={t('taste_title')}>
      <h2 className="sheet__title">{t('taste_title')}</h2>
      {!d && !failed && <Spinner label={t('loading')} />}
      {failed && <p className="notice notice--error">{t('error_generic')}</p>}
      {d && !d.ready && <p className="muted">{t('taste_locked', { n: TASTE_AT - d.count })}</p>}
      {d?.ready && (
        <div className="taste">
          <p className="muted">{t('taste_intro', { n: d.count })}</p>
          {d.genres.length > 0 && (
            <section className="taste__block">
              <h3>{t('taste_genres')}</h3>
              <ul className="taste__bars">
                {d.genres.map((g) => (
                  <li key={g.id}>
                    <span>{g.name}</span>
                    <i style={{ width: `${Math.max(12, (g.n / top) * 100)}%` }} />
                  </li>
                ))}
              </ul>
            </section>
          )}
          <dl className="taste__facts">
            {d.decade && (
              <div><dt>{t('taste_decade')}</dt><dd>{t('taste_decade_val', { decade: d.decade })}</dd></div>
            )}
            <div><dt>{t('taste_mix')}</dt><dd>{t('taste_mix_val', { movies: d.movies, tv: d.tv })}</dd></div>
            <div><dt>{t('taste_keep', { pct: d.keep_percent })}</dt></div>
          </dl>
          {d.full && d.people.length > 0 && (
            <section className="taste__block">
              <h3>{t('taste_people')}</h3>
              <dl className="taste__facts">
                {d.people.map((p) => (
                  <div key={p.role}><dt>{t(p.role === 'director' ? 'taste_director' : 'taste_actor')}</dt><dd>{p.name}</dd></div>
                ))}
              </dl>
            </section>
          )}
          <button type="button" className="btn btn--primary btn--block" onClick={onMore}>{t('taste_more')}</button>
        </div>
      )}
      <Badges data={badges} />
      <div className="actions">
        <button type="button" className="btn btn--ghost" onClick={onClose}>{t('taste_close')}</button>
      </div>
    </Sheet>
  )
}
