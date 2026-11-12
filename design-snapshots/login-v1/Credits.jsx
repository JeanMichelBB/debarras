import { useApp } from './ctx.jsx'
import { Sheet } from './ui.jsx'

/** Attribution required by TMDb, JustWatch (via TMDb) and Wikipedia (CC BY-SA). */
export default function Credits() {
  const { t } = useApp()
  return (
    <div className="credits">
      <p>
        {t('s_credit_tmdb')}{' '}
        <a href="https://www.themoviedb.org" target="_blank" rel="noreferrer">themoviedb.org</a>
      </p>
      <p>{t('s_credit_jw')}</p>
      <p>
        {t('s_credit_wiki')}{' '}
        <a href="https://creativecommons.org/licenses/by-sa/4.0/" target="_blank" rel="noreferrer">CC BY-SA 4.0</a>
      </p>
    </div>
  )
}

/** The About sheet, shared by the login screen and the main app. */
export function AboutSheet({ onClose }) {
  const { t } = useApp()
  return (
    <Sheet onClose={onClose} title={t('auth_about')}>
      <h2 className="sheet__title">{t('app_name')}</h2>
      <p className="auth__body">{t('tagline_body')}</p>
      <p className="hint">{t('passkey_hint')}</p>
      <Credits />
    </Sheet>
  )
}
