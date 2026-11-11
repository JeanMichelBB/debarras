import { useState } from 'react'
import { useApp } from './ctx.jsx'

export function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

/** Shows recovery codes once. The user must confirm they saved them before continuing. */
export default function RecoveryCodes({ codes, onDone }) {
  const { t } = useApp()
  const [saved, setSaved] = useState(false)
  const [copied, setCopied] = useState(false)
  const text = codes.join('\n')

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(text)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard blocked: download still works */
    }
  }

  return (
    <div className="codes">
      <h2>{t('recovery_title')}</h2>
      <p>{t('recovery_body')}</p>
      <ul className="codes__list">
        {codes.map((c) => <li key={c}>{c}</li>)}
      </ul>
      <div className="actions">
        <button type="button" className="btn btn--ghost" onClick={copy}>{copied ? t('copied') : t('recovery_copy')}</button>
        <button
          type="button"
          className="btn btn--ghost"
          onClick={() => downloadBlob(new Blob([text + '\n'], { type: 'text/plain' }), 'debarras-recovery-codes.txt')}
        >
          {t('recovery_download')}
        </button>
      </div>
      <label className="check">
        <input type="checkbox" checked={saved} onChange={(e) => setSaved(e.target.checked)} />
        <span>{t('recovery_saved')}</span>
      </label>
      <button type="button" className="btn btn--primary btn--block" disabled={!saved} onClick={onDone}>{t('continue')}</button>
    </div>
  )
}
