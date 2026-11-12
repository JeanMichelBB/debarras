import { useState } from 'react'
import { motion } from 'framer-motion'
import { IconButton, Stamp } from './ui.jsx'
import { useApp } from './ctx.jsx'

// One step per gesture, then undo. `to` is where the demo card slides.
const STEPS = [
  { id: 'watched', to: { x: 96, y: 0, rotate: 10 } },
  { id: 'want', to: { x: 0, y: -96, rotate: 0 } },
  { id: 'not_now', to: { x: -96, y: 0, rotate: -10 } },
  { id: 'details', to: { x: 0, y: 70, rotate: 0 } },
  { id: 'undo', to: null },
]

function Demo({ step }) {
  const { t } = useApp()
  if (!step.to) {
    return (
      <div className="tutorial__demo tutorial__demo--undo">
        <IconButton icon="undo" hot label={t('undo')} onClick={() => {}} />
      </div>
    )
  }
  const { x, y, rotate } = step.to
  return (
    <div className="tutorial__demo">
      <motion.div
        key={step.id}
        className="tutorial__card"
        animate={{ x: [0, x, x, 0], y: [0, y, y, 0], rotate: [0, rotate, rotate, 0] }}
        transition={{ duration: 2.4, times: [0, 0.35, 0.75, 1], ease: 'easeInOut', repeat: Infinity, repeatDelay: 0.4 }}
      >
        <span className="tutorial__bar" />
        <span className="tutorial__bar tutorial__bar--short" />
        <motion.span
          className="tutorial__stampwrap"
          animate={{ opacity: [0, 1, 1, 0] }}
          transition={{ duration: 2.4, times: [0.2, 0.4, 0.75, 0.9], repeat: Infinity, repeatDelay: 0.4 }}
        >
          {step.id === 'details' ? (
            <span className="stamp stamp--details tutorial__stamp">{t('details')}</span>
          ) : (
            <Stamp status={step.id} className="tutorial__stamp" />
          )}
        </motion.span>
      </motion.div>
    </div>
  )
}

/** First-run guide: one screen per gesture. */
export default function Tutorial({ onDone }) {
  const { t } = useApp()
  const [i, setI] = useState(0)
  const step = STEPS[i]
  const last = i === STEPS.length - 1

  return (
    <div className="tutorial" role="dialog" aria-modal="true" aria-label={t('tut_title')}>
      <div className="tutorial__body">
        <Demo step={step} />
        <h2 className="tutorial__title">{t(`tut_${step.id}_t`)}</h2>
        <p className="tutorial__text">{t(`tut_${step.id}_b`)}</p>
        <div className="tutorial__dots" aria-hidden="true">
          {STEPS.map((s, n) => <span key={s.id} className={n === i ? 'on' : ''} />)}
        </div>
        <button type="button" className="btn btn--primary" onClick={() => (last ? onDone() : setI(i + 1))}>
          {last ? t('tut_go') : t('tut_next')}
        </button>
        {!last && <button type="button" className="linkbtn" onClick={onDone}>{t('tut_skip')}</button>}
      </div>
    </div>
  )
}
