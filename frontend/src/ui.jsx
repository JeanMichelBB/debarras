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
