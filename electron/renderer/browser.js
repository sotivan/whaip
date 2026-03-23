/**
 * WHAIP – Browser pane controller
 */

const webview    = document.getElementById('webview')
const addressBar = document.getElementById('address-bar')
const btnBack    = document.getElementById('btn-back')
const btnForward = document.getElementById('btn-forward')
const btnReload  = document.getElementById('btn-reload')

// ── Address bar ─────────────────────────────────────────────────────────────

function normalizeUrl(input) {
  const s = input.trim()
  if (!s) return 'https://www.google.com'
  // Looks like a URL?
  if (/^(https?|whp):\/\//i.test(s)) return s
  if (/^localhost|\d+\.\d+\.\d+\.\d+/.test(s)) return `http://${s}`
  if (/\.\w{2,}(\/|$)/.test(s) && !s.includes(' ')) return `https://${s}`
  // Treat as search query
  return `https://www.google.com/search?q=${encodeURIComponent(s)}`
}

addressBar.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    webview.src = normalizeUrl(addressBar.value)
    webview.blur()
  }
})

// ── Nav buttons ──────────────────────────────────────────────────────────────

btnBack.addEventListener('click',    () => webview.canGoBack()    && webview.goBack())
btnForward.addEventListener('click', () => webview.canGoForward() && webview.goForward())
btnReload.addEventListener('click',  () => webview.reload())

// ── Webview events ────────────────────────────────────────────────────────────

webview.addEventListener('did-navigate', e => {
  addressBar.value = e.url
  btnBack.style.opacity    = webview.canGoBack()    ? '1' : '0.35'
  btnForward.style.opacity = webview.canGoForward() ? '1' : '0.35'
})

webview.addEventListener('did-navigate-in-page', e => {
  addressBar.value = e.url
})

webview.addEventListener('page-title-updated', e => {
  document.title = `${e.title} — WHAIP`
})

webview.addEventListener('did-start-loading', () => {
  btnReload.textContent = '✕'
  btnReload.title = 'Stop'
  btnReload.onclick = () => webview.stop()
})

webview.addEventListener('did-stop-loading', () => {
  btnReload.textContent = '⟳'
  btnReload.title = 'Reload'
  btnReload.onclick = () => webview.reload()
})

// ── WHP action executor ───────────────────────────────────────────────────────

async function executeAction(cmd) {
  switch (cmd.action) {
    case 'click':     return handleClick(cmd.x, cmd.y)
    case 'type':      return handleType(cmd.text)
    case 'scroll':    return handleScroll(cmd.direction)
    case 'navigate':  return handleNavigate(cmd.text)
    case 'wait':      return   // agent loop handles timing
    case 'done':      return window.dispatchEvent(new CustomEvent('whaip:done', { detail: cmd }))
    default: console.warn('[browser] unknown action:', cmd.action)
  }
}

function handleClick(x, y) {
  webview.executeJavaScript(`
    (function() {
      const el = document.elementFromPoint(${x}, ${y});
      if (el) {
        el.dispatchEvent(new MouseEvent('mousedown', { bubbles:true, clientX:${x}, clientY:${y} }));
        el.dispatchEvent(new MouseEvent('mouseup',   { bubbles:true, clientX:${x}, clientY:${y} }));
        el.click();
      }
    })()
  `).catch(console.error)
}

function handleType(text) {
  if (!text) return
  webview.executeJavaScript(`
    (function() {
      const el = document.activeElement;
      if (!el) return;
      const nativeInput = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
      if (nativeInput) nativeInput.set.call(el, ${JSON.stringify(text)});
      else el.value = ${JSON.stringify(text)};
      el.dispatchEvent(new Event('input',  { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
    })()
  `).catch(console.error)
}

function handleScroll(direction) {
  const dy = direction === 'down' ? 400 : -400
  webview.executeJavaScript(
    `window.scrollBy({ top: ${dy}, behavior: 'smooth' })`
  ).catch(console.error)
}

function handleNavigate(url) {
  webview.src = normalizeUrl(url)
  addressBar.value = webview.src
}

// ── Screenshot responder ──────────────────────────────────────────────────────

window.whaip.onAgentMessage(async data => {
  if (data.type === 'screenshot:request') {
    const b64 = await window.whaip.captureScreenshot()
    window.whaip.sendToAgent({ type: 'screenshot:response', data: b64 })
    return
  }
  if (data.type === 'action' && data.action) {
    executeAction(data)
  }
})

// ── Init ──────────────────────────────────────────────────────────────────────

;(async function init() {
  const cfg = await window.whaip.getConfig()
  const home = cfg?.browser?.home_url || 'https://www.google.com'
  webview.src = home
  addressBar.value = home
  btnBack.style.opacity    = '0.35'
  btnForward.style.opacity = '0.35'
})()
