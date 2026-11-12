import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AnimatePresence, motion } from 'framer-motion'
import { fadeUp, slideDown } from './motion.jsx'
import { api } from './api.js'
import { commitSwipe, removeSwipe, sameTitle, EVT_SWIPE, EVT_UNDO } from './actions.js'
import { decisionForKey, filterParams, countActiveFilters, EMPTY_FILTERS } from './swipeLogic.js'
import { loadFilters, saveFilters } from './storage.js'
import Deck from './Deck.jsx'
import FiltersPanel from './FiltersPanel.jsx'
import { IconButton, Mark } from './ui.jsx'
import { useApp } from './ctx.jsx'

const BATCH = 10 // titles fetched at a time
const LOW = 12 // when the pile drops below this many cards, the next batch loads quietly and fades in at the bottom

// Dev only: add ?loading to the address to hold the pile loader for testing.
const HOLD_LOADING = import.meta.env.DEV && new URLSearchParams(window.location.search).has('loading')

const idOf = (c) => `${c.media_type}:${c.tmdb_id}`

export default function Sort({ active, sheetOpen, openDetails, actionsSlot, similar, closeSignal, onBeforeFilters }) {
  const { t, notify, errorText } = useApp()
  const [filters, setFilters] = useState(loadFilters)
  const [stack, setStack] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [exhausted, setExhausted] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [canUndo, setCanUndo] = useState(false)
  const [wantCount, setWantCount] = useState(0)
  const [likeOf, setLikeOf] = useState(null) // title the current pile was built from

  const deck = useRef(null)
  useEffect(() => setShowFilters(false), [closeSignal]) // another sheet opened from the bar
  const stackRef = useRef([])
  const history = useRef([])
  // Titles decided this session. A refill that was already in flight when the swipe happened
  // can still contain them, so every response is filtered against this set.
  const decided = useRef(new Set())
  const loadingRef = useRef(false)
  const exhaustedRef = useRef(false)
  const pageRef = useRef(1)
  const gen = useRef(0)
  const shuffleNext = useRef(false) // Apply in the filters reshuffles the pile, even if nothing changed
  const pendingSource = useRef(null) // 'wild' = next reload ignores what the user liked
  stackRef.current = stack

  const fetchMore = useCallback(
    async (reset = false, opts = {}) => {
      if (loadingRef.current && !reset) return
      if (!reset && exhaustedRef.current) return
      const myGen = reset ? ++gen.current : gen.current
      if (reset) {
        pageRef.current = opts.page || 1
        exhaustedRef.current = false
        setExhausted(false)
      }
      loadingRef.current = true
      setLoading(true)
      setError(null)
      try {
        const exclude = (reset ? [] : stackRef.current).map(idOf).join(',')
        const res = await api.queue({ ...filterParams(filters), limit: BATCH, page: pageRef.current, exclude, ...(opts.source && { source: opts.source }), ...(opts.shuffle && { shuffle: 1 }) })
        if (myGen !== gen.current) return
        pageRef.current = res.next_page
        if (res.cards.length === 0) {
          exhaustedRef.current = true
          setExhausted(true)
        }
        setStack((s) => {
          const base = reset ? [] : s
          const have = new Set(base.map(idOf))
          return [...base, ...res.cards.filter((c) => !have.has(idOf(c)) && !decided.current.has(idOf(c)))]
        })
      } catch (e) {
        if (myGen === gen.current) setError(errorText(e, 'sort_error'))
      } finally {
        if (myGen === gen.current) {
          loadingRef.current = false
          setLoading(false)
        }
      }
    },
    [filters, errorText],
  )

  // Reload from scratch whenever the filters change (and on first mount).
  useEffect(() => {
    history.current = []
    setCanUndo(false)
    const src = pendingSource.current
    pendingSource.current = null
    // "Surprise me" starts a few pages into the trending list so it differs from the usual pile.
    const shuffle = shuffleNext.current
    shuffleNext.current = false
    if (src) fetchMore(true, { source: src, page: 2 + Math.floor(Math.random() * 6) })
    else fetchMore(true, shuffle ? { shuffle: true, page: 1 + Math.floor(Math.random() * 3) } : {})
  }, [fetchMore])

  const removeFromStack = (item) => setStack((s) => s.filter((c) => !sameTitle(c, item)))

  const onDecide = async (status, card) => {
    if (!stackRef.current.some((c) => sameTitle(c, card))) return // already handled
    removeFromStack(card)
    decided.current.add(idOf(card))
    history.current.push(card)
    setCanUndo(true)
    try {
      await commitSwipe(status, card, 'deck')
    } catch (e) {
      decided.current.delete(idOf(card))
      setStack((s) => [card, ...s])
      history.current.pop()
      setCanUndo(history.current.length > 0)
      notify(errorText(e, 'save_failed'), 'error')
    }
  }

  const undo = async () => {
    const card = history.current.pop()
    setCanUndo(history.current.length > 0)
    if (!card) return
    try {
      await removeSwipe(card)
      decided.current.delete(idOf(card))
      setStack((s) => (s.some((c) => sameTitle(c, card)) ? s : [card, ...s]))
      notify(t('undone'))
    } catch (e) {
      history.current.push(card)
      setCanUndo(true)
      notify(errorText(e, 'save_failed'), 'error')
    }
  }

  // Decisions made in the detail sheet also leave the pile (and become undoable).
  useEffect(() => {
    const onSwipe = (e) => {
      const { item, source } = e.detail
      if (source !== 'sheet') return
      decided.current.add(idOf(item))
      if (stackRef.current.some((c) => sameTitle(c, item))) {
        removeFromStack(item)
        history.current.push(item)
        setCanUndo(true)
      }
    }
    const onUndo = (e) => decided.current.delete(idOf(e.detail.item))
    window.addEventListener(EVT_SWIPE, onSwipe)
    window.addEventListener(EVT_UNDO, onUndo)
    return () => {
      window.removeEventListener(EVT_SWIPE, onSwipe)
      window.removeEventListener(EVT_UNDO, onUndo)
    }
  }, [])

  // Keyboard: arrows decide, Ctrl/Cmd+Z = undo.
  useEffect(() => {
    if (!active || sheetOpen || showFilters) return undefined
    const onKey = (e) => {
      if (e.target.closest?.('input, select, textarea, button, [contenteditable]')) return
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'z') {
        e.preventDefault()
        undo()
        return
      }
      if (e.metaKey || e.ctrlKey || e.altKey) return
      const d = decisionForKey(e.key)
      if (d) {
        e.preventDefault()
        deck.current?.trigger(d)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  const applyFilters = (f) => {
    setLikeOf(null)
    shuffleNext.current = true
    saveFilters(f)
    setFilters({ ...f })
    setShowFilters(false)
  }

  const nActive = countActiveFilters(filters)
  const empty = stack.length === 0

  // Keep the pile topped up: no "pile cleared" stop. New cards arrive at the bottom of the pile.
  useEffect(() => {
    if (loading || error || exhausted || HOLD_LOADING) return
    if (likeOf && stack.length === 0) {
      setLikeOf(null) // a themed pile ran out: go back to the usual pile
      fetchMore(true)
    } else if (!likeOf && stack.length < LOW) {
      fetchMore()
    }
  }, [stack.length, loading, error, exhausted, likeOf, fetchMore])

  // pickTonight, moreLikeLiked and surprise below are ready to be wired to a button; they have no home in the UI yet.
  const pickTonight = async () => {
    try {
      const total = (await api.stats()).want || 0
      if (!total) return notify(t('sort_tonight_none'))
      const res = await api.swipes({ status: 'want', limit: 1, offset: Math.floor(Math.random() * total) })
      if (res.items[0]) openDetails(res.items[0], res.items[0].status)
    } catch (e) {
      notify(errorText(e), 'error')
    }
  }

  const moreLikeLiked = async () => {
    setLoading(true)
    try {
      const res = await api.queue({ ...filterParams(filters), limit: BATCH, source: 'related' })
      const fresh = res.cards.filter((c) => !decided.current.has(idOf(c)))
      if (!fresh.length) notify(t('sort_related_none'))
      else setStack(fresh)
    } catch (e) {
      notify(errorText(e, 'sort_error'), 'error')
    } finally {
      setLoading(false)
    }
  }

  // "More like this" from a detail sheet: replace the pile with titles similar to that one.
  useEffect(() => {
    if (!similar) return
    const { label, query } = similar
    let live = true
    setLoading(true)
    setError(null)
    api.queue({ limit: BATCH, ...query })
      .then((res) => {
        if (!live) return
        const fresh = res.cards.filter((c) => !decided.current.has(idOf(c)))
        if (!fresh.length) return notify(t('sort_similar_none', { title: label }))
        history.current = []
        setCanUndo(false)
        exhaustedRef.current = false
        setExhausted(false)
        setLikeOf(similar)
        setStack(fresh)
      })
      .catch((e) => live && notify(errorText(e, 'sort_error'), 'error'))
      .finally(() => live && setLoading(false))
    return () => { live = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [similar])

  const backToMine = () => {
    setLikeOf(null)
    fetchMore(true)
  }

  const surprise = () => {
    setLikeOf(null)
    pendingSource.current = 'wild'
    saveFilters(EMPTY_FILTERS)
    setFilters({ ...EMPTY_FILTERS })
  }

  return (
    <section className="screen sort" aria-label={t('nav_sort')}>
      {active && actionsSlot && createPortal(
        <>
          <IconButton icon="filter" label={t('filters')} badge={nActive} on={showFilters} pill onClick={() => { if (showFilters) { setShowFilters(false); return } onBeforeFilters?.(); setShowFilters(true) }} />
          <IconButton icon="undo" label={t('undo')} hot={canUndo} disabled={!canUndo} onClick={undo} />
        </>,
        actionsSlot,
      )}
      <div className="stage">
        <AnimatePresence>
          {likeOf && !empty && (
            <motion.p key="similar" className="similar-bar" {...slideDown}>
              <span>{t(likeOf.kind === 'title' ? 'sort_similar_to' : 'sort_person_to', { title: likeOf.label })}</span>
              <button type="button" className="linkbtn" onClick={backToMine}>{t('sort_similar_back')}</button>
            </motion.p>
          )}
        </AnimatePresence>
        {(HOLD_LOADING || (empty && loading)) && (
          <div className="loading-mark" role="status">
            <Mark loading />
            <span>{t('sort_loading')}</span>
          </div>
        )}
        {empty && !loading && error && (
          <motion.div className="empty" {...fadeUp}>
            <p>{error}</p>
            <button type="button" className="btn btn--primary" onClick={() => fetchMore(true)}>{t('retry')}</button>
          </motion.div>
        )}
        {empty && !loading && !error && exhausted && (
          <motion.div className="empty" {...fadeUp}>
            <h2>{t('sort_empty_title')}</h2>
            <p>{t('sort_empty_body')}</p>
            <button type="button" className="btn btn--primary" onClick={() => setShowFilters(true)}>{t('sort_change_filters')}</button>
          </motion.div>
        )}
        {!empty && !HOLD_LOADING && <Deck ref={deck} cards={stack} onDecide={onDecide} onDetails={openDetails} />}
      </div>

      <AnimatePresence>
        {showFilters && (
          <FiltersPanel
            key="filters"
            value={filters}
            onApply={applyFilters}
            onClose={() => setShowFilters(false)}
          />
        )}
      </AnimatePresence>
    </section>
  )
}
