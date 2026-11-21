import { useState } from 'react'
import { startRegistration } from '@simplewebauthn/browser'
import { api } from './api.js'
import { useApp } from './ctx.jsx'
import RecoveryCodes from './RecoveryCodes.jsx'
import { Sheet } from './ui.jsx'

const cancelled = (e) => e?.name === 'NotAllowedError' || e?.name === 'AbortError'

/** A guest turns into a full account: add a passkey to the same user, then show the recovery codes once. */
export default function SaveProgress({ onClose, onSaved }) {
  const { t, errorText } = useApp()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(null)
  const [codes, setCodes] = useState(null)

  const create = async () => {
    setBusy(true)
    setError(null)
    try {
      const { options, state } = await api.addPasskeyBegin()
      const credential = await startRegistration({ optionsJSON: options })
      await api.addPasskeyFinish(credential, state)
      const res = await api.newRecoveryCodes()
      setCodes(res.recovery_codes)
      await onSaved?.()
    } catch (e) {
      setError(cancelled(e) ? t('passkey_cancelled') : errorText(e))
    } finally {
      setBusy(false)
    }
  }

  return (
    <Sheet onClose={onClose} title={t('save_title')}>
      {codes ? (
        <RecoveryCodes codes={codes} onDone={onClose} />
      ) : (
        <div className="auth__actions">
          <h2 className="sheet__title">{t('save_title')}</h2>
          <p>{t('save_body')}</p>
          {error && <p className="notice notice--error" role="alert">{error}</p>}
          <button type="button" className="btn btn--primary btn--block" disabled={busy} onClick={create}>{t('save_cta')}</button>
          <button type="button" className="btn btn--ghost btn--block" onClick={onClose}>{t('save_later')}</button>
        </div>
      )}
    </Sheet>
  )
}
