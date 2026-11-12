import { useEffect, useRef, useState } from 'react'
import { AnimatePresence, motion, useDragControls, useIsPresent } from 'framer-motion'
import { base, leave, pop, snap } from './motion.jsx'
import { useApp } from './ctx.jsx'

/** Rubber-stamp label. The one memorable element of the app. */
export function Stamp({ status, className = '' }) {
  const { t } = useApp()
  return <span className={`stamp stamp--${status} ${className}`}>{t(`st_${status}`)}</span>
}

export function Poster({ src, title, eager = false }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return (
      <div className="poster poster--empty" role="img" aria-label={title}>
        <span>{title}</span>
      </div>
    )
  }
  return (
    <img
      className="poster"
      src={src}
      alt={title}
      loading={eager ? 'eager' : 'lazy'}
      draggable={false}
      onError={() => setFailed(true)}
    />
  )
}

/** The SEEN stamp with letters that fade out from the left, then back in: SEEN, EEN, EN, N, S, SE, SEE. */
function LoadingStamp() {
  const { t } = useApp()
  const letters = Array.from(t('st_watched').toUpperCase())
  const n = letters.length
  const frames = [
    ...Array.from({ length: n }, (_, k) => (i) => i >= k),
    ...Array.from({ length: n }, (_, k) => (i) => i <= k),
  ]
  const [f, setF] = useState(0)
  useEffect(() => {
    const id = setInterval(() => setF((x) => (x + 1) % frames.length), 380)
    return () => clearInterval(id)
  }, [frames.length])
  return (
    <span className="stamp stamp--watched auth__stamp" aria-hidden="true">
      {letters.map((ch, i) => (
        <span key={i} className="stamp__ch" style={{ opacity: frames[f](i) ? 1 : 0 }}>{ch}</span>
      ))}
    </span>
  )
}

/** The Débarras mark: a small pile of cards with a green SEEN stamp. `loading` makes it sway. */
const jitter = (max) => (Math.random() * 2 - 1) * max

export function Mark({ loading = false, hero = false, name = '' }) {
  const [tilt] = useState(() => {
    const side = Math.random() < 0.5 ? 1 : -1
    const lean = () => 3 + Math.random() * 4
    const shift = () => 0.5 + Math.random() * 1.5
    return { a: -side * lean(), b: side * lean(), f: jitter(2), ax: -side * shift(), bx: side * shift() }
  })

  const at = (deg, dx) => (hero ? { transform: `translateX(calc(-50% + ${dx.toFixed(1)}%)) rotate(${deg.toFixed(1)}deg)` } : undefined)
  return (
    <div className={`auth__pile${loading ? ' mark--loading' : ''}${hero ? ' auth__pile--hero' : ''}`} aria-hidden="true">
      <span className="auth__sheet auth__sheet--3" style={at(tilt.a, tilt.ax)} />
      <span className="auth__sheet auth__sheet--2" style={at(tilt.b, tilt.bx)} />
      <span className="auth__sheet auth__sheet--1" style={at(tilt.f, 0)}>
        {loading ? <LoadingStamp /> : <Stamp status="watched" className="auth__stamp" />}
        {name && <span className="auth__corner auth__corner--tl">{name}</span>}
        {name && <span className="auth__corner auth__corner--br">{name}</span>}
      </span>
    </div>
  )
}

const GRID_TITLES = [['Dune', 2021], ['Arrival', 2016], ['Severance', 2022], ['Parasite', 2019], ['Heat', 1995], ['Fargo', 1996], ['Alien', 1979], ['Andor', 2022], ['Drive', 2011], ['Her', 2013], ['Amélie', 2001], ['Chernobyl', 2019], ['Whiplash', 2014], ['Barry', 2018], ['Dark', 2017], ['Past Lives', 2023], ['Ran', 1985], ['The Bear', 2022], ['Moonlight', 2016], ['Oldboy', 2003], ['Arcane', 2021], ['Gone Girl', 2014], ['Léon', 1994], ['Sicario', 2015], ['Atlanta', 2016], ['Memento', 2000]]
const GRID_COLORS = ['#172334', '#213249', '#2a3e57', '#26384f', '#1f2f44', '#2d4a45', '#3a3552', '#4a3340', '#35422f', '#3f3a2a']
const GRID_STATUSES = ['watched', 'want', 'not_now']
const pickOne = (a) => a[Math.floor(Math.random() * a.length)]

/** Login hero: a 4x4 scatter of slightly tilted cards, some stamped. Random on every load. */
export function CardGrid() {
  const [cards] = useState(() => {
    const pool = [...GRID_TITLES].sort(() => Math.random() - 0.5)
    return Array.from({ length: 16 }, (_, i) => ({
      title: pool[i][0],
      year: pool[i][1],
      color: pickOne(GRID_COLORS),
      rot: jitter(4),
      dx: jitter(2),
      dy: jitter(2),
      status: Math.random() < 0.5 ? pickOne(GRID_STATUSES) : null,
      stampRot: jitter(12) - 6,
    }))
  })
  return (
    <div className="cardgrid" aria-hidden="true">
      {cards.map((c, i) => (
        <div className="cardgrid__cell" key={i}>
          <div className="cardgrid__card" style={{ background: c.color, transform: `translate(${c.dx.toFixed(1)}%, ${c.dy.toFixed(1)}%) rotate(${c.rot.toFixed(1)}deg)` }}>
            <span className="cardgrid__year">{c.year}</span>
            <span className="cardgrid__title">{c.title}</span>
            {c.status && <Stamp status={c.status} className="cardgrid__stamp" />}
          </div>
        </div>
      ))}
    </div>
  )
}

export function Spinner({ label }) {
  return (
    <div className="spinner" role="status">
      <span className="spinner__dot" />
      <span>{label}</span>
    </div>
  )
}

const openSheets = [] // mounted sheets, oldest first: only the top one that is not closing reacts to Escape

/** Bottom sheet: Escape or backdrop closes; drag the handle down to dismiss. `head` sits above the scrolling body. */
export function Sheet({ onClose, title, children, wide = false, head = null, covered = false, tall = false }) {
  const present = useIsPresent()
  const panel = useRef(null)
  const controls = useDragControls()
  // Latest onClose without re-running the effect: callers pass inline arrows, and re-running
  // would re-focus the panel on every render (stealing focus from inputs while typing).
  const closeRef = useRef(onClose)
  const meRef = useRef(null)
  useEffect(() => { if (meRef.current) meRef.current.present = present }, [present])
  closeRef.current = onClose

  useEffect(() => {
    const me = { present: true }
    meRef.current = me
    openSheets.push(me)
    const onKey = (e) => e.key === 'Escape' && [...openSheets].reverse().find((s) => s.present) === me && closeRef.current()
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      openSheets.splice(openSheets.indexOf(me), 1)
      document.body.style.overflow = prev
    }
  }, [])

  return (
    <div className="sheet-root" style={{ pointerEvents: present ? undefined : 'none' }}>
      <div className="sheet-backdrop" onClick={onClose} />
      <motion.div
        ref={panel}
        className={`sheet ${wide ? 'sheet--wide' : ''}${tall ? ' sheet--tall' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
        initial={{ y: '100%' }}
        animate={{ y: 0, scale: covered ? 0.96 : 1, opacity: covered ? 0.55 : 1, transition: base }}
        exit={{ y: '100%', transition: leave }}
        style={{ transformOrigin: '50% 100%' }}
        drag="y"
        dragListener={false}
        dragControls={controls}
        dragConstraints={{ top: 0, bottom: 0 }}
        dragElastic={{ top: 0, bottom: 0.6 }}
        onDragEnd={(_, info) => (info.offset.y > 120 || info.velocity.y > 600) && onClose()}
      >
        <div className="sheet__handle" onPointerDown={(e) => controls.start(e)}>
          <span />
        </div>
        {head}
        <div className="sheet__body">{children}</div>
      </motion.div>
    </div>
  )
}

export function Toast({ toast }) {
  return (
    <AnimatePresence>
      {toast && (
        <motion.div
          key={toast.text}
          className={`toast ${toast.kind === 'error' ? 'toast--error' : ''}`}
          role="status"
          style={{ x: '-50%' }}
          initial={{ opacity: 0, y: 16 }}
          animate={{ opacity: 1, y: 0, transition: base }}
          exit={{ opacity: 0, y: 8, transition: leave }}
        >
          {toast.text}
        </motion.div>
      )}
    </AnimatePresence>
  )
}

const ICONS = {
  filter: 'M3 5h18l-7 8v6l-4 2v-8z',
  undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  list: 'M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01',
  history: 'M3 12a9 9 0 1 0 3-6.7L3 8M3 3v5h5M12 7v5l3 2',
  back: 'M15 18l-6-6 6-6',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
}

/** Round icon button for the top bar. `badge` shows a small count. */
export function IconButton({ icon, label, onClick, disabled = false, on = false, hot = false, badge = 0, pill = false }) {
  return (
    <motion.button type="button" className={`iconbtn${on ? ' on' : ''}${hot ? ' hot' : ''}`} aria-label={label} title={label} disabled={disabled} onClick={onClick} whileTap={disabled ? undefined : { scale: 0.88 }} transition={snap}>
      {pill && on && <motion.span layoutId="dock-pill" className="dock__pill" style={{ borderRadius: 999 }} transition={base} />}
      <svg className="iconbtn__svg" viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={ICONS[icon]} />
      </svg>
      {badge > 0 && <motion.span key={badge} className="iconbtn__badge" {...pop}>{badge}</motion.span>}
    </motion.button>
  )
}
