import { useCallback, useEffect, useState } from 'react'
import { api } from './api.js'
import { EVT_SWIPE, EVT_UNDO } from './actions.js'
import { Poster, Spinner } from './ui.jsx'
import { useApp } from './ctx.jsx'

function Bar({ seen, total }) {
  return <span className="colbar" role="presentation"><i style={{ width: `${total ? (seen / total) * 100 : 0}%` }} /></span>
}

function Detail({ id, onBack, openDetails }) {
  const { t, notify, errorText } = useApp()
  const [d, setD] = useState(null)
  const load = useCallback(() => api.collection(id).then(setD).catch((e) => notify(errorText(e), 'error')), [id, notify, errorText])
  useEffect(() => {
    load()
    window.addEventListener(EVT_SWIPE, load)
    window.addEventListener(EVT_UNDO, load)
    return () => {
      window.removeEventListener(EVT_SWIPE, load)
      window.removeEventListener(EVT_UNDO, load)
    }
  }, [load])

  if (!d) return <Spinner label={t('loading')} />
  return (
    <>
      <button type="button" className="linkbtn" onClick={onBack}>{t('back')}</button>
      <h2 className="sheet__title">{d.name}</h2>
      <p className="muted">{t('c_progress', { seen: d.seen, total: d.total })}</p>
      <Bar seen={d.seen} total={d.total} />
      <ul className="grid">
        {d.items.map((it) => (
          <li key={it.tmdb_id}>
            <button type="button" className={`tile${it.released ? '' : ' tile--dim'}`} onClick={() => openDetails(it, it.status)} aria-label={it.title}>
              <Poster src={it.poster} title={it.title} />
              {it.status && <span className={`tile__st tile__st--${it.status}`}>{t(`st_${it.status}`)}</span>}
              {!it.released && <span className="tile__soon">{t('c_not_out')}</span>}
              <span className="tile__title">{it.title}{it.year ? ` (${it.year})` : ''}</span>
            </button>
          </li>
        ))}
      </ul>
    </>
  )
}

/** Franchises with progress, such as "7 of 33 seen". */
export default function Collections({ openDetails }) {
  const { t, notify, errorText } = useApp()
  const [rows, setRows] = useState(null)
  const [open, setOpen] = useState(null)

  useEffect(() => {
    let live = true
    api.collections().then((r) => live && setRows(r.collections)).catch((e) => { if (live) { setRows([]); notify(errorText(e), 'error') } })
    return () => { live = false }
  }, [open, notify, errorText]) // coming back from a franchise refreshes the progress

  if (open) return <Detail id={open} onBack={() => setOpen(null)} openDetails={openDetails} />
  return (
    <section className="collections" aria-label={t('nav_collections')}>
      <p className="muted">{t('c_intro')}</p>
      {!rows && <Spinner label={t('loading')} />}
      {rows?.length === 0 && <p className="empty-note">{t('c_empty')}</p>}
      <ul className="colls">
        {rows?.map((c) => (
          <li key={c.key}>
            <button type="button" className="colls__row" onClick={() => setOpen(c.key)}>
              <span className="colls__poster"><Poster src={c.poster} title={c.name} /></span>
              <span className="colls__text">
                <strong>{c.name}</strong>
                <small>{c.complete ? t('c_complete') : t('c_progress', { seen: c.seen, total: c.total })}</small>
                <Bar seen={c.seen} total={c.total} />
              </span>
            </button>
          </li>
        ))}
      </ul>
    </section>
  )
}
