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
