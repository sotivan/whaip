/**
 * WHAIP – Multi-tab manager
 * Must be loaded BEFORE browser.js
 */

let _tabs = []         // array of { id, url, title, favicon, webview }
let _activeId = null   // id of active tab

const tabsBar     = document.getElementById('tabs-bar')
const tabsList    = document.getElementById('tabs-list')
const btnNewTab   = document.getElementById('btn-new-tab')
const browserPane = document.getElementById('browser-pane')

// ── Public API used by browser.js ─────────────────────────────────────────────

window.getActiveWebview = () => {
  const t = _tabs.find(t => t.id === _activeId)
  return t ? t.webview : null
}

window.getActiveTab = () => _tabs.find(t => t.id === _activeId) || null

// ── Create tab ────────────────────────────────────────────────────────────────

function createTab(url) {
  const id  = 'tab-' + Date.now()
  const wv  = document.createElement('webview')
  wv.setAttribute('allowpopups', '')
  wv.setAttribute('webpreferences', 'contextIsolation=false, nodeIntegration=false')
  wv.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:none'
  wv.src = url || 'https://www.google.com'

  // Bind per-webview events (address bar, title, loading state)
  bindTabEvents(id, wv)

  browserPane.appendChild(wv)

  const tab = { id, url: wv.src, title: 'Nueva pestaña', favicon: '', webview: wv }
  _tabs.push(tab)
  renderTabs()
  switchTab(id)
  // Show start screen for new tabs (not the very first one — that's shown from HTML)
  if (_tabs.length > 1) {
    window.dispatchEvent(new CustomEvent('whaip:newtab'))
  }
  return tab
}

// ── Switch tab ────────────────────────────────────────────────────────────────

function switchTab(id) {
  _activeId = id
  _tabs.forEach(t => {
    t.webview.style.display = t.id === id ? 'block' : 'none'
  })
  renderTabs()

  // Hide start screen when switching to an active browsing tab
  const switching = _tabs.find(t => t.id === id)
  if (switching && switching.url && !switching.url.startsWith('https://www.google.com') &&
      switching.url !== 'about:blank' && typeof window.hideStartScreen === 'function') {
    window.hideStartScreen()
  }

  // Update shared UI
  const t = _tabs.find(t => t.id === id)
  if (t) {
    const ab = document.getElementById('address-bar')
    if (ab) ab.value = t.url || ''
    const btnBack    = document.getElementById('btn-back')
    const btnForward = document.getElementById('btn-forward')
    if (btnBack)    btnBack.style.opacity    = t.webview.canGoBack?.()    ? '1' : '0.35'
    if (btnForward) btnForward.style.opacity = t.webview.canGoForward?.() ? '1' : '0.35'
  }
}

// ── Close tab ─────────────────────────────────────────────────────────────────

function closeTab(id) {
  if (_tabs.length === 1) {
    // Last tab — navigate to new tab page instead of closing
    const t = _tabs[0]
    t.webview.src = 'https://www.google.com'
    t.title = 'Nueva pestaña'
    t.url   = 'https://www.google.com'
    renderTabs()
    return
  }

  const idx = _tabs.findIndex(t => t.id === id)
  const tab = _tabs[idx]
  tab.webview.remove()
  _tabs.splice(idx, 1)

  if (_activeId === id) {
    const next = _tabs[Math.min(idx, _tabs.length - 1)]
    switchTab(next.id)
  } else {
    renderTabs()
  }
}

// ── Per-webview events ────────────────────────────────────────────────────────

function bindTabEvents(id, wv) {
  wv.addEventListener('did-navigate', e => {
    const t = _tabs.find(t => t.id === id)
    if (t) { t.url = e.url; renderTabs() }
    if (_activeId === id) {
      const ab = document.getElementById('address-bar')
      if (ab) ab.value = e.url
      const btnBack    = document.getElementById('btn-back')
      const btnForward = document.getElementById('btn-forward')
      if (btnBack)    btnBack.style.opacity    = wv.canGoBack?.()    ? '1' : '0.35'
      if (btnForward) btnForward.style.opacity = wv.canGoForward?.() ? '1' : '0.35'
      window.whaip.sendToAgent({ type: 'page:context', url: e.url, title: t?.title || '' })
    }
  })

  wv.addEventListener('did-navigate-in-page', e => {
    const t = _tabs.find(t => t.id === id)
    if (t) t.url = e.url
    if (_activeId === id) {
      const ab = document.getElementById('address-bar')
      if (ab) ab.value = e.url
    }
  })

  wv.addEventListener('page-title-updated', e => {
    const t = _tabs.find(t => t.id === id)
    if (t) { t.title = e.title; renderTabs() }
    if (_activeId === id) {
      document.title = `${e.title} — WHAIP`
      window.whaip.sendToAgent({ type: 'page:context', url: t?.url || '', title: e.title })
    }
  })

  wv.addEventListener('page-favicon-updated', e => {
    const t = _tabs.find(t => t.id === id)
    if (t && e.favicons && e.favicons[0]) { t.favicon = e.favicons[0]; renderTabs() }
  })

  wv.addEventListener('did-start-loading', () => {
    if (_activeId !== id) return
    const btnReload = document.getElementById('btn-reload')
    if (btnReload) { btnReload.textContent = '✕'; btnReload.title = 'Stop'; btnReload.onclick = () => wv.stop() }
  })

  wv.addEventListener('did-stop-loading', () => {
    if (_activeId !== id) return
    const btnReload = document.getElementById('btn-reload')
    if (btnReload) { btnReload.textContent = '⟳'; btnReload.title = 'Reload'; btnReload.onclick = () => wv.reload() }
  })
}

// ── Render tab bar ────────────────────────────────────────────────────────────

function renderTabs() {
  tabsList.innerHTML = ''

  _tabs.forEach(t => {
    const tab = document.createElement('div')
    tab.className = 'tab-item' + (t.id === _activeId ? ' tab-active' : '')
    tab.dataset.id = t.id
    tab.title = t.url

    const favEl = t.favicon
      ? `<img class="tab-favicon" src="${t.favicon}" onerror="this.style.display='none'">`
      : '<span class="tab-favicon-placeholder">○</span>'

    const label = (t.title || t.url || 'Nueva pestaña').slice(0, 24)

    tab.innerHTML = `
      ${favEl}
      <span class="tab-title">${escHtml(label)}</span>
      <button class="tab-close" title="Cerrar">×</button>
    `

    tab.addEventListener('click', e => {
      if (!e.target.classList.contains('tab-close')) switchTab(t.id)
    })
    tab.querySelector('.tab-close').addEventListener('click', e => {
      e.stopPropagation()
      closeTab(t.id)
    })

    tabsList.appendChild(tab)
  })
}

function escHtml(s) {
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

// ── New tab button ────────────────────────────────────────────────────────────

btnNewTab.addEventListener('click', () => createTab('https://www.google.com'))

// Cmd+T / Ctrl+T — new tab
document.addEventListener('keydown', e => {
  if ((e.metaKey || e.ctrlKey) && e.key === 't') { e.preventDefault(); createTab('https://www.google.com') }
  if ((e.metaKey || e.ctrlKey) && e.key === 'w') { e.preventDefault(); if (_activeId) closeTab(_activeId) }
})

// ── Init: create first tab using existing webview ────────────────────────────

;(function init() {
  // Use the existing <webview id="webview"> as the first tab
  const existing = document.getElementById('webview')
  if (existing) {
    const id  = 'tab-' + Date.now()
    existing.style.cssText = 'position:absolute;inset:0;width:100%;height:100%;display:block'
    const tab = { id, url: existing.src || 'https://www.google.com', title: 'Nueva pestaña', favicon: '', webview: existing }
    _tabs.push(tab)
    _activeId = id
    bindTabEvents(id, existing)
    renderTabs()
  }
})()
