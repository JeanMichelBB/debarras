import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  decide, withMomentum, decisionForKey, filterParams, countActiveFilters, EMPTY_FILTERS, THRESHOLD,
} from './swipeLogic.js'

test('each direction maps to its decision', () => {
  assert.equal(decide({ x: 150, y: 0 }), 'watched')
  assert.equal(decide({ x: -150, y: 0 }), 'not_now')
  assert.equal(decide({ x: 0, y: -150 }), 'want')
  assert.equal(decide({ x: 0, y: 150 }), 'details')
})

test('short drags do nothing', () => {
  assert.equal(decide({ x: THRESHOLD - 1, y: 0 }), null)
  assert.equal(decide({ x: 0, y: -(THRESHOLD - 1) }), null)
  assert.equal(decide({ x: 0, y: 0 }), null)
})

test('the dominant axis wins on diagonals', () => {
  assert.equal(decide({ x: 130, y: -120 }), 'watched')
  assert.equal(decide({ x: 120, y: -130 }), 'want')
  assert.equal(decide({ x: -90, y: -130 }), 'want')
  assert.equal(decide({ x: 100, y: 130 }), 'details')
})

test('a long diagonal still needs the winning axis to pass the threshold', () => {
  assert.equal(decide({ x: 100, y: -100 }), null)
})

test('a quick flick counts through momentum', () => {
  const o = withMomentum({ x: 60, y: 0 }, { x: 800, y: 0 })
  assert.equal(decide(o), 'watched')
  assert.equal(decide(withMomentum({ x: 60, y: 0 }, { x: 100, y: 0 })), null)
})

test('keyboard shortcuts', () => {
  assert.equal(decisionForKey('ArrowRight'), 'watched')
  assert.equal(decisionForKey('ArrowUp'), 'want')
  assert.equal(decisionForKey('ArrowLeft'), 'not_now')
  assert.equal(decisionForKey('ArrowDown'), 'details')
  assert.equal(decisionForKey('x'), null)
  assert.equal(decisionForKey('a'), null)
})

test('filter params only include what is set', () => {
  assert.deepEqual(filterParams(EMPTY_FILTERS), {})
  assert.deepEqual(
    filterParams({ media_type: 'tv', genres: [18, 35], year_min: '1990', year_max: '', min_rating: '7' }),
    { media_type: 'tv', genres: '18,35', year_min: '1990', min_rating: '7' },
  )
})

test('active filter count', () => {
  assert.equal(countActiveFilters(EMPTY_FILTERS), 0)
  assert.equal(countActiveFilters({ ...EMPTY_FILTERS, media_type: 'movie', genres: [1], min_rating: '6' }), 3)
})
