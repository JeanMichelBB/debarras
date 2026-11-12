import { useApp } from './ctx.jsx'

/** Placeholder for the whole app while the account loads: same header, pile and bottom bar. */
export default function AppSkeleton() {
  const { t } = useApp()
  return (
    <div className="shell" role="status" aria-busy="true" aria-label={t('loading')}>
      <header className="topbar">
        <div className="topbar__row">
          <span className="sk sk--word" />
          <div className="topbar__actions">
            <span className="sk sk--icon" />
            <span className="sk sk--icon" />
            <span className="sk sk--icon" />
          </div>
        </div>
      </header>
      <div className="screens">
        <section className="screen sort">
          <div className="stage">
            <div className="deck">
              <div className="card sk sk--card sk--back2" />
              <div className="card sk sk--card sk--back1" />
              <div className="card sk sk--card sk--top">
                <span className="sk sk--line sk--title" />
                <span className="sk sk--line sk--facts" />
              </div>
            </div>
          </div>
        </section>
      </div>
      <nav className="nav" aria-hidden="true">
        <span className="sk sk--tab" />
        <span className="sk sk--tab" />
      </nav>
    </div>
  )
}
