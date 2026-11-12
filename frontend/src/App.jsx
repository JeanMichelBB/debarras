import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, getToken, setOnUnauthorized, setToken } from './api.js'
import { normalizeLang, translate } from './i18n.js'
import { isOnboarded, isTutorialSeen, loadLang, markTutorialSeen, resetTutorial, saveLang } from './storage.js'
import { AppCtx } from './ctx.jsx'
import AuthScreen from './AuthScreen.jsx'
import Onboarding from './Onboarding.jsx'
import Tutorial from './Tutorial.jsx'
import AppSkeleton from './Skeleton.jsx'
import Sort from './Sort.jsx'
import Lists from './Lists.jsx'
import Settings from './Settings.jsx'
import DetailSheet from './DetailSheet.jsx'
import { IconButton, Toast } from './ui.jsx'

// Dev only: add ?skeleton to the address to hold the full-app skeleton for testing.
const HOLD_SKELETON = import.meta.env.DEV && new URLSearchParams(window.location.search).has('skeleton')

const TABS = ['sort', 'lists']

export default function App() {
  const [lang, setLangState] = useState(() => normalizeLang(loadLang()))
  const [token, setTokenState] = useState(getToken())
  const [user, setUser] = useState(null)
  const [bootError, setBootError] = useState(false)
  const [onboarding, setOnboarding] = useState(false)
  const [tab, setTab] = useState('sort')
  const [showGuide, setShowGuide] = useState(() => !isTutorialSeen())
  const [sheet, setSheet] = useState(null) // { item, status }
  const [toast, setToast] = useState(null)
  const [tabsSlot, setTabsSlot] = useState(null) // Lists puts its Seen / Want / Not now tabs into the header
  const [actionsSlot, setActionsSlot] = useState(null) // where the Sort screen puts its top-bar buttons
  const toastTimer = useRef(null)
  const screensRef = useRef(null)
  const [topBlur, setTopBlur] = useState(false) // header: solid at the top of a page, blurred once content scrolls under it
  const [navBlur, setNavBlur] = useState(false) // bottom bar is solid at the top of a page and blurs once you scroll down with content still below

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
    setSheet(null)
    setOnboarding(false)
    setTab('sort')
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

  useEffect(() => {
    const box = screensRef.current
    if (!box) return undefined
    const check = () => {
      const scrolled = box.scrollTop > 4
      setTopBlur(scrolled)
      setNavBlur(scrolled && box.scrollHeight - box.scrollTop - box.clientHeight > 4)
    }
    check()
    box.addEventListener('scroll', check, { passive: true })
    const ro = new ResizeObserver(check)
    ro.observe(box)
    Array.from(box.children).forEach((c) => ro.observe(c))
    return () => {
      box.removeEventListener('scroll', check)
      ro.disconnect()
    }
  }, [tab, user, onboarding, token])

  useEffect(() => {
    document.documentElement.lang = lang
  }, [lang])

  const onAuthed = ({ token: tk, isNew, recovered }) => {
    setToken(tk)
    setTokenState(tk)
    if (isNew && !isOnboarded()) setOnboarding(true)
    if (recovered) notify(translate(lang, 'recovery_after'))
  }

  const openDetails = useCallback((item, status = null) => setSheet({ item, status }), [])
  const closeSheet = useCallback(() => setSheet(null), [])

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
  else
    body = (
      <div className={`shell${tab === 'settings' ? ' shell--settings' : ''}${tab === 'lists' ? ' shell--lists' : ''}`}>
        <header className={`topbar${topBlur ? ' topbar--blur' : ''}`}>
          <div className="topbar__row">
            <span className="wordmark">{t('app_name')}</span>
            <div className="topbar__actions">
              <span ref={setActionsSlot} className="topbar__slot" />
              <IconButton icon="gear" label={t('nav_settings')} on={tab === 'settings'} onClick={() => { setSheet(null); setTab(tab === 'settings' ? 'sort' : 'settings') }} />
            </div>
          </div>
          {tab === 'lists' && <div ref={setTabsSlot} className="topbar__tabs" />}
        </header>
        <div className="screens" ref={screensRef}>
          <div hidden={tab === 'lists'}>
            <Sort active={tab === 'sort'} sheetOpen={!!sheet} openDetails={openDetails} actionsSlot={actionsSlot} />
          </div>
          {tab === 'lists' && <Lists openDetails={openDetails} tabsSlot={tabsSlot} />}
          {tab === 'settings' && <Settings user={user} setLang={setLang} refreshUser={refreshUser} signOut={signOut} onShowGuide={() => { resetTutorial(); setShowGuide(true); setTab('sort') }} />}
        </div>
        <nav className={`nav${navBlur ? ' nav--blur' : ''}`} aria-label="Main">
          {TABS.map((id) => (
            <button key={id} type="button" className={tab === id ? 'on' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => { setSheet(null); setTab(id) }}>
              {t(`nav_${id}`)}
            </button>
          ))}
        </nav>
        {showGuide && tab === 'sort' && <Tutorial onDone={() => { markTutorialSeen(); setShowGuide(false) }} />}
        {sheet && <DetailSheet item={sheet.item} status={sheet.status} onClose={closeSheet} />}
      </div>
    )

  return (
    <AppCtx.Provider value={ctx}>
      {body}
      <Toast toast={toast} />
    </AppCtx.Provider>
  )
}
