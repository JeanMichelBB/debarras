import { useEffect, useRef, useState } from 'react'
import { motion, useDragControls } from 'framer-motion'
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
export function Mark({ loading = false }) {
  return (
    <div className={`auth__pile${loading ? ' mark--loading' : ''}`} aria-hidden="true">
      <span className="auth__sheet auth__sheet--3" />
      <span className="auth__sheet auth__sheet--2" />
      <span className="auth__sheet auth__sheet--1">
        {loading ? <LoadingStamp /> : <Stamp status="watched" className="auth__stamp" />}
      </span>
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

/** Bottom sheet: Escape or backdrop closes; drag the handle down to dismiss. */
export function Sheet({ onClose, title, children, wide = false }) {
  const panel = useRef(null)
  const controls = useDragControls()
  // Latest onClose without re-running the effect: callers pass inline arrows, and re-running
  // would re-focus the panel on every render (stealing focus from inputs while typing).
  const closeRef = useRef(onClose)
  closeRef.current = onClose

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && closeRef.current()
    window.addEventListener('keydown', onKey)
    panel.current?.focus()
    const prev = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      window.removeEventListener('keydown', onKey)
      document.body.style.overflow = prev
    }
  }, [])

  return (
    <div className="sheet-root">
      <div className="sheet-backdrop" onClick={onClose} />
      <motion.div
        ref={panel}
        className={`sheet ${wide ? 'sheet--wide' : ''}`}
        role="dialog"
        aria-modal="true"
        aria-label={title}
        tabIndex={-1}
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
        <div className="sheet__body">{children}</div>
      </motion.div>
    </div>
  )
}

export function Toast({ toast }) {
  if (!toast) return null
  return (
    <div className={`toast ${toast.kind === 'error' ? 'toast--error' : ''}`} role="status">
      {toast.text}
    </div>
  )
}

const ICONS = {
  filter: 'M3 5h18l-7 8v6l-4 2v-8z',
  undo: 'M9 14 4 9l5-5M4 9h10a6 6 0 0 1 0 12h-3',
  gear: 'M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6zM19.4 15a1.7 1.7 0 0 0 .3 1.8l.1.1a2 2 0 1 1-2.8 2.8l-.1-.1a1.7 1.7 0 0 0-1.8-.3 1.7 1.7 0 0 0-1 1.5V21a2 2 0 1 1-4 0v-.1a1.7 1.7 0 0 0-1.1-1.5 1.7 1.7 0 0 0-1.8.3l-.1.1a2 2 0 1 1-2.8-2.8l.1-.1a1.7 1.7 0 0 0 .3-1.8 1.7 1.7 0 0 0-1.5-1H3a2 2 0 1 1 0-4h.1a1.7 1.7 0 0 0 1.5-1.1 1.7 1.7 0 0 0-.3-1.8l-.1-.1a2 2 0 1 1 2.8-2.8l.1.1a1.7 1.7 0 0 0 1.8.3H9a1.7 1.7 0 0 0 1-1.5V3a2 2 0 1 1 4 0v.1a1.7 1.7 0 0 0 1 1.5 1.7 1.7 0 0 0 1.8-.3l.1-.1a2 2 0 1 1 2.8 2.8l-.1.1a1.7 1.7 0 0 0-.3 1.8V9a1.7 1.7 0 0 0 1.5 1H21a2 2 0 1 1 0 4h-.1a1.7 1.7 0 0 0-1.5 1z',
}

/** Round icon button for the top bar. `badge` shows a small count. */
export function IconButton({ icon, label, onClick, disabled = false, on = false, hot = false, badge = 0 }) {
  return (
    <button type="button" className={`iconbtn${on ? ' on' : ''}${hot ? ' hot' : ''}`} aria-label={label} title={label} disabled={disabled} onClick={onClick}>
      <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
        <path d={ICONS[icon]} />
      </svg>
      {badge > 0 && <span className="iconbtn__badge">{badge}</span>}
    </button>
  )
}
