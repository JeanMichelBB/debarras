import { useCallback, useEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'
import { base, listItem } from './motion.jsx'
import { api } from './api.js'
import { EVT_REWATCH, EVT_SWIPE, EVT_UNDO } from './actions.js'
import { fmtDate, isUpcoming } from './format.js'
import { Poster, Spinner } from './ui.jsx'
import { downloadBlob } from './RecoveryCodes.jsx'
import { loadListsPrefs, saveListsSort } from './storage.js'
import { useApp } from './ctx.jsx'

const CHIPS = ['all', 'want', 'watched', 'not_now']
const SORTS = ['recent', 'az', 'year']
const PAGE = 48

function ImportPanel({ onDone }) {
  const { t, notify, errorText } = useApp()
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('watched')
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const [trakt, setTrakt] = useState('')
  const [hasTrakt, setHasTrakt] = useState(false)
  const timer = useRef(null)

  useEffect(() => () => clearInterval(timer.current), [])
  useEffect(() => {
    api.importSources().then((r) => setHasTrakt(!!r.trakt)).catch(() => {})
  }, [])

  // One import job at a time, whatever the source: start it, then follow its progress.
  const run = async (begin) => {
    setBusy(true)
    setJob(null)
    try {
      const { job_id, total } = await begin()
      setJob({ status: 'running', total, done: 0 })
      timer.current = setInterval(async () => {
        try {
          const j = await api.importStatus(job_id)
          setJob(j)
          if (j.status !== 'running') {
            clearInterval(timer.current)
            setBusy(false)
            onDone()
          }
        } catch (e) {
          clearInterval(timer.current)
          setBusy(false)
          notify(errorText(e), 'error')
        }
      }, 1000)
    } catch (e) {
      setBusy(false)
      // The server explains a private or unknown Trakt profile; other errors get the usual text.
      notify(e?.status === 400 || e?.status === 503 ? e.message : errorText(e), 'error')
    }
  }

  return (
    <details className="import">
      <summary>{t('l_import_title')}</summary>
      <p>{t('l_import_body')}</p>
      <label className="filebtn">
        <input type="file" accept=".csv,text/csv" onChange={(e) => setFile(e.target.files?.[0] || null)} />
        <span>{file ? file.name : t('l_import_file')}</span>
      </label>
      <div className="seg">
        <span className="seg__label">{t('l_import_as')}</span>
        {['watched', 'want'].map((s) => (
          <button key={s} type="button" className={status === s ? 'on' : ''} onClick={() => setStatus(s)}>{t(`st_${s}`)}</button>
        ))}
      </div>
      <button type="button" className="btn btn--primary" disabled={!file || busy} onClick={() => run(() => api.startImport(file, status))}>{t('l_import_go')}</button>
      {hasTrakt && (
        <div className="import__trakt">
          <h3>{t('l_trakt_title')}</h3>
          <p>{t('l_trakt_body')}</p>
          <input type="text" value={trakt} onChange={(e) => setTrakt(e.target.value)} placeholder={t('l_trakt_user')} aria-label={t('l_trakt_user')} autoCapitalize="none" autoCorrect="off" spellCheck={false} />
          <button type="button" className="btn btn--ghost" disabled={!trakt.trim() || busy} onClick={() => run(() => api.startTraktImport(trakt.trim()))}>{t('l_trakt_go')}</button>
        </div>
      )}
      {job && job.status === 'running' && (
        <>
          <progress max={job.total} value={job.done} />
          <p className="muted">{t('l_import_progress', { done: job.done, total: job.total })}</p>
        </>
      )}
      {job?.status === 'done' && <p className="notice">{t('l_import_done', job)}</p>}
      {job?.status === 'failed' && <p className="notice notice--error">{t('l_import_failed', { error: job.error || '' })}</p>}
    </details>
  )
}

// Dev only: add ?loading to the address to hold the list skeleton for testing.
const HOLD_LOADING = import.meta.env.DEV && new URLSearchParams(window.location.search).has('loading')

export default function Lists({ openDetails, guest = false, onSave, onCollections }) {
  const { t, lang, notify, errorText } = useApp()
  const [chip, setChip] = useState('want') // opens on Want: that is the backlog
  const [rewatchOnly, setRewatchOnly] = useState(false)
  const [sort, setSort] = useState(() => (SORTS.includes(loadListsPrefs().sort) ? loadListsPrefs().sort : 'recent'))
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const gen = useRef(0)
  const countRef = useRef(0)
  countRef.current = items.length
  // A search always looks through every list, and shows the All chip while it does.
  const searching = dq !== ''
  const shown = searching ? 'all' : chip
  const status = shown === 'all' ? undefined : shown

  useEffect(() => {
    const id = setTimeout(() => setDq(q.trim()), 300)
    return () => clearTimeout(id)
  }, [q])

  const load = useCallback(
    async (reset) => {
      const my = ++gen.current
      setLoading(true)
      try {
        const res = await api.swipes({ status, q: dq, limit: PAGE, offset: reset ? 0 : countRef.current, sort, rewatch: rewatchOnly ? 'true' : '' })
        if (my !== gen.current) return
        setItems((cur) => (reset ? res.items : [...cur, ...res.items]))
        setTotal(res.total)
      } catch (e) {
        if (my === gen.current) notify(errorText(e), 'error')
      } finally {
        if (my === gen.current) setLoading(false)
      }
    },
    [status, dq, sort, rewatchOnly, notify, errorText],
  )

  const loadStats = useCallback(() => api.stats().then(setStats).catch(() => {}), [])

  useEffect(() => {
    load(true)
  }, [load])
  useEffect(() => {
    loadStats()
  }, [loadStats])

  useEffect(() => {
    const refresh = () => {
      load(true)
      loadStats()
    }
    window.addEventListener(EVT_SWIPE, refresh)
    window.addEventListener(EVT_UNDO, refresh)
    window.addEventListener(EVT_REWATCH, refresh)
    return () => {
      window.removeEventListener(EVT_SWIPE, refresh)
      window.removeEventListener(EVT_UNDO, refresh)
      window.removeEventListener(EVT_REWATCH, refresh)
    }
  }, [load, loadStats])

  const doExport = async () => {
    try {
      const which = rewatchOnly ? 'rewatch' : shown // the export follows what the list shows
      const { blob, missing } = await api.exportCsv(which)
      downloadBlob(blob, `debarras-${which}.csv`)
      notify(missing ? t('l_exported', { n: missing }) : t('l_exported_ok'))
    } catch (e) {
      notify(errorText(e), 'error')
    }
  }

  return (
    <section className="lists" aria-label={t('nav_lists')}>
      {guest && (
        <p className="guestbar">
          <span>{t('save_banner')}</span>
          <button type="button" className="linkbtn" onClick={onSave}>{t('save_banner_cta')}</button>
        </p>
      )}
      <button type="button" className="rowlink" onClick={onCollections}>
        <span>{t('nav_collections')}</span>
        <small>{t('c_intro')}</small>
      </button>
      <div className="tabs" role="tablist">
        {CHIPS.map((c) => {
          const n = stats ? (c === 'all' ? stats.want + stats.watched + stats.not_now : stats[c]) : null
          return (
            <button key={c} type="button" role="tab" aria-selected={shown === c} className={shown === c ? 'on' : ''} onClick={() => { setQ(''); setDq(''); setChip(c) }}>
              {t(c === 'all' ? 'l_all' : `st_${c}`)}
              {n != null && <span className="tabs__n">{n}</span>}
              {shown === c && <motion.span layoutId="lists-tab" className="tabs__bar" transition={base} />}
            </button>
          )
        })}
      </div>

      <div className="lists__tools">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('l_search')} aria-label={t('l_search')} />
        <select value={sort} aria-label={t('l_sort')} onChange={(e) => { saveListsSort(e.target.value); setSort(e.target.value) }}>
          {SORTS.map((s) => <option key={s} value={s}>{t(`l_sort_${s}`)}</option>)}
        </select>
        <button type="button" className="btn btn--ghost" onClick={doExport} disabled={!total}>{t('l_export')}</button>
      </div>
      {(rewatchOnly || (stats?.rewatch ?? 0) > 0) && (
        <div className="lists__filters">
          <button type="button" className={`chip rewatch${rewatchOnly ? ' on' : ''}`} aria-pressed={rewatchOnly} onClick={() => setRewatchOnly((v) => !v)}>
            {t('l_rewatch')}{stats ? ` ${stats.rewatch}` : ''}
          </button>
        </div>
      )}

      {items.length === 0 && !loading && !HOLD_LOADING && <p className="empty-note">{searching ? t('l_empty_search') : t('l_empty')}</p>}

      <ul className="grid">
        {!HOLD_LOADING && items.map((it, i) => (
          <motion.li key={`${it.media_type}:${it.tmdb_id}`} {...listItem(i % 24)}>
            <button type="button" className="tile" onClick={() => openDetails(it, it.status)} aria-label={it.title}>
              <Poster src={it.poster} title={it.title} />
              {it.status === 'watched' && it.rating === 3 && <span className="tile__loved" aria-hidden="true" />}
              {shown === 'all' && <span className={`tile__st tile__st--${it.status}`}>{t(`st_${it.status}`)}</span>}
              {it.rewatch && <span className="tile__again" title={t('d_rewatch')} aria-label={t('d_rewatch')}>↻</span>}
              {it.status === 'want' && isUpcoming(it.release_date) && <span className="tile__soon">{fmtDate(it.release_date, lang)}</span>}
              <span className="tile__title">{it.title}</span>
            </button>
          </motion.li>
        ))}
      </ul>

      {(HOLD_LOADING || (loading && items.length === 0)) && (
        <ul className="grid" role="status" aria-busy="true" aria-label={t('loading')}>
          {Array.from({ length: 9 }, (_, i) => <li key={i}><span className="sk sk--tile" /></li>)}
        </ul>
      )}
      {loading && items.length > 0 && <Spinner label={t('loading')} />}
      {!loading && items.length < total && (
        <button type="button" className="btn btn--ghost btn--block" onClick={() => load(false)}>{t('l_more')}</button>
      )}

      <ImportPanel onDone={() => { load(true); loadStats() }} />
    </section>
  )
}
