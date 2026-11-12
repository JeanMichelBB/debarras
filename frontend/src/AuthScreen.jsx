import { useState } from 'react'
import { browserSupportsWebAuthn, startAuthentication, startRegistration } from '@simplewebauthn/browser'
import { api } from './api.js'
import { useApp } from './ctx.jsx'
import RecoveryCodes from './RecoveryCodes.jsx'
import Credits from './Credits.jsx'
import { Mark } from './ui.jsx'

const cancelled = (e) => e?.name === 'NotAllowedError' || e?.name === 'AbortError'

export default function AuthScreen({ onAuthed }) {
  const { t, errorText } = useApp()
  const [mode, setMode] = useState('home') // home | recover | codes
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

  return (
    <main className="auth">
      <Mark />

      <h1 className="auth__word">{t('app_name')}</h1>
      <p className="auth__title">{t('tagline_title')}</p>
      <p className="auth__body">{t('tagline_body')}</p>

      {mode === 'home' && (
        <div className="auth__actions">
          {!supported && <p className="notice notice--error">{t('passkey_unsupported')}</p>}
          <button type="button" className="btn btn--primary btn--block" disabled={busy || !supported} onClick={register}>
            {t('create_account')}
          </button>
          <button type="button" className="btn btn--ghost btn--block" disabled={busy || !supported} onClick={signIn}>
            {t('sign_in')}
          </button>
          <button type="button" className="linkbtn" onClick={() => { setError(null); setMode('recover') }}>
            {t('use_recovery')}
          </button>
          <p className="hint">{t('passkey_hint')}</p>
        </div>
      )}

      {mode === 'recover' && (
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
          <button type="submit" className="btn btn--primary btn--block" disabled={busy || code.trim().length < 8}>
            {t('recovery_signin')}
          </button>
          <button type="button" className="linkbtn" onClick={() => { setError(null); setMode('home') }}>{t('back')}</button>
        </form>
      )}

      {error && <p className="notice notice--error" role="alert">{error}</p>}
      <Credits />
    </main>
  )
}
