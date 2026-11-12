import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { api } from './api.js'
import { commitSwipe, removeSwipe, sameTitle, EVT_SWIPE, EVT_UNDO } from './actions.js'
import { decisionForKey, filterParams, countActiveFilters } from './swipeLogic.js'
import { loadFilters, saveFilters } from './storage.js'
import Deck from './Deck.jsx'
import FiltersPanel from './FiltersPanel.jsx'
import { IconButton, Mark } from './ui.jsx'
import { useApp } from './ctx.jsx'

const BATCH = 10 // one pile = 10 titles; the next pile only loads when asked

// Dev only: add ?loading to the address to hold the pile loader for testing.
const HOLD_LOADING = import.meta.env.DEV && new URLSearchParams(window.location.search).has('loading')

const idOf = (c) => `${c.media_type}:${c.tmdb_id}`

export default function Sort({ active, sheetOpen, openDetails, actionsSlot }) {
  const { t, notify, errorText } = useApp()
  const [filters, setFilters] = useState(loadFilters)
  const [stack, setStack] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [exhausted, setExhausted] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [canUndo, setCanUndo] = useState(false)

  const deck = useRef(null)
  const stackRef = useRef([])
  const history = useRef([])
  // Titles decided this session. A refill that was already in flight when the swipe happened
  // can still contain them, so every response is filtered against this set.
  const decided = useRef(new Set())
  const loadingRef = useRef(false)
  const exhaustedRef = useRef(false)
  const pageRef = useRef(1)
  const gen = useRef(0)
  stackRef.current = stack

  const fetchMore = useCallback(
    async (reset = false) => {
      if (loadingRef.current && !reset) return
      if (!reset && exhaustedRef.current) return
      const myGen = reset ? ++gen.current : gen.current
      if (reset) {
        pageRef.current = 1
        exhaustedRef.current = false
        setExhausted(false)
      }
      loadingRef.current = true
      setLoading(true)
      setError(null)
      try {
        const exclude = (reset ? [] : stackRef.current).map(idOf).join(',')
        const res = await api.queue({ ...filterParams(filters), limit: BATCH, page: pageRef.current, exclude })
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
    fetchMore(true)
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
    saveFilters(f)
    setFilters(f)
    setShowFilters(false)
  }

  const nActive = countActiveFilters(filters)
  const empty = stack.length === 0

  return (
    <section className="screen sort" aria-label={t('nav_sort')}>
      {active && actionsSlot && createPortal(
        <>
          <IconButton icon="filter" label={t('filters')} badge={nActive} onClick={() => setShowFilters(true)} />
          <IconButton icon="undo" label={t('undo')} hot={canUndo} disabled={!canUndo} onClick={undo} />
        </>,
        actionsSlot,
      )}
      <div className="stage">
        {(HOLD_LOADING || (empty && loading)) && (
          <div className="loading-mark" role="status">
            <Mark loading />
            <span>{t('sort_loading')}</span>
          </div>
        )}
        {empty && !loading && error && (
          <div className="empty">
            <p>{error}</p>
            <button type="button" className="btn btn--primary" onClick={() => fetchMore(true)}>{t('retry')}</button>
          </div>
        )}
        {empty && !loading && !error && exhausted && (
          <div className="empty">
            <h2>{t('sort_empty_title')}</h2>
            <p>{t('sort_empty_body')}</p>
            <button type="button" className="btn btn--primary" onClick={() => setShowFilters(true)}>{t('sort_change_filters')}</button>
          </div>
        )}
        {empty && !loading && !error && !exhausted && (
          <div className="empty">
            <h2>{t('sort_done_title')}</h2>
            <p>{t('sort_done_body')}</p>
            <button type="button" className="btn btn--primary" onClick={() => fetchMore()}>{t('sort_more')}</button>
            <button type="button" className="btn btn--ghost" onClick={() => setShowFilters(true)}>{t('sort_explore')}</button>
          </div>
        )}
        {!empty && !HOLD_LOADING && <Deck ref={deck} cards={stack} onDecide={onDecide} onDetails={openDetails} />}
      </div>

      {showFilters && <FiltersPanel value={filters} onApply={applyFilters} onClose={() => setShowFilters(false)} />}
    </section>
  )
}
