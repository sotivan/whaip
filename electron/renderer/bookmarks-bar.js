/**
 * WHAIP – Bookmarks bar
 * Receives bookmarks:list from agent → renders pills with favicon + title.
 * Click → navigate. Right-click → delete.
 */

const bookmarksBar  = document.getElementById('bookmarks-bar')
const bookmarksList = document.getElementById('bookmarks-list')

// ── Render ────────────────────────────────────────────────────────────────────

function renderBookmarks(bookmarks) {
  bookmarksList.innerHTML = ''

  if (!bookmarks || bookmarks.length === 0) {
    bookmarksBar.classList.add('bar-empty')
    return
  }

  bookmarksBar.classList.remove('bar-empty')

  bookmarks.forEach(b => {
    const pill = document.createElement('button')
    pill.className = 'bm-pill'
    pill.title = b.url

    const domain = (() => {
      try { return new URL(b.url).hostname.replace(/^www\./, '') } catch { return '' }
    })()
    const faviconSrc = b.favicon || (domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=16` : '')
    const label = (b.title || domain || b.url).slice(0, 22)

    pill.innerHTML = faviconSrc
      ? `<img class="bm-favicon" src="${faviconSrc}" onerror="this.style.display='none'" /><span class="bm-label">${escapeHtml(label)}</span>`
      : `<span class="bm-label">${escapeHtml(label)}</span>`

    // Click → navigate
    pill.addEventListener('click', () => {
      const webview = document.getElementById('webview')
      if (webview) webview.src = b.url
      const addressBar = document.getElementById('address-bar')
      if (addressBar) addressBar.value = b.url
    })

    // Right-click → context menu
    pill.addEventListener('contextmenu', e => {
      e.preventDefault()
      showBmContextMenu(e.clientX, e.clientY, b.url)
    })

    bookmarksList.appendChild(pill)
  })
}

// ── Context menu ──────────────────────────────────────────────────────────────

function showBmContextMenu(x, y, url) {
  removeBmContextMenu()
  const menu = document.createElement('div')
  menu.id = 'bm-context-menu'
  menu.style.cssText = `position:fixed;left:${x}px;top:${y}px;z-index:9999;
    background:#1a1a1e;border:1px solid #2e2e34;border-radius:6px;
    padding:4px;min-width:160px;box-shadow:0 4px 16px rgba(0,0,0,0.5)`
  menu.innerHTML = `
    <button class="bm-menu-item bm-menu-delete">🗑 Eliminar marcador</button>
    <button class="bm-menu-item">✏️ Abrir en nueva sesión</button>
  `
  menu.querySelector('.bm-menu-delete').addEventListener('click', () => {
    window.whaip.sendToAgent({ type: 'bookmark:remove', url })
    removeBmContextMenu()
  })
  menu.querySelector('.bm-menu-item:last-child').addEventListener('click', () => {
    window.open(url, '_blank')
    removeBmContextMenu()
  })
  document.body.appendChild(menu)
  // Close on click outside
  setTimeout(() => document.addEventListener('click', removeBmContextMenu, { once: true }), 10)
}

function removeBmContextMenu() {
  const m = document.getElementById('bm-context-menu')
  if (m) m.remove()
}

function escapeHtml(str) {
  return String(str).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;')
}

// ── Listen for updates from agent ─────────────────────────────────────────────

window.whaip.onAgentMessage(data => {
  if (data.type === 'bookmarks:list') {
    renderBookmarks(data.bookmarks || [])
  }
})

// ── Init: request bookmarks on load ──────────────────────────────────────────

;(function init() {
  // Will receive bookmarks:list push from agent on connect
  bookmarksBar.classList.add('bar-empty')
})()
