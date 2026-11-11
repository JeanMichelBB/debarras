import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { api, getToken, setOnUnauthorized, setToken } from './api.js'
import { normalizeLang, translate } from './i18n.js'
import { isOnboarded, loadLang, saveLang } from './storage.js'
import { AppCtx } from './ctx.jsx'
import AuthScreen from './AuthScreen.jsx'
import Onboarding from './Onboarding.jsx'
import Sort from './Sort.jsx'
import Lists from './Lists.jsx'
import Settings from './Settings.jsx'
import DetailSheet from './DetailSheet.jsx'
import { Spinner, Toast } from './ui.jsx'

const TABS = ['sort', 'lists', 'settings']

export default function App() {
  const [lang, setLangState] = useState(() => normalizeLang(loadLang()))
  const [token, setTokenState] = useState(getToken())
  const [user, setUser] = useState(null)
  const [bootError, setBootError] = useState(false)
  const [onboarding, setOnboarding] = useState(false)
  const [tab, setTab] = useState('sort')
  const [sheet, setSheet] = useState(null) // { item, status }
  const [toast, setToast] = useState(null)
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
  if (!token) body = <AuthScreen onAuthed={onAuthed} />
  else if (bootError)
    body = (
      <main className="auth">
        <p className="notice notice--error">{t('e_network')}</p>
        <button type="button" className="btn btn--primary" onClick={boot}>{t('retry')}</button>
      </main>
    )
  else if (!user)
    body = (
      <main className="auth"><Spinner label={t('loading')} /></main>
    )
  else if (onboarding) body = <Onboarding onDone={() => setOnboarding(false)} />
  else
    body = (
      <div className="shell">
        <header className="topbar">
          <span className="wordmark">{t('app_name')}</span>
        </header>
        <div className="screens">
          <div hidden={tab !== 'sort'}>
            <Sort active={tab === 'sort'} sheetOpen={!!sheet} openDetails={openDetails} />
          </div>
          {tab === 'lists' && <Lists openDetails={openDetails} />}
          {tab === 'settings' && <Settings user={user} setLang={setLang} refreshUser={refreshUser} signOut={signOut} />}
        </div>
        <nav className="nav" aria-label="Main">
          {TABS.map((id) => (
            <button key={id} type="button" className={tab === id ? 'on' : ''} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}>
              {t(`nav_${id}`)}
            </button>
          ))}
        </nav>
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
