import { useCallback, useEffect, useMemo, useState } from 'react'
import { startRegistration } from '@simplewebauthn/browser'
import { api } from './api.js'
import { LANGS } from './i18n.js'
import RecoveryCodes from './RecoveryCodes.jsx'
import Credits from './Credits.jsx'
import { Sheet } from './ui.jsx'
import { useApp } from './ctx.jsx'

// Regions TMDb has watch-provider data for (subset of the most common).
const REGIONS = [
  'CA', 'US', 'GB', 'FR', 'DE', 'ES', 'IT', 'AU', 'NZ', 'IE', 'BE', 'NL', 'CH', 'AT', 'SE', 'NO', 'DK', 'FI',
  'PT', 'PL', 'CZ', 'HU', 'GR', 'TR', 'JP', 'KR', 'IN', 'MX', 'BR', 'AR', 'CL', 'CO', 'ZA', 'SG', 'HK', 'TW',
  'PH', 'TH', 'ID', 'MY', 'AE', 'SA', 'IL', 'EG', 'NG', 'KE', 'UA', 'RO', 'BG', 'HR', 'IS', 'LU', 'PE', 'EC',
]
const LANG_NAMES = { en: 'English', fr: 'Français' }

export default function Settings({ user, setLang, refreshUser, signOut }) {
  const { t, lang, notify, errorText } = useApp()
  const [passkeys, setPasskeys] = useState([])
  const [codes, setCodes] = useState(null)
  const [confirmCodes, setConfirmCodes] = useState(false)
  const [confirmText, setConfirmText] = useState('')
  const [showDelete, setShowDelete] = useState(false)
  const [busy, setBusy] = useState(false)

  const regionNames = useMemo(() => {
    let dn
    try {
      dn = new Intl.DisplayNames([lang], { type: 'region' })
    } catch {
      dn = null
    }
    return REGIONS.map((code) => ({ code, name: dn?.of(code) || code })).sort((a, b) => a.name.localeCompare(b.name, lang))
  }, [lang])

  const loadPasskeys = useCallback(() => api.passkeys().then(setPasskeys).catch(() => {}), [])
  useEffect(() => {
    loadPasskeys()
  }, [loadPasskeys])

  const guard = async (fn) => {
    setBusy(true)
    try {
      await fn()
    } catch (e) {
      if (e?.name === 'NotAllowedError' || e?.name === 'AbortError') notify(t('passkey_cancelled'), 'error')
      else notify(errorText(e), 'error')
    } finally {
      setBusy(false)
    }
  }

  const changeLang = (l) => guard(async () => {
    await api.updateMe({ lang: l })
    setLang(l)
    await refreshUser()
  })
  const changeRegion = (r) => guard(async () => {
    await api.updateMe({ region: r })
    await refreshUser()
  })
  const addPasskey = () => guard(async () => {
    const { options, state } = await api.addPasskeyBegin()
    const credential = await startRegistration({ optionsJSON: options })
    await api.addPasskeyFinish(credential, state)
    await loadPasskeys()
    await refreshUser()
  })
  const removePasskey = (id) => guard(async () => {
    await api.deletePasskey(id)
    await loadPasskeys()
    await refreshUser()
  })
  const newCodes = () => guard(async () => {
    const res = await api.newRecoveryCodes()
    setConfirmCodes(false)
    setCodes(res.recovery_codes)
    await refreshUser()
  })
  const deleteAccount = () => guard(async () => {
    await api.deleteAccount()
    signOut()
  })

  const word = t('s_delete_word')

  return (
    <section className="screen settings" aria-label={t('nav_settings')}>
      <div className="setting">
        <label htmlFor="lang">{t('s_language')}</label>
        <select id="lang" value={lang} disabled={busy} onChange={(e) => changeLang(e.target.value)}>
          {LANGS.map((l) => <option key={l} value={l}>{LANG_NAMES[l]}</option>)}
        </select>
      </div>

      <div className="setting">
        <label htmlFor="region">{t('s_region')}</label>
        <select id="region" value={user.region} disabled={busy} onChange={(e) => changeRegion(e.target.value)}>
          {regionNames.map((r) => <option key={r.code} value={r.code}>{r.name}</option>)}
        </select>
        <p className="muted small">{t('s_region_hint')}</p>
      </div>

      <div className="setting">
        <h2>{t('s_passkeys')}</h2>
        <ul className="rows">
          {passkeys.map((p, i) => (
            <li key={p.id}>
              <span>{p.name || `${t('s_passkeys')} ${i + 1}`}</span>
              <button type="button" className="linkbtn" disabled={busy || passkeys.length <= 1} title={passkeys.length <= 1 ? t('s_last_passkey') : undefined} onClick={() => removePasskey(p.id)}>
                {t('s_remove')}
              </button>
            </li>
          ))}
        </ul>
        {passkeys.length <= 1 && <p className="muted small">{t('s_last_passkey')}</p>}
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={addPasskey}>{t('s_add_passkey')}</button>
      </div>

      <div className="setting">
        <h2>{t('s_codes')}</h2>
        <p className="muted">{t('s_codes_left', { n: user.recovery_codes_left })}</p>
        <button type="button" className="btn btn--ghost" disabled={busy} onClick={() => setConfirmCodes(true)}>{t('s_codes_new')}</button>
      </div>

      <div className="setting">
        <button type="button" className="btn btn--ghost" onClick={signOut}>{t('s_signout')}</button>
      </div>

      <div className="setting setting--danger">
        <h2>{t('s_delete')}</h2>
        <p>{t('s_delete_warn')}</p>
        <button type="button" className="btn btn--danger" onClick={() => setShowDelete(true)}>{t('s_delete')}</button>
      </div>

      <div className="setting">
        <h2>{t('s_about')}</h2>
        <Credits />
      </div>

      {confirmCodes && (
        <Sheet onClose={() => setConfirmCodes(false)} title={t('s_codes_new')}>
          <h2 className="sheet__title">{t('s_codes_new')}</h2>
          <p>{t('s_codes_warn')}</p>
          <div className="actions">
            <button type="button" className="btn btn--ghost" onClick={() => setConfirmCodes(false)}>{t('cancel')}</button>
            <button type="button" className="btn btn--primary" disabled={busy} onClick={newCodes}>{t('s_codes_new')}</button>
          </div>
        </Sheet>
      )}

      {codes && (
        <Sheet onClose={() => {}} title={t('recovery_title')}>
          <RecoveryCodes codes={codes} onDone={() => setCodes(null)} />
        </Sheet>
      )}

      {showDelete && (
        <Sheet onClose={() => setShowDelete(false)} title={t('s_delete')}>
          <h2 className="sheet__title">{t('s_delete')}</h2>
          <p>{t('s_delete_warn')}</p>
          <label className="field">
            <span>{t('s_delete_type', { word })}</span>
            <input value={confirmText} onChange={(e) => setConfirmText(e.target.value)} autoComplete="off" />
          </label>
          <div className="actions">
            <button type="button" className="btn btn--ghost" onClick={() => setShowDelete(false)}>{t('cancel')}</button>
            <button type="button" className="btn btn--danger" disabled={busy || confirmText.trim() !== word} onClick={deleteAccount}>
              {t('s_delete_go')}
            </button>
          </div>
        </Sheet>
      )}
    </section>
  )
}
