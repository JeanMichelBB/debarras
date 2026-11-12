import { useEffect, useState } from 'react'
import { api } from './api.js'
import { commitSwipe, removeSwipe } from './actions.js'
import { Poster, Sheet, Spinner } from './ui.jsx'
import { motion } from 'framer-motion'
import { Expandable, fadeUp } from './motion.jsx'
import { TitleRow } from './Explore.jsx'
import { useApp } from './ctx.jsx'

const PROVIDER_GROUPS = [
  ['flatrate', 'd_stream'],
  ['free', 'd_free'],
  ['ads', 'd_ads'],
  ['rent', 'd_rent'],
  ['buy', 'd_buy'],
]
const REVIEW_PREVIEW = 280

// TMDb gives one JustWatch page per title and region, not a link per service.
const safeLink = (url) => (typeof url === 'string' && /^https:\/\/([a-z0-9-]+\.)?(themoviedb\.org|justwatch\.com)\//.test(url) ? url : null)

function Providers({ providers, region }) {
  const { t } = useApp()
  const link = safeLink(providers?.link)
  const groups = providers ? PROVIDER_GROUPS.filter(([k]) => providers[k]?.length) : []
  return (
    <motion.section className="block" {...fadeUp}>
      <h3>{t('d_where', { region })}</h3>
      {groups.length === 0 ? (
        <p className="muted">{t('d_no_providers', { region })}</p>
      ) : (
        groups.map(([kind, label]) => (
          <div key={kind} className="providers">
            <span className="providers__label">{t(label)}</span>
            <ul>
              {providers[kind].map((p) => (
                <li key={p.name} title={p.name}>
                  {link ? (
                    <a href={link} target="_blank" rel="noopener noreferrer" aria-label={`${p.name} (${t('d_open_new')})`}>
                      {p.logo ? <img src={p.logo} alt="" loading="lazy" /> : p.name}
                    </a>
                  ) : p.logo ? <img src={p.logo} alt={p.name} loading="lazy" /> : p.name}
                </li>
              ))}
            </ul>
          </div>
        ))
      )}
      {link && (
        <a className="linkbtn" href={link} target="_blank" rel="noopener noreferrer">{t('d_watch_link')}</a>
      )}
      <p className="muted small">{t('d_providers_credit')}</p>
    </motion.section>
  )
}

function Person({ p, onPerson }) {
  return (
    <li className="person">
      <button type="button" className="person__btn" onClick={() => onPerson(p)}>
        <span className="person__photo">
          {p.photo ? <img src={p.photo} alt="" loading="lazy" /> : <span aria-hidden="true">{p.name.slice(0, 1)}</span>}
        </span>
        <span className="person__name">{p.name}</span>
        {p.role && <span className="person__role">{p.role}</span>}
      </button>
    </li>
  )
}

/** Directors and creators first, then the main cast, as a row of photos. */
function People({ d, onPerson }) {
  const { t } = useApp()
  const seen = new Set()
  const people = []
  for (const c of d.crew || []) {
    if ((c.job === 'Director' || c.job === 'Creator') && !seen.has(c.id)) {
      seen.add(c.id)
      people.push({ ...c, role: t(c.job === 'Director' ? 'role_director' : 'role_creator') })
    }
  }
  for (const c of (d.cast || []).slice(0, 12)) {
    if (!seen.has(c.id)) {
      seen.add(c.id)
      people.push({ ...c, role: c.character })
    }
  }
  if (people.length === 0) return null
  return (
    <motion.section className="block" {...fadeUp}>
      <h3>{t('d_cast')}</h3>
      <ul className="people" data-hscroll>
        {people.map((p) => <Person key={p.id} p={p} onPerson={onPerson} />)}
      </ul>
    </motion.section>
  )
}

/** Studios behind the title. Tap one to see its popular titles right here, or to build a pile from it. */
function Studios({ companies, onOpen, onMore }) {
  const { t } = useApp()
  const [sel, setSel] = useState(null)
  const [info, setInfo] = useState(null)
  useEffect(() => {
    if (!sel) return undefined
    let live = true
    setInfo(null)
    api.company(sel.id).then((r) => live && setInfo(r)).catch(() => live && setInfo(false))
    return () => { live = false }
  }, [sel])
  if (!companies?.length) return null
  return (
    <motion.section className="block" {...fadeUp}>
      <h3>{t('d_studio')}</h3>
      <ul className="studios">
        {companies.map((c) => (
          <li key={c.id}>
            <button type="button" className={`studio${sel?.id === c.id ? ' on' : ''}`} aria-pressed={sel?.id === c.id} onClick={() => setSel(sel?.id === c.id ? null : c)}>
              {c.logo ? <img src={c.logo} alt="" loading="lazy" /> : null}
              <span>{c.name}</span>
            </button>
          </li>
        ))}
      </ul>
      {sel && info === null && <Spinner label={t('loading')} />}
      {sel && info && (
        <>
          <p className="muted">{t('d_studio_titles', { name: sel.name })}</p>
          <TitleRow items={info.titles} onOpen={onOpen} />
          <button type="button" className="btn btn--ghost btn--block" onClick={() => onMore(sel)}>{t('d_more_from', { name: sel.name })}</button>
        </>
      )}
      {sel && info === false && <p className="muted">{t('d_load_failed')}</p>}
    </motion.section>
  )
}

function Facts({ facts }) {
  const { t } = useApp()
  return (
    <motion.section className="block" {...fadeUp}>
      <h3>{t('d_facts')}</h3>
      {facts === undefined && <Spinner label={t('loading')} />}
      {facts === null && <p className="muted">{t('d_facts_none')}</p>}
      {facts &&
        facts.sections.map((s) => (
          <div key={s.heading} className="fact">
            <h4>{s.heading}</h4>
            <p>{s.text}</p>
          </div>
        ))}
      {facts && (
        <p className="muted small">
          <a href={facts.url} target="_blank" rel="noreferrer">{t('d_facts_source')}</a>
          {facts.fallback_language ? ` ${t('d_facts_fallback')}` : ''}
        </p>
      )}
    </motion.section>
  )
}

function Review({ r }) {
  const { t } = useApp()
  const [open, setOpen] = useState(false)
  const long = r.content.length > REVIEW_PREVIEW
  return (
    <blockquote className="review">
      <Expandable open={open} collapsed={96}><p>{r.content}</p></Expandable>
      <footer>
        {r.author}
        {r.rating ? `, ${r.rating}/10` : ''}
        {long && (
          <button type="button" className="linkbtn" onClick={() => setOpen(!open)}>{open ? t('d_less') : t('d_more')}</button>
        )}
      </footer>
    </blockquote>
  )
}

export default function DetailSheet({ item, status, onClose, onSimilar, onPerson, onCompany, onOpen, head, covered }) {
  const { t, notify, errorText } = useApp()
  const [d, setD] = useState(null)
  const [facts, setFacts] = useState(undefined)
  const [failed, setFailed] = useState(false)
  const [trailer, setTrailer] = useState(false)
  const [busy, setBusy] = useState(false)

  const [tries, setTries] = useState(0) // bumped by "Try again"

  useEffect(() => {
    let live = true
    let timer
    setD(null)
    setFacts(undefined)
    setFailed(false)
    // A one-off network or TMDb hiccup should not show an error: retry once quietly first.
    const loadDetails = (retriesLeft) =>
      api.details(item.media_type, item.tmdb_id)
        .then((r) => live && setD(r))
        .catch((e) => {
          if (!live) return
          if (retriesLeft > 0 && e?.code !== 'session') timer = setTimeout(() => loadDetails(retriesLeft - 1), 700)
          else setFailed(true)
        })
    loadDetails(1)
    api.facts(item.media_type, item.tmdb_id)
      .then((r) => live && setFacts(r.facts))
      .catch(() => live && setFacts(null))
    return () => {
      live = false
      clearTimeout(timer)
    }
  }, [item.media_type, item.tmdb_id, tries])

  const act = async (next) => {
    setBusy(true)
    try {
      await commitSwipe(next, item, 'sheet')
      onClose()
    } catch (e) {
      notify(errorText(e, 'save_failed'), 'error')
    } finally {
      setBusy(false)
    }
  }
  const remove = async () => {
    setBusy(true)
    try {
      await removeSwipe(item)
      onClose()
    } catch (e) {
      notify(errorText(e, 'save_failed'), 'error')
    } finally {
      setBusy(false)
    }
  }

  const cur = d ? d.my_status : status // the server knows the saved status even when the sheet was opened from history
  const runtime = d?.runtime ? t('d_runtime', { n: d.runtime }) : null
  const seasons = d?.number_of_seasons ? (d.number_of_seasons === 1 ? t('d_season') : t('d_seasons', { n: d.number_of_seasons })) : null
  const director = d?.crew?.filter((c) => c.job === 'Director').map((c) => c.name)
  const creator = d?.crew?.filter((c) => c.job === 'Creator').map((c) => c.name)
  const trailerKey = d?.videos?.[0]?.key

  return (
    <Sheet onClose={onClose} title={item.title} wide head={head} covered={covered}>
      <header className="detail__head">
        <div className="detail__poster"><Poster src={item.poster} title={item.title} eager /></div>
        <div>
          <h2 className="detail__title">{item.title}</h2>
          <p className="detail__facts">
            {(d?.year || item.year) && <span>{d?.year || item.year}</span>}
            <span>{item.media_type === 'tv' ? t('type_tv') : t('type_movie')}</span>
            {runtime && <span>{runtime}</span>}
            {seasons && <span>{seasons}</span>}
            {d?.vote_average ? <span>{d.vote_average.toFixed(1)} / 10</span> : null}
          </p>
          {d?.genres?.length > 0 && <p className="muted">{d.genres.map((g) => g.name).join(', ')}</p>}
          {director?.length > 0 && <p className="muted">{t('d_director')} {director.join(', ')}</p>}
          {creator?.length > 0 && <p className="muted">{t('d_creator')} {creator.join(', ')}</p>}
        </div>
      </header>

      <div className="detail__actions">
        {['not_now', 'want', 'watched'].map((s) => (
          <button
            key={s}
            type="button"
            className={`stampbtn stampbtn--${s} ${cur === s ? 'is-current' : ''}`}
            aria-pressed={cur === s}
            disabled={busy}
            onClick={() => act(s)}
          >
            {t(`st_${s}`)}
          </button>
        ))}
      </div>
      <button type="button" className="btn btn--ghost btn--block btn--withicon" onClick={() => onSimilar(item)}>
        <span>{t('d_similar')}</span>
        <img src="/logo-mark-2.svg" alt="" />
      </button>
      {cur && (
        <button type="button" className="linkbtn" disabled={busy} onClick={remove}>{t('d_remove')}</button>
      )}

      {failed && (
        <>
          <p className="notice notice--error">{t('d_load_failed')}</p>
          <button type="button" className="btn btn--ghost" onClick={() => setTries((n) => n + 1)}>{t('retry')}</button>
        </>
      )}
      {!d && !failed && <Spinner label={t('loading')} />}

      {d && (
        <>
          {d.tagline && <p className="detail__tagline">{d.tagline}</p>}
          {d.overview && <p className="detail__overview">{d.overview}</p>}

          {trailerKey && (
            <motion.section className="block" {...fadeUp}>
              {trailer ? (
                <div className="trailer">
                  <iframe
                    src={`https://www.youtube-nocookie.com/embed/${trailerKey}?autoplay=1&rel=0`}
                    title={d.videos[0].name || t('d_trailer')}
                    allow="autoplay; encrypted-media; picture-in-picture"
                    allowFullScreen
                  />
                </div>
              ) : (
                <button type="button" className="btn btn--ghost" onClick={() => setTrailer(true)}>{t('d_trailer')}</button>
              )}
            </motion.section>
          )}

          <Providers providers={d.providers} region={d.region} />

          <People d={d} onPerson={onPerson} />
          <Studios companies={d.companies} onOpen={onOpen} onMore={onCompany} />

          <Facts facts={facts} />

          {d.reviews?.length > 0 && (
            <motion.section className="block" {...fadeUp}>
              <h3>{t('d_reviews')}</h3>
              {d.reviews.slice(0, 3).map((r, i) => <Review key={i} r={r} />)}
            </motion.section>
          )}
        </>
      )}
    </Sheet>
  )
}
