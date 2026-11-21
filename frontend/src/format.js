/** "2027-05-01" as a short local date, in the app language. */
export function fmtDate(iso, lang = 'en') {
  const d = new Date(`${iso}T12:00:00`)
  if (Number.isNaN(d.getTime())) return iso
  return d.toLocaleDateString(lang === 'fr' ? 'fr-CA' : 'en-US', { year: 'numeric', month: 'short', day: 'numeric' })
}

/** Today as yyyy-mm-dd in local time. */
export const today = () => {
  const d = new Date()
  const p = (n) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())}`
}

export const isUpcoming = (iso) => !!iso && iso > today()
