import { EMPTY_FILTERS } from './swipeLogic.js'

const FILTERS_KEY = 'debarras_filters'
const LANG_KEY = 'debarras_lang'
const ONBOARDED_KEY = 'debarras_onboarded'
const TUTORIAL_KEY = 'debarras_tutorial'

export function loadFilters() {
  try {
    return { ...EMPTY_FILTERS, ...JSON.parse(localStorage.getItem(FILTERS_KEY) || '{}') }
  } catch {
    return { ...EMPTY_FILTERS }
  }
}
export const saveFilters = (f) => localStorage.setItem(FILTERS_KEY, JSON.stringify(f))

export const loadLang = () => localStorage.getItem(LANG_KEY)
export const saveLang = (l) => localStorage.setItem(LANG_KEY, l)

export const isOnboarded = () => localStorage.getItem(ONBOARDED_KEY) === '1'
export const markOnboarded = () => localStorage.setItem(ONBOARDED_KEY, '1')

export const isTutorialSeen = () => localStorage.getItem(TUTORIAL_KEY) === '1'
export const markTutorialSeen = () => localStorage.setItem(TUTORIAL_KEY, '1')
export const resetTutorial = () => localStorage.removeItem(TUTORIAL_KEY)

// Sheets the user opened (titles, people, studios), newest first. Kept on this device only.
const HISTORY_KEY = 'debarras_history'
const HISTORY_MAX = 30
export const historyKey = (e) => (e.type === 'detail' ? `${e.item.media_type}:${e.item.tmdb_id}` : `${e.type}:${e.id}`)

export function loadHistory() {
  try {
    const list = JSON.parse(localStorage.getItem(HISTORY_KEY) || '[]')
    return Array.isArray(list) ? list : []
  } catch {
    return []
  }
}
export function pushHistory(entry) {
  const { status, ...rest } = entry // a stored status would go stale
  const list = loadHistory().filter((x) => historyKey(x) !== historyKey(rest))
  list.unshift({ ...rest, at: Date.now() })
  localStorage.setItem(HISTORY_KEY, JSON.stringify(list.slice(0, HISTORY_MAX)))
}
export const clearHistory = () => localStorage.removeItem(HISTORY_KEY)

// Lists remembers the last tab and sort. Want to watch is the default: it is the backlog.
export const loadListsPrefs = () => ({
  tab: localStorage.getItem('debarras_lists_tab') || 'want',
  sort: localStorage.getItem('debarras_lists_sort') || 'recent',
})
export const saveListsTab = (v) => localStorage.setItem('debarras_lists_tab', v)
export const saveListsSort = (v) => localStorage.setItem('debarras_lists_sort', v)
