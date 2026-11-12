import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'framer-motion'
import { decide, withMomentum, FLY, PREVIEW, THRESHOLD } from './swipeLogic.js'
import { Poster, Stamp } from './ui.jsx'
import { useApp } from './ctx.jsx'

const BEHIND = 9 // cards visible under the top one (10 in the pile)
// Hand-dropped pile. Tilt and sideways nudge belong to the title (hashed from its id), not to its
// position, so a card keeps its own angle while it moves up the pile. Only the depth offset changes.
function look(card) {
  let h = Number(card.tmdb_id) * 2654435761 + (card.media_type === 'tv' ? 40503 : 0)
  const next = () => ((h = Math.imul(h ^ (h >>> 15), 2246822519) >>> 0) % 1000) / 1000
  next()
  return { tilt: (next() * 2 - 1) * 5, dx: (next() * 2 - 1) * 9 }
}
const SPRING = { type: 'spring', stiffness: 520, damping: 34 }

/**
 * The pile. The top card follows your finger; drag it past the threshold and it takes
 * the stamp for that direction. Buttons and keys call trigger() to do the same.
 */
const Deck = forwardRef(function Deck({ cards, onDecide, onDetails }, ref) {
  const { t } = useApp()
  const x = useMotionValue(0)
  const y = useMotionValue(0)
  const rotate = useTransform(x, [-260, 0, 260], [-9, 0, 9])
  const [intent, setIntent] = useState(null)
  const [flying, setFlying] = useState(false) // the top card is leaving: it must not accept a new touch
  const busy = useRef(false)
  const moved = useRef(false) // true once a press turned into a drag, so its release is not a tap
  const top = cards[0]
  const topKey = top ? `${top.media_type}:${top.tmdb_id}` : ''

  // A new top card starts centered and ready.
  useEffect(() => {
    x.set(0)
    y.set(0)
    setIntent(null)
    setFlying(false)
    busy.current = false
  }, [topKey, x, y])

  const springBack = () => {
    animate(x, 0, SPRING)
    animate(y, 0, SPRING)
  }

  const fly = async (status) => {
    if (busy.current || !top) return
    busy.current = true
    setFlying(true)
    setIntent(status)
    const to = FLY[status]
    // Never wait on the animation alone: if the browser interrupts it (touch cancel, the drag's own
    // snap-back taking over x), its promise may never settle and the card would stay locked.
    const flight = Promise.all([
      animate(x, to.x, { duration: 0.24, ease: 'easeIn' }),
      animate(y, to.y, { duration: 0.24, ease: 'easeIn' }),
    ]).catch(() => {})
    await Promise.race([flight, new Promise((r) => setTimeout(r, 500))])
    onDecide(status, top)
    setTimeout(() => { busy.current = false; setFlying(false) }, 600) // safety net if the card did not change
  }

  useImperativeHandle(ref, () => ({
    trigger: (status) => (status === 'details' ? top && onDetails(top) : fly(status)),
  }))

  const behind = cards.slice(1, 1 + BEHIND)

  return (
    <div className="deck">
      {behind
        .map((c, i) => (
          <div
            key={`${c.media_type}:${c.tmdb_id}`}
            className="card card--behind"
            style={{
              transform: `translate(${look(c).dx}px, ${(i + 1) * 3 + 4}px) rotate(${look(c).tilt}deg)`,
              filter: `brightness(${Math.max(0.3, 0.78 - i * 0.06)})`,
              zIndex: BEHIND - i,
            }}
            aria-hidden="true"
          >
            <Poster src={c.poster} title={c.title} eager={i < 3} />
          </div>
        ))
        .reverse()}

      {top && (
        <motion.div
          key={topKey}
          className="card-pose"
          initial={{ rotate: look(top).tilt, x: look(top).dx, y: 7 }}
          animate={{ rotate: 0, x: 0, y: 0 }}
          transition={{ type: 'spring', stiffness: 380, damping: 26 }}
        >
        <motion.div
          className="card card--top"
          // A quick flick can start on the card that is still flying off. When that card unmounts mid-drag,
          // framer keeps its global drag lock and no card can be dragged again until a reload.
          style={{ x, y, rotate, pointerEvents: flying ? 'none' : undefined }}
          drag
          dragMomentum={false}
          dragElastic={0.9}
          dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
          whileTap={{ cursor: 'grabbing' }}
          onTapStart={() => (moved.current = false)}
          onDragStart={() => (moved.current = true)}
          onDrag={(_, info) => {
            const d = decide(info.offset, PREVIEW)
            setIntent(d && d !== 'details' ? d : null)
          }}
          onDragEnd={(_, info) => {
            const d = decide(withMomentum(info.offset, info.velocity), THRESHOLD)
            if (!d) {
              setIntent(null)
              springBack()
            } else if (d === 'details') {
              setIntent(null)
              springBack()
              onDetails(top)
            } else {
              fly(d)
            }
          }}
          onTap={() => !moved.current && !busy.current && onDetails(top)}
        >
          <Poster src={top.poster} title={top.title} eager />
          <div className="card__shade" />
          <div className="card__meta">
            <h2 className="card__title">{top.title}</h2>
            <p className="card__facts">
              {top.year && <span>{top.year}</span>}
              <span>{top.media_type === 'tv' ? t('type_tv') : t('type_movie')}</span>
              {top.vote_average ? <span>{top.vote_average.toFixed(1)} / 10</span> : null}
              {top.genres?.length ? <span>{top.genres.join(' · ')}</span> : null}
            </p>
            {top.reason && <p className="card__reason">{top.reason}</p>}
          </div>
          {intent && <Stamp status={intent} className={`card__stamp card__stamp--${intent}`} />}
        </motion.div>
        </motion.div>
      )}
    </div>
  )
})

export default Deck
