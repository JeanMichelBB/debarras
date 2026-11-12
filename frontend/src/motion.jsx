// One place for how the app moves. Use these instead of writing new numbers in components:
// a new screen then feels like the rest of the app without extra work.
//
// Rules: keep motion under ~300ms, animate only transform and opacity, and let <MotionConfig reducedMotion="user">
// (in App) drop movement for people who turned Reduce Motion on. They still get a quick fade.
import { useLayoutEffect, useRef, useState } from 'react'
import { motion } from 'framer-motion'

// Springs: snap = taps and small controls, base = sheets and panels, soft = things that travel.
export const snap = { type: 'spring', stiffness: 600, damping: 34 }
export const base = { type: 'spring', stiffness: 420, damping: 36, mass: 0.9 }
export const soft = { type: 'spring', stiffness: 260, damping: 30 }
// Tweens: ease-out for things arriving, ease-in for things leaving.
export const enter = { duration: 0.2, ease: [0.2, 0.8, 0.2, 1] }
export const leave = { duration: 0.18, ease: [0.4, 0, 1, 1] }

// Ready-made props for the common cases: <motion.div {...fadeUp} />
export const fadeUp = { initial: { opacity: 0, y: 8 }, animate: { opacity: 1, y: 0, transition: enter }, exit: { opacity: 0, y: 4, transition: leave } }
export const fade = { initial: { opacity: 0 }, animate: { opacity: 1, transition: enter }, exit: { opacity: 0, transition: leave } }
export const slideDown = { initial: { opacity: 0, y: -8 }, animate: { opacity: 1, y: 0, transition: enter }, exit: { opacity: 0, y: -6, transition: leave } }
export const pop = { initial: { opacity: 0, scale: 0.6 }, animate: { opacity: 1, scale: 1, transition: snap }, exit: { opacity: 0, scale: 0.6, transition: leave } }
export const tap = { whileTap: { scale: 0.92 }, transition: snap }

/** Item i of a list: fades in with a short stagger (capped so long lists do not wait). */
export const listItem = (i) => ({
  initial: { opacity: 0, scale: 0.96 },
  animate: { opacity: 1, scale: 1, transition: { ...enter, delay: Math.min(i, 12) * 0.025 } },
})

/** Wrapper for content that should fade in: <FadeIn tag="section" className="block">. */
export function FadeIn({ tag = 'div', children, ...rest }) {
  const Tag = motion[tag]
  return <Tag {...fadeUp} {...rest}>{children}</Tag>
}

/**
 * Text that opens and closes smoothly (Read more / Show less). `collapsed` is the closed height in px;
 * text shorter than that is shown in full. The height animates, so the content below glides instead of jumping.
 */
export function Expandable({ open, collapsed = 112, children }) {
  const inner = useRef(null)
  const [full, setFull] = useState(null)
  useLayoutEffect(() => {
    const el = inner.current
    if (!el) return undefined
    const measure = () => setFull(el.scrollHeight)
    measure()
    const ro = new ResizeObserver(measure)
    ro.observe(el)
    return () => ro.disconnect()
  }, [])
  const needs = full !== null && full > collapsed + 8
  const height = !needs ? 'auto' : open ? full : collapsed
  return (
    <motion.div className={`expandable${needs && !open ? ' is-clamped' : ''}`} initial={false} animate={{ height }} transition={base}>
      <div ref={inner}>{children}</div>
    </motion.div>
  )
}
