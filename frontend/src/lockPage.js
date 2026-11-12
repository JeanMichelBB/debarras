// iOS keeps the page elastic (and Chrome offers pull-to-refresh) even when nothing can scroll.
// CSS alone does not stop it there, so cancel any touch move that cannot scroll something:
// the page itself never moves, and inner lists stop dead at their top and bottom.
const SCROLLERS = '.screens, .screen.settings, .sheet__body, .auth, .onboarding'

export function lockPage() {
  let startX = 0
  let startY = 0
  document.addEventListener(
    'touchstart',
    (e) => {
      startX = e.touches[0].clientX
      startY = e.touches[0].clientY
    },
    { passive: true },
  )
  document.addEventListener(
    'touchmove',
    (e) => {
      if (e.touches.length > 1) return // pinch
      const dx = e.touches[0].clientX - startX
      // Sideways swipes inside a horizontally scrolling row (cast photos) are left alone.
      if (e.target.closest?.('[data-hscroll]') && Math.abs(dx) > Math.abs(e.touches[0].clientY - startY)) return
      const el = e.target.closest?.(SCROLLERS)
      if (!el || el.scrollHeight <= el.clientHeight + 1) {
        e.preventDefault()
        return
      }
      const dy = e.touches[0].clientY - startY // > 0: finger moving down, content wants to scroll up
      const atTop = el.scrollTop <= 0
      const atBottom = el.scrollTop + el.clientHeight >= el.scrollHeight - 1
      if ((atTop && dy > 0) || (atBottom && dy < 0)) e.preventDefault()
    },
    { passive: false },
  )
}
