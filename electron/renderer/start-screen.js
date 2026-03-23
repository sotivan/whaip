/**
 * WHAIP – Start screen
 * Shown on launch and each new tab. Click mic to begin session.
 */

const startScreen     = document.getElementById('start-screen')
const startMicBtn     = document.getElementById('start-mic-btn')
const startName       = document.getElementById('start-name')
const startHint       = document.getElementById('start-hint')
const settingsBtn     = document.getElementById('start-settings-btn')
const settingsPanel   = document.getElementById('start-settings-panel')
const themeToggle     = document.getElementById('theme-toggle')

// ── Visibility ────────────────────────────────────────────────────────────────

window.showStartScreen = function() {
  startScreen.classList.remove('ss-gone')
}

window.hideStartScreen = function() {
  startScreen.classList.add('ss-gone')
}

// ── Mic button ────────────────────────────────────────────────────────────────

startMicBtn.addEventListener('click', () => {
  startMicBtn.classList.add('ss-active')
  startHint.textContent = 'Escuchando…'
  // Trigger the real topbar mic toggle
  document.getElementById('btn-mic-toggle').click()
  setTimeout(window.hideStartScreen, 400)
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
