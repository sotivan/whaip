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
    case 'click':     return handleClick(cmd.x, cmd.y, cmd.text)
    case 'type':      return handleType(cmd.text)
    case 'scroll':    return handleScroll(cmd.direction)
    case 'navigate':  return handleNavigate(cmd.text)
    case 'js':        return handleJS(cmd.code, cmd._id)
    case 'wait':      return
    case 'done':      return window.dispatchEvent(new CustomEvent('whaip:done', { detail: cmd }))
    default: console.warn('[browser] unknown action:', cmd.action)
  }
}

function handleJS(code, actionId) {
  if (!code) return
  console.log('[whaip] executing JS:', code.slice(0, 200))

  const wrapped = `
    (function() {
      // ── Helpers available to Claude-generated code ──
      function setInput(el, value) {
        if (!el) return 'ERROR: el is null';
        const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
        if (setter) setter.set.call(el, value);
        else el.value = value;
        el.dispatchEvent(new Event('input',  { bubbles: true }));
        el.dispatchEvent(new Event('change', { bubbles: true }));
        return 'ok: set "' + value + '" on ' + (el.id || el.className || el.tagName);
      }
      function pressEnter(el) {
        if (!el) return 'ERROR: el is null';
        el.dispatchEvent(new KeyboardEvent('keydown',  { key:'Enter', keyCode:13, bubbles:true }));
        el.dispatchEvent(new KeyboardEvent('keypress', { key:'Enter', keyCode:13, bubbles:true }));
        el.dispatchEvent(new KeyboardEvent('keyup',    { key:'Enter', keyCode:13, bubbles:true }));
        return 'ok: enter pressed';
      }
      function clickEl(selector) {
        const el = typeof selector === 'string' ? document.querySelector(selector) : selector;
        if (!el) {
          // Return diagnostic: what buttons ARE in the page
          const btns = [...document.querySelectorAll('button,[role="button"]')]
            .map(b => (b.className || b.id || b.innerText || '').slice(0,40))
            .filter(Boolean).slice(0,8).join(' | ');
          return 'NOT FOUND: ' + (typeof selector === 'string' ? selector : '?') + ' — visible buttons: ' + btns;
        }
        el.click();
        return 'clicked: ' + (el.className || el.id || el.innerText || el.tagName).slice(0,60);
      }
      // ── Claude code ──
      return (function(){ ${code} })();
    })()
  `
  webview.executeJavaScript(wrapped)
    .then(result => {
      window.whaip.sendToAgent({
        type: 'action:result',
        action_id: actionId,
        ok: true,
        result: String(result ?? 'ok'),
        url: location.href,
      })
    })
    .catch(err => {
      console.error('[whaip] JS error:', err.message)
      window.whaip.sendToAgent({
        type: 'action:result',
        action_id: actionId,
        ok: false,
        error: err.message,
        url: location.href,
      })
    })
}

function handleClick(x, y, buttonText) {
  // If a button label is known, try to find it by text first (more reliable than coords)
  const textScript = buttonText ? `
    (function() {
      const text = ${JSON.stringify(buttonText)}.toLowerCase();
      const candidates = [...document.querySelectorAll('button, [role="button"], a, input[type="submit"]')];
      const el = candidates.find(e => e.textContent.trim().toLowerCase().includes(text));
      if (el) { el.click(); return true; }
      return false;
    })()
  ` : 'false'

  webview.executeJavaScript(textScript).then(found => {
    if (found) return
    // Fallback to coordinates
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
  }).catch(console.error)
}

function handleType(text) {
  if (!text) return
  webview.executeJavaScript(`
    (function() {
      const el = document.activeElement;
      if (!el || el === document.body) return;
      // Focus first
      el.focus();
      // Try native setter (works for React)
      const setter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value')
                  || Object.getOwnPropertyDescriptor(window.HTMLTextAreaElement.prototype, 'value');
      if (setter) setter.set.call(el, ${JSON.stringify(text)});
      else el.value = ${JSON.stringify(text)};
      el.dispatchEvent(new Event('input',  { bubbles: true }));
      el.dispatchEvent(new Event('change', { bubbles: true }));
      // Also try execCommand for extra compatibility
      document.execCommand('selectAll', false, null);
      document.execCommand('insertText', false, ${JSON.stringify(text)});
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
