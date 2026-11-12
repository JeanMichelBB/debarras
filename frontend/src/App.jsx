import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, getToken, setOnUnauthorized, setToken } from './api.js'
import { normalizeLang, translate } from './i18n.js'
import { isOnboarded, isTutorialSeen, loadLang, markTutorialSeen, pushHistory, resetTutorial, saveLang } from './storage.js'
import { EVT_SWIPE, EVT_UNDO } from './actions.js'
import { AppCtx } from './ctx.jsx'
import AuthScreen from './AuthScreen.jsx'
import Onboarding from './Onboarding.jsx'
import Tutorial from './Tutorial.jsx'
import AppSkeleton from './Skeleton.jsx'
import Sort from './Sort.jsx'
import Lists from './Lists.jsx'
import Settings from './Settings.jsx'
import DetailSheet from './DetailSheet.jsx'
import { HistorySheet, PersonSheet, Trail } from './Explore.jsx'
import { AnimatePresence, MotionConfig, motion } from 'framer-motion'
import { base, snap, soft } from './motion.jsx'
import { IconButton, Sheet, Toast } from './ui.jsx'
import { AboutSheet } from './Credits.jsx'

// Dev only: add ?skeleton to the address to hold the full-app skeleton for testing.
const HOLD_SKELETON = import.meta.env.DEV && new URLSearchParams(window.location.search).has('skeleton')

export default function App() {
  const [lang, setLangState] = useState(() => normalizeLang(loadLang()))
  const [token, setTokenState] = useState(getToken())
  const [user, setUser] = useState(null)
  const [bootError, setBootError] = useState(false)
  const [onboarding, setOnboarding] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)
  const [panel, setPanel] = useState(null) // 'lists' | 'settings': the sheet opened from the bottom bar
  const [stack, setStack] = useState([]) // sheets opened on top of it: titles, people, history
  const [closeSignal, setCloseSignal] = useState(0)
  const [wantCount, setWantCount] = useState(0)
  const [showGuide, setShowGuide] = useState(() => !isTutorialSeen())
  const [similar, setSimilar] = useState(null) // { kind, label, query, n } asks Sort to show a themed pile
  const [toast, setToast] = useState(null)
  const [actionsSlot, setActionsSlot] = useState(null) // where the Sort screen puts its filter and undo buttons in the bar
  const toastTimer = useRef(null)

  const t = useCallback((key, vars) => translate(lang, key, vars), [lang])

  const setLang = useCallback((l) => {
    const next = normalizeLang(l)
    saveLang(next)
    setLangState(next)
  }, [])

  const notify = useCallback((text, kind = 'info') => {
    clearTimeout(toastTimer.current)
    setToast({ text, kind })
    toastTimer.current = setTimeout(() => setToast(null), 3500)
  }, [])

  const errorText = useCallback(
    (e, fallbackKey = 'error_generic') =>
      e?.code === 'network' ? t('e_network')
      : e?.code === 'session' ? t('e_session')
      : e?.code === 'rate' ? t('e_too_many')
      : t(fallbackKey),
    [t],
  )

  const signOut = useCallback(() => {
    setToken(null)
    setTokenState(null)
    setUser(null)
    setStack([])
    setPanel(null)
    setSimilar(null)
    setOnboarding(false)
  }, [])

  // Any 401 from the API signs the user out.
  useEffect(() => {
    setOnUnauthorized(() => {
      signOut()
      notify(translate(loadLang() || 'en', 'e_session'), 'error')
    })
  }, [signOut, notify])

  const refreshUser = useCallback(async () => {
    const u = await api.me()
    setUser(u)
    setLang(u.lang)
    return u
  }, [setLang])

  const boot = useCallback(() => {
    setBootError(false)
    refreshUser().catch((e) => {
      if (e?.status !== 401) setBootError(true)
    })
  }, [refreshUser])

  useEffect(() => {
    if (token) boot()
  }, [token, boot])

  // "Lists" count in the bar: titles waiting in Want to watch.
  useEffect(() => {
    if (!user) return undefined
    const load = () => api.stats().then((r) => setWantCount(r.want || 0)).catch(() => {})
    load()
    window.addEventListener(EVT_SWIPE, load)
    window.addEventListener(EVT_UNDO, load)
    return () => {
      window.removeEventListener(EVT_SWIPE, load)
      window.removeEventListener(EVT_UNDO, load)
    }
  }, [user])

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const onAuthed = ({ token: tk, isNew, recovered }) => {
    setToken(tk)
    setTokenState(tk)
    if (isNew && !isOnboarded()) setOnboarding(true)
    if (recovered) notify(translate(lang, 'recovery_after'))
  }

  // Sheets: the bar opens one panel; anything opened from inside it stacks on top.
  // Closing or saving pops one level, so you land back on the sheet you came from.
  const closeAll = useCallback(() => {
    setStack([])
    setPanel(null)
  }, [])
  const popSheet = useCallback(() => setStack((s) => s.slice(0, -1)), [])
  const push = useCallback((entry) => {
    if (entry.type === 'detail' || entry.type === 'person') pushHistory(entry)
    setStack((s) => {
      const top = s[s.length - 1]
      const same = top && top.type === entry.type && (entry.type === 'detail' ? top.item.tmdb_id === entry.item.tmdb_id && top.item.media_type === entry.item.media_type : top.id === entry.id)
      return same ? s : [...s, entry]
    })
  }, [])
  const openDetails = useCallback((item, status = null) => {
    const slim = { media_type: item.media_type, tmdb_id: item.tmdb_id, title: item.title, year: item.year, poster: item.poster }
    push({ type: 'detail', item: slim, status, name: item.title, icon: item.poster || null })
  }, [push])
  const openPerson = useCallback((p) => push({ type: 'person', id: p.id, name: p.name, icon: p.photo || null, photo: p.photo || null }), [push])
  const openFromHistory = useCallback((e) => push(e), [push])
  const showPile = useCallback((kind, label, query) => {
    closeAll()
    setSimilar({ kind, label, query, n: Date.now() })
  }, [closeAll])
  const showSimilar = useCallback((item) => showPile('title', item.title, { like: `${item.media_type}:${item.tmdb_id}` }), [showPile])
  const showPersonPile = useCallback((p) => showPile('person', p.name, { person: p.id }), [showPile])
  const showCompanyPile = useCallback((c) => showPile('company', c.name, { company: c.id }), [showPile])
  const togglePanel = useCallback((name) => {
    setCloseSignal((n) => n + 1)
    setStack([])
    setPanel((p) => (p === name && stack.length === 0 ? null : name))
  }, [stack.length])

  const ctx = useMemo(() => ({ t, lang, notify, errorText }), [t, lang, notify, errorText])

  let body
  if (HOLD_SKELETON) body = <AppSkeleton />
  else if (!token) body = <AuthScreen onAuthed={onAuthed} />
  else if (bootError)
    body = (
      <main className="auth">
        <p className="notice notice--error">{t('e_network')}</p>
        <button type="button" className="btn btn--primary" onClick={boot}>{t('retry')}</button>
      </main>
    )
  else if (!user)
    body = <AppSkeleton />
  else if (onboarding) body = <Onboarding onDone={() => setOnboarding(false)} />
  else {
    const full = [
      ...(panel ? [{ type: 'panel', name: panel === 'lists' ? t('nav_lists') : t('nav_settings'), icon: null }] : []),
      ...stack,
    ]
    const jump = (i) => setStack(full.slice(panel ? 1 : 0, i + 1))
    const trail = full.length > 1 ? <Trail entries={full} onJump={jump} onBack={popSheet} /> : null
    body = (
      <div className="shell">
        <header className="topbar">
          <div className="topbar__row">
            <span className="wordmark">{t('app_name')}</span>
            <button type="button" className="linkbtn" onClick={() => setAboutOpen(true)}>{t('auth_about')}</button>
          </div>
        </header>
        <div className="screens">
          <Sort active sheetOpen={!!panel || stack.length > 0} openDetails={openDetails} actionsSlot={actionsSlot} similar={similar} closeSignal={closeSignal} onBeforeFilters={closeAll} />
        </div>
        <motion.nav className="dock" aria-label="Main" initial={{ y: 90, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={soft}>
          <motion.button type="button" className={`dock__lists${panel === 'lists' ? ' on' : ''}`} aria-pressed={panel === 'lists'} onClick={() => togglePanel('lists')} whileTap={{ scale: 0.94 }} transition={snap}>
            {panel === 'lists' && <motion.span layoutId="dock-pill" className="dock__pill" style={{ borderRadius: 999 }} transition={base} />}
            <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01" /></svg>
            <span>{t('nav_lists')}</span>
            {wantCount > 0 && <small>{wantCount}</small>}
          </motion.button>
          <div className="dock__right">
            <span ref={setActionsSlot} className="topbar__slot" />
            <IconButton icon="gear" label={t('nav_settings')} on={panel === 'settings'} pill onClick={() => togglePanel('settings')} />
          </div>
        </motion.nav>
        {showGuide && !panel && stack.length === 0 && <Tutorial onDone={() => { markTutorialSeen(); setShowGuide(false) }} />}
        <AnimatePresence>
          {aboutOpen && <AboutSheet key="about" onClose={() => setAboutOpen(false)} />}
          {panel === 'lists' && (
            <Sheet key="lists" onClose={closeAll} title={t('nav_lists')} wide tall covered={stack.length > 0}>
              <h2 className="sheet__title">{t('nav_lists')}</h2>
              <Lists openDetails={openDetails} />
            </Sheet>
          )}
          {panel === 'settings' && (
            <Settings key="settings" user={user} setLang={setLang} refreshUser={refreshUser} signOut={signOut} onClose={closeAll} covered={stack.length > 0}
              onHistory={() => push({ type: 'history', name: t('h_title'), icon: null })}
              onShowGuide={() => { resetTutorial(); setShowGuide(true); closeAll() }} />
          )}
          {stack.map((e, i) => {
            const top = i === stack.length - 1
            const head = top ? trail : null
            const covered = !top
            if (e.type === 'detail') {
              return <DetailSheet key={`${i}:${e.item.media_type}:${e.item.tmdb_id}`} item={e.item} status={e.status} onClose={popSheet} onSimilar={showSimilar} onPerson={openPerson} onCompany={showCompanyPile} onOpen={openDetails} head={head} covered={covered} />
            }
            if (e.type === 'person') {
              return <PersonSheet key={`${i}:p${e.id}`} person={e} onClose={popSheet} onOpen={openDetails} onMore={showPersonPile} head={head} covered={covered} />
            }
            return <HistorySheet key={`${i}:h`} onClose={popSheet} onOpen={openFromHistory} head={head} covered={covered} />
          })}
        </AnimatePresence>
      </div>
    )
  }

  return (
    <AppCtx.Provider value={ctx}>
      <MotionConfig reducedMotion="user">
        {body}
        <Toast toast={toast} />
      </MotionConfig>
    </AppCtx.Provider>
  )
}
