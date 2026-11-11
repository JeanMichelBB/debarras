import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { animate, motion, useMotionValue, useTransform } from 'framer-motion'
import { decide, withMomentum, FLY, PREVIEW, THRESHOLD } from './swipeLogic.js'
import { Poster, Stamp } from './ui.jsx'
import { useApp } from './ctx.jsx'

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
  const busy = useRef(false)
  const top = cards[0]
  const topKey = top ? `${top.media_type}:${top.tmdb_id}` : ''

  // A new top card starts centered and ready.
  useEffect(() => {
    x.set(0)
    y.set(0)
    setIntent(null)
    busy.current = false
  }, [topKey, x, y])

  const springBack = () => {
    animate(x, 0, SPRING)
    animate(y, 0, SPRING)
  }

  const fly = async (status) => {
    if (busy.current || !top) return
    busy.current = true
    setIntent(status)
    const to = FLY[status]
    await Promise.all([
      animate(x, to.x, { duration: 0.24, ease: 'easeIn' }),
      animate(y, to.y, { duration: 0.24, ease: 'easeIn' }),
    ])
    onDecide(status, top)
    setTimeout(() => (busy.current = false), 600) // safety net if the card did not change
  }

  useImperativeHandle(ref, () => ({
    trigger: (status) => (status === 'details' ? top && onDetails(top) : fly(status)),
  }))

  const behind = cards.slice(1, 3)

  return (
    <div className="deck">
      {behind
        .map((c, i) => (
          <div key={`${c.media_type}:${c.tmdb_id}`} className={`card card--behind card--behind-${i + 1}`} aria-hidden="true">
            <Poster src={c.poster} title={c.title} eager />
          </div>
        ))
        .reverse()}

      {top && (
        <motion.div
          key={topKey}
          className="card card--top"
          style={{ x, y, rotate }}
          drag
          dragMomentum={false}
          dragElastic={0.9}
          dragConstraints={{ left: 0, right: 0, top: 0, bottom: 0 }}
          whileTap={{ cursor: 'grabbing' }}
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
          onTap={() => onDetails(top)}
        >
          <Poster src={top.poster} title={top.title} eager />
          <div className="card__shade" />
          <div className="card__meta">
            <h2 className="card__title">{top.title}</h2>
            <p className="card__facts">
              {top.year && <span>{top.year}</span>}
              <span>{top.media_type === 'tv' ? t('type_tv') : t('type_movie')}</span>
              {top.vote_average ? <span>{top.vote_average.toFixed(1)} / 10</span> : null}
            </p>
            {top.reason && <p className="card__reason">{top.reason}</p>}
          </div>
          {intent && <Stamp status={intent} className={`card__stamp card__stamp--${intent}`} />}
        </motion.div>
      )}
    </div>
  )
})

export default Deck
