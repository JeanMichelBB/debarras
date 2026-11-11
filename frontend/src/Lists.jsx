import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from './api.js'
import { EVT_SWIPE, EVT_UNDO } from './actions.js'
import { Poster, Spinner, Stamp } from './ui.jsx'
import { downloadBlob } from './RecoveryCodes.jsx'
import { useApp } from './ctx.jsx'

const TABS = ['watched', 'want', 'not_now']
const PAGE = 48

function ImportPanel({ onDone }) {
  const { t, notify, errorText } = useApp()
  const [file, setFile] = useState(null)
  const [status, setStatus] = useState('watched')
  const [job, setJob] = useState(null)
  const [busy, setBusy] = useState(false)
  const timer = useRef(null)

  useEffect(() => () => clearInterval(timer.current), [])

  const start = async () => {
    if (!file) return
    setBusy(true)
    setJob(null)
    try {
      const { job_id, total } = await api.startImport(file, status)
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
      notify(errorText(e), 'error')
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
      <button type="button" className="btn btn--primary" disabled={!file || busy} onClick={start}>{t('l_import_go')}</button>
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

export default function Lists({ openDetails }) {
  const { t, notify, errorText } = useApp()
  const [tab, setTab] = useState('watched')
  const [q, setQ] = useState('')
  const [dq, setDq] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(true)
  const gen = useRef(0)
  const countRef = useRef(0)
  countRef.current = items.length

  useEffect(() => {
    const id = setTimeout(() => setDq(q.trim()), 300)
    return () => clearTimeout(id)
  }, [q])

  const load = useCallback(
    async (reset) => {
      const my = ++gen.current
      setLoading(true)
      try {
        const res = await api.swipes({ status: tab, q: dq, limit: PAGE, offset: reset ? 0 : countRef.current })
        if (my !== gen.current) return
        setItems((cur) => (reset ? res.items : [...cur, ...res.items]))
        setTotal(res.total)
      } catch (e) {
        if (my === gen.current) notify(errorText(e), 'error')
      } finally {
        if (my === gen.current) setLoading(false)
      }
    },
    [tab, dq, notify, errorText],
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
    return () => {
      window.removeEventListener(EVT_SWIPE, refresh)
      window.removeEventListener(EVT_UNDO, refresh)
    }
  }, [load, loadStats])

  const doExport = async () => {
    try {
      const { blob, missing } = await api.exportCsv(tab)
      downloadBlob(blob, `debarras-${tab}.csv`)
      notify(missing ? t('l_exported', { n: missing }) : t('l_exported_ok'))
    } catch (e) {
      notify(errorText(e), 'error')
    }
  }

  return (
    <section className="screen lists" aria-label={t('nav_lists')}>
      <div className="tabs" role="tablist">
        {TABS.map((s) => (
          <button key={s} type="button" role="tab" aria-selected={tab === s} className={tab === s ? 'on' : ''} onClick={() => setTab(s)}>
            {t(`l_${s}`)}
            {stats && <span className="tabs__n">{stats[s]}</span>}
          </button>
        ))}
      </div>

      <div className="lists__tools">
        <input type="search" value={q} onChange={(e) => setQ(e.target.value)} placeholder={t('l_search')} aria-label={t('l_search')} />
        <button type="button" className="btn btn--ghost" onClick={doExport} disabled={!total}>{t('l_export')}</button>
      </div>
      {total > 0 && <p className="muted small">{t('l_total', { n: total })}. {t('l_export_help')}</p>}

      {items.length === 0 && !loading && <p className="empty-note">{t('l_empty')}</p>}

      <ul className="grid">
        {items.map((it) => (
          <li key={`${it.media_type}:${it.tmdb_id}`}>
            <button type="button" className="tile" onClick={() => openDetails(it, it.status)} aria-label={it.title}>
              <Poster src={it.poster} title={it.title} />
              {it.status === 'watched' && it.rating === 3 && <span className="tile__loved" aria-hidden="true" />}
              <span className="tile__title">{it.title}</span>
              {tab !== it.status && <Stamp status={it.status} className="tile__stamp" />}
            </button>
          </li>
        ))}
      </ul>

      {loading && <Spinner label={t('loading')} />}
      {!loading && items.length < total && (
        <button type="button" className="btn btn--ghost btn--block" onClick={() => load(false)}>{t('l_more')}</button>
      )}

      <ImportPanel onDone={() => { load(true); loadStats() }} />
    </section>
  )
}
