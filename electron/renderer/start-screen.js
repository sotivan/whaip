/**
 * WHAIP – Start screen
 * Shown on launch and each new tab. Click mic to begin session.
 *
 * NOTE: Electron <webview> elements render in their own Chromium compositing
 * layer and ignore CSS z-index. We must hide them explicitly while the start
 * screen is visible, then restore them on dismiss.
 */

const startScreen     = document.getElementById('start-screen')
const startMicBtn     = document.getElementById('start-mic-btn')
const startName       = document.getElementById('start-name')
const startHint       = document.getElementById('start-hint')
const settingsBtn     = document.getElementById('start-settings-btn')
const settingsPanel   = document.getElementById('start-settings-panel')
const themeToggle     = document.getElementById('theme-toggle')

// ── Webview visibility helpers ────────────────────────────────────────────────

function setWebviewsVisible(visible) {
  document.querySelectorAll('webview').forEach(wv => {
    wv.style.visibility = visible ? '' : 'hidden'
  })
}

// Hide all webviews immediately so they don't bleed through the start screen
setWebviewsVisible(false)

// ── Visibility ────────────────────────────────────────────────────────────────

window.showStartScreen = function() {
  startScreen.classList.remove('ss-gone')
  setWebviewsVisible(false)
}

window.hideStartScreen = function() {
  if (startScreen.classList.contains('ss-gone')) return  // already hidden
  startScreen.classList.add('ss-gone')
  // Restore webviews and load home URL
  setWebviewsVisible(true)
  if (typeof window.loadHomeUrl === 'function') window.loadHomeUrl()
}

// ── Mic button ────────────────────────────────────────────────────────────────

startMicBtn.addEventListener('click', () => {
  startMicBtn.classList.add('ss-active')
  startHint.textContent = 'Escuchando…'
  // Trigger the real topbar mic toggle — start screen stays visible until
  // the agent responds with an action/transcript (see onAgentMessage below)
  document.getElementById('btn-mic-toggle').click()
})

// ── Settings panel ────────────────────────────────────────────────────────────

settingsBtn.addEventListener('click', e => {
  e.stopPropagation()
  settingsPanel.classList.toggle('ss-hidden')
})
document.addEventListener('click', () => settingsPanel.classList.add('ss-hidden'))

// ── Theme toggle ──────────────────────────────────────────────────────────────

function applyTheme(dark) {
  document.documentElement.setAttribute('data-theme', dark ? 'dark' : 'light')
  localStorage.setItem('whaip-theme', dark ? 'dark' : 'light')
  themeToggle.checked = dark
}

themeToggle.addEventListener('change', () => applyTheme(themeToggle.checked))

// Init theme
const savedTheme = localStorage.getItem('whaip-theme')
applyTheme(savedTheme !== 'light')   // default dark

// ── Receive user name from agent ──────────────────────────────────────────────

window.whaip.onAgentMessage(data => {
  if (data.type === 'profile:name') {
    const name = data.name || ''
    startName.textContent = name ? `, ${name}` : ''
  }
  // Auto-hide when agent sends a real response (not mere status pings)
  if (data.type === 'transcript' || data.type === 'action') {
    window.hideStartScreen()
  }
})

// ── Hide start screen when user types in address bar ─────────────────────────

document.getElementById('address-bar').addEventListener('keydown', e => {
  if (e.key === 'Enter') window.hideStartScreen()
})

// ── New tab event (fired by tabs.js) ─────────────────────────────────────────

window.addEventListener('whaip:newtab', () => {
  startMicBtn.classList.remove('ss-active')
  startHint.textContent = 'Pulsa para comenzar'
  window.showStartScreen()
})
