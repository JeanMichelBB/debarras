import { useEffect, useState } from 'react'
import { browserSupportsWebAuthn, startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { api } from './api.js'
import { useApp } from './ctx.jsx'
import RecoveryCodes from './RecoveryCodes.jsx'
import { AboutSheet } from './Credits.jsx'
import { AnimatePresence, motion } from 'framer-motion'
import { soft } from './motion.jsx'
import { CardGrid, Mark, Sheet } from './ui.jsx'

const cancelled = (e) => e?.name === 'NotAllowedError' || e?.name === 'AbortError'

// If the posters can't be fetched, these three (TMDb poster paths) are used.
const FALLBACK_POSTERS = ['/qJ2tW6WMUDux911r6m7haRef0WH.jpg', '/jSziioSwPVrOy9Yow3XhWIBDjq1.jpg', '/8Gxv8gSFCU0XGDykEGv7zR1n2ua.jpg']

export default function AuthScreen({ onAuthed }) {
  const { t, errorText } = useApp()
  const [mode, setMode] = useState('home') // home | codes
  const [posters, setPosters] = useState(null) // null until the random picks arrive, so no poster flashes first
  const [recoverOpen, setRecoverOpen] = useState(false)
  const [aboutOpen, setAboutOpen] = useState(false)

  useEffect(() => {
    let live = true
    api.loginPosters().then((r) => live && setPosters(r.posters?.length ? r.posters : FALLBACK_POSTERS)).catch(() => live && setPosters(FALLBACK_POSTERS))
    return () => {
      live = false
    }
  }, [])
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [pending, setPending] = useState(null) // { token, codes } until the codes are saved
  const [code, setCode] = useState('')
  const supported = browserSupportsWebAuthn()

  const run = async (fn) => {
    setBusy(true)
    setError(null)
    try {
      await fn()
    } catch (e) {
      if (cancelled(e)) setError(t('passkey_cancelled'))
      else if (e?.status === 401 && e?.code !== 'rate') setError(t('passkey_unknown'))
      else setError(errorText(e))
    } finally {
      setBusy(false)
    }
  }

  const register = () =>
    run(async () => {
      const { options, state } = await api.registerBegin()
      const credential = await startRegistration({ optionsJSON: options })
      const res = await api.registerFinish(credential, state)
      setPending({ token: res.access_token, codes: res.recovery_codes })
      setMode('codes')
    })

  const signIn = () =>
    run(async () => {
      const { options, state } = await api.loginBegin()
      const credential = await startAuthentication({ optionsJSON: options })
      const res = await api.loginFinish(credential, state)
      onAuthed({ token: res.access_token })
    })

  const recover = (e) => {
    e.preventDefault()
    run(async () => {
      const res = await api.recover(code.trim())
      setRecoverOpen(false)
      onAuthed({ token: res.access_token, recovered: true })
    })
  }

  if (mode === 'codes' && pending) {
    return (
      <main className="auth">
        <RecoveryCodes codes={pending.codes} onDone={() => onAuthed({ token: pending.token, isNew: true })} />
      </main>
    )
  }

  const icon = (d) => (
    <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d={d} /></svg>
  )

  return (
    <main className="auth auth--login">
      <div className="auth__top">
        <span className="wordmark">{t('app_name')}</span>
        <button type="button" className="linkbtn" onClick={() => setAboutOpen(true)}>{t('auth_about')}</button>
      </div>

      <div className="auth__hero">
        <Mark hero posters={posters} />
        <p className="auth__title">{t('tagline_title')}</p>
        {!supported && <p className="notice notice--error">{t('passkey_unsupported')}</p>}
        {error && <p className="notice notice--error" role="alert">{error}</p>}
      </div>

      <p className="auth__pk">{t('auth_passkey')}</p>

      <motion.nav className="dock dock--auth" aria-label={t('app_name')} initial={{ y: 90, opacity: 0 }} animate={{ y: 0, opacity: 1 }} transition={soft}>
        <button type="button" className="dock__btn dock__btn--main" disabled={busy || !supported} onClick={register}>
          {icon('M12 5v14M5 12h14')}
          <span>{t('auth_create')}</span>
        </button>
        <button type="button" className="dock__btn" disabled={busy || !supported} onClick={signIn}>
          {icon('M12 11a3 3 0 0 1 3 3v3M9 17v-3a3 3 0 0 1 3-3M7 20v-6a5 5 0 0 1 10 0v2M5 10a7 7 0 0 1 14 0')}
          <span>{t('auth_signin')}</span>
        </button>
      </motion.nav>
      <button type="button" className="linkbtn auth__recover" onClick={() => { setError(null); setRecoverOpen(true) }}>{t('auth_trouble')}</button>

      <AnimatePresence>
        {recoverOpen && (
          <Sheet key="recover" onClose={() => setRecoverOpen(false)} title={t('use_recovery')}>
            <h2 className="sheet__title">{t('use_recovery')}</h2>
            <form className="auth__actions" onSubmit={recover}>
              <label className="field">
                <span>{t('recovery_enter')}</span>
                <input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="XXXX-XXXX-XXXX-XXXX"
                  autoComplete="off"
                  autoCapitalize="characters"
                  spellCheck={false}
                  required
                />
              </label>
              {error && <p className="notice notice--error" role="alert">{error}</p>}
              <button type="submit" className="btn btn--primary btn--block" disabled={busy || code.trim().length < 8}>
                {t('recovery_signin')}
              </button>
            </form>
          </Sheet>
        )}
        {aboutOpen && <AboutSheet key="about" onClose={() => setAboutOpen(false)} />}
      </AnimatePresence>
    </main>
  )
}
