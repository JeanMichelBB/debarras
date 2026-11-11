import { test } from 'node:test'
import assert from 'node:assert/strict'
import { DICTS, LANGS, DEFAULT_LANG, translate, normalizeLang } from './i18n.js'

test('English is the default and the only fallback', () => {
  assert.equal(DEFAULT_LANG, 'en')
  assert.equal(normalizeLang('de'), 'en')
  assert.equal(normalizeLang(undefined), 'en')
  assert.equal(normalizeLang('fr'), 'fr')
})

test('French has exactly the same keys as English', () => {
  const en = Object.keys(DICTS.en).sort()
  const fr = Object.keys(DICTS.fr).sort()
  assert.deepEqual(fr, en)
})

test('no empty translations', () => {
  for (const lang of LANGS) for (const [k, v] of Object.entries(DICTS[lang])) assert.ok(v.trim(), `${lang}.${k}`)
})

test('placeholders match between languages', () => {
  const vars = (s) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort()
  for (const k of Object.keys(DICTS.en)) assert.deepEqual(vars(DICTS.fr[k]), vars(DICTS.en[k]), k)
})

test('translate fills variables and falls back', () => {
  assert.equal(translate('en', 'd_where', { region: 'CA' }), 'Where to watch in CA')
  assert.equal(translate('fr', 'd_where', { region: 'CA' }), 'Où regarder : CA')
  assert.equal(translate('fr', 'no_such_key'), 'no_such_key')
  assert.equal(translate('en', 'd_runtime'), '{n} min') // unfilled placeholder stays visible
  assert.equal(translate('xx', 'undo'), 'Undo')
})
