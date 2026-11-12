import { useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { Expandable, fadeUp, listItem, snap } from './motion.jsx'
import { api } from './api.js'
import { loadHistory, clearHistory } from './storage.js'
import { Poster, Sheet, Spinner } from './ui.jsx'
import { useApp } from './ctx.jsx'

/** Small icons of every sheet the user went through, joined by dashes. Tap one to jump back to it. */
export function Trail({ entries, onJump, onBack }) {
  const { t } = useApp()
  const last = entries.length - 1
  const row = useRef(null)
  useEffect(() => {
    row.current?.scrollTo({ left: row.current.scrollWidth, behavior: 'smooth' }) // keep the newest step in view
  }, [entries.length])
  return (
    <div className="trail" role="navigation" aria-label={t('sheet_back')}>
      <button type="button" className="trail__back" aria-label={t('sheet_back')} onClick={onBack}>
        <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M15 18l-6-6 6-6" /></svg>
      </button>
      <div className="trail__row" data-hscroll ref={row}>
        {entries.map((e, i) => (
          <motion.span key={i} className="trail__step" initial={{ opacity: 0, scale: 0.6 }} animate={{ opacity: 1, scale: 1 }} transition={snap}>
            {i > 0 && <span className="trail__dash" aria-hidden="true" />}
            <button type="button" className={`trail__node trail__node--${e.type}${i === last ? ' is-current' : ''}`} aria-label={e.name} title={e.name} onClick={() => i !== last && onJump(i)}>
              {e.icon ? <img src={e.icon} alt="" loading="lazy" /> : <span aria-hidden="true">{(e.name || '?').slice(0, 1)}</span>}
            </button>
          </motion.span>
        ))}
      </div>
    </div>
  )
}

function useLoad(load, key) {
  const [data, setData] = useState(null)
  const [failed, setFailed] = useState(false)
  const [tries, setTries] = useState(0)
  useEffect(() => {
    let live = true
    setData(null)
    setFailed(false)
    load().then((r) => live && setData(r)).catch(() => live && setFailed(true))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, tries])
  return { data, failed, retry: () => setTries((n) => n + 1) }
}

/** Row of posters; tapping one opens that title. */
export function TitleRow({ items, onOpen }) {
  return (
    <ul className="titlerow" data-hscroll>
      {items.map((it, i) => (
        <motion.li key={`${it.media_type}:${it.tmdb_id}`} {...listItem(i)}>
          <button type="button" className="tile" onClick={() => onOpen(it)} aria-label={it.title}>
            <Poster src={it.poster} title={it.title} />
            <span className="tile__title">{it.title}</span>
          </button>
        </motion.li>
      ))}
    </ul>
  )
}

export function PersonSheet({ person, onClose, onOpen, onMore, head, covered }) {
  const { t, lang } = useApp()
  const [full, setFull] = useState(false)
  const { data: p, failed, retry } = useLoad(() => api.person(person.id), person.id)
  const fmt = (d) => { try { return new Date(`${d}T00:00:00`).toLocaleDateString(lang, { year: 'numeric', month: 'long', day: 'numeric' }) } catch { return d } }
  const bio = p?.bio || ''
  const long = bio.length > 320
  return (
    <Sheet onClose={onClose} title={person.name} wide head={head} covered={covered}>
      <header className="detail__head">
        <div className="detail__poster detail__poster--person">
          {(p?.photo || person.photo) ? <img src={p?.photo || person.photo} alt="" /> : <Poster src={null} title={person.name} />}
        </div>
        <div>
          <h2 className="detail__title">{person.name}</h2>
          {p?.department && <p className="muted">{p.department}</p>}
          {p?.birthday && <p className="muted">{p.deathday ? `${fmt(p.birthday)} – ${fmt(p.deathday)}` : t('p_born', { date: fmt(p.birthday) })}</p>}
          {p?.place && <p className="muted small">{p.place}</p>}
        </div>
      </header>
      <button type="button" className="btn btn--primary btn--block" onClick={() => onMore(person)}>{t('d_more_from', { name: person.name })}</button>
      {failed && (
        <>
          <p className="notice notice--error">{t('d_load_failed')}</p>
          <button type="button" className="btn btn--ghost" onClick={retry}>{t('retry')}</button>
        </>
      )}
      {!p && !failed && <Spinner label={t('loading')} />}
      {p && (
        <>
          <motion.section className="block" {...fadeUp}>
            <Expandable open={full} collapsed={112}><p className="detail__overview">{bio || t('p_no_bio')}</p></Expandable>
            {long && <button type="button" className="linkbtn" onClick={() => setFull(!full)}>{full ? t('p_read_less') : t('p_read_more')}</button>}
          </motion.section>
          {p.known_for.length > 0 && (
            <motion.section className="block" {...fadeUp}>
              <h3>{t('p_known_for')}</h3>
              <TitleRow items={p.known_for} onOpen={onOpen} />
            </motion.section>
          )}
        </>
      )}
    </Sheet>
  )
}

export function HistorySheet({ onClose, onOpen, head, covered }) {
  const { t } = useApp()
  const [list, setList] = useState(loadHistory)
  const kind = (e) => (e.type === 'person' ? t('h_person') : e.type === 'company' ? t('h_studio') : [e.item.year, e.item.media_type === 'tv' ? t('type_tv') : t('type_movie')].filter(Boolean).join(' · '))
  return (
    <Sheet onClose={onClose} title={t('h_title')} head={head} covered={covered}>
      <h2 className="sheet__title">{t('h_title')}</h2>
      {list.length === 0 && <p className="muted">{t('h_empty')}</p>}
      <ul className="history">
        {list.map((e, i) => (
          <motion.li key={i} {...listItem(i)}>
            <button type="button" onClick={() => onOpen(e)}>
              <span className={`history__icon history__icon--${e.type}`}>
                {e.icon ? <img src={e.icon} alt="" loading="lazy" /> : <span aria-hidden="true">{(e.name || '?').slice(0, 1)}</span>}
              </span>
              <span className="history__text">
                <span>{e.name}</span>
                <small>{kind(e)}</small>
              </span>
            </button>
          </motion.li>
        ))}
      </ul>
      {list.length > 0 && (
        <button type="button" className="linkbtn" onClick={() => { clearHistory(); setList([]) }}>{t('h_clear')}</button>
      )}
    </Sheet>
  )
}
