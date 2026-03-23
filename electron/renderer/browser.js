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
  window.whaip.sendToAgent({ type: 'page:context', url: e.url, title: document.title })
  startAutoClean(e.url)
})

webview.addEventListener('page-title-updated', e => {
  window.whaip.sendToAgent({ type: 'page:context', url: webview.src, title: e.title })
})

webview.addEventListener('did-navigate-in-page', e => {
  addressBar.value = e.url
})

webview.addEventListener('page-title-updated', e => {
  document.title = `${e.title} — WHAIP`
  window.whaip.sendToAgent({ type: 'page:context', url: webview.src, title: e.title })
})

webview.addEventListener('did-start-loading', () => {
  btnReload.textContent = '✕'
  btnReload.title = 'Stop'
  btnReload.onclick = () => webview.stop()
})

// ── Auto-dismiss: cookies + ads (runs on every page load, no Claude needed) ──────

const COOKIE_JS = `
(function() {
  const textRe = /aceptar|accept|allow all|alle akzept|i agree|acepto|got it|entendido|permitir|concordo|agree|consent|alle cookies/i;

  // 1. Main document — click by text
  const byText = [...document.querySelectorAll('button,[role="button"],a')].find(b => textRe.test(b.innerText));
  if (byText) { byText.click(); return 'clicked main: ' + byText.innerText.slice(0,30); }

  // 2. Search inside ALL iframes (OneTrust, CookieBot, etc. load in iframes)
  for (const fr of document.querySelectorAll('iframe')) {
    try {
      const d = fr.contentDocument || fr.contentWindow.document;
      if (!d) continue;
      const btn = [...d.querySelectorAll('button,[role="button"],a')].find(b => textRe.test(b.innerText));
      if (btn) { btn.click(); return 'clicked iframe: ' + btn.innerText.slice(0,30); }
    } catch(e) {}
  }

  // 3. Click by data-* attributes
  const byAttr = document.querySelector('[data-testid*="accept"],[id*="accept"],[id*="cookie-accept"],[id*="onetrust-accept"]');
  if (byAttr) { byAttr.click(); return 'clicked attr: ' + byAttr.id; }

  // 4. Nuclear: hide fixed overlays blocking the page
  let removed = 0;
  document.querySelectorAll('*').forEach(el => {
    try {
      const s = window.getComputedStyle(el);
      if ((s.position==='fixed'||s.position==='sticky') && parseInt(s.zIndex)>999 && el.offsetHeight>80) {
        el.style.display = 'none'; removed++;
      }
    } catch(e) {}
  });
  document.body.style.overflow = '';
  if (removed) return 'hid ' + removed + ' overlay(s)';
  return 'no banner';
})()
`

const YOUTUBE_AD_JS = `
(function() {
  // Skip button
  const skip = document.querySelector('.ytp-skip-ad-button,.ytp-ad-skip-button-slot button,[class*="skip-ad"]');
  if (skip) { skip.click(); return 'skipped ad'; }
  // Close overlay ad
  const close = document.querySelector('.ytp-ad-overlay-close-button');
  if (close) { close.click(); return 'closed overlay'; }
  return null;
})()
`

let _adInterval = null

function runCookieDismiss() {
  // 1. Try in main frame (fast)
  webview.executeJavaScript(COOKIE_JS).catch(() => {})
  // 2. Try in ALL frames via main process (catches cross-origin iframes like OneTrust, CookieBot)
  window.whaip.dismissCookies().catch(() => {})
}

function startAutoClean(url) {
  // Cookies: fire at 1s, 3s and 6s after load (some CMPs load late)
  setTimeout(runCookieDismiss, 1000)
  setTimeout(runCookieDismiss, 3000)
  setTimeout(runCookieDismiss, 6000)

  // YouTube ads: poll every 2s
  if (_adInterval) clearInterval(_adInterval)
  if (url && url.includes('youtube.com')) {
    _adInterval = setInterval(() => {
      webview.executeJavaScript(YOUTUBE_AD_JS).catch(() => {})
    }, 2000)
  } else {
    _adInterval = null
  }
}

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

// ── AI cursor ─────────────────────────────────────────────────────────────────

const aiCursor      = document.getElementById('ai-cursor')
const aiCursorPulse = document.getElementById('ai-cursor-pulse')

function showAICursor(x, y) {
  // x, y are webview-relative coords — offset by webview's position in layout
  const rect = webview.getBoundingClientRect()
  const absX  = rect.left + x
  const absY  = rect.top  + y
  aiCursor.style.display = 'block'
  aiCursor.style.left    = absX + 'px'
  aiCursor.style.top     = absY + 'px'
}

function pulseAICursor() {
  if (!aiCursorPulse) return
  aiCursorPulse.style.transition = 'none'
  aiCursorPulse.style.opacity    = '0.8'
  aiCursorPulse.style.r          = '6'
  requestAnimationFrame(() => {
    requestAnimationFrame(() => {
      aiCursorPulse.style.transition = 'all 0.5s ease-out'
      aiCursorPulse.style.opacity    = '0'
    })
  })
}

function hideAICursor() {
  setTimeout(() => { aiCursor.style.display = 'none' }, 600)
}

// ── Click handler — real Chromium input events + AI cursor ────────────────────

function handleClick(x, y, buttonText) {
  // Validate coords — sendInputEvent crashes with non-integers
  x = Math.round(Number(x) || 0)
  y = Math.round(Number(y) || 0)

  // Step 1: move cursor visually
  showAICursor(x, y)

  // Step 2: wait for CSS transition (250ms), then click
  setTimeout(() => {
    pulseAICursor()

    // Try JS text-match first (most reliable for known button labels)
    const textScript = buttonText ? `
      (function() {
        const text = ${JSON.stringify(buttonText)}.toLowerCase();
        const el = [...document.querySelectorAll('button,[role="button"],a,input[type="submit"]')]
          .find(e => e.textContent.trim().toLowerCase().includes(text));
        if (el) {
          const r = el.getBoundingClientRect();
          el.click();
          return JSON.stringify({found:true, x: Math.round(r.left+r.width/2), y: Math.round(r.top+r.height/2)});
        }
        return JSON.stringify({found:false});
      })()
    ` : 'JSON.stringify({found:false})'

    webview.executeJavaScript(textScript).then(raw => {
      const res = JSON.parse(raw)
      if (res.found) {
        // Update cursor to actual element position
        if (res.x && res.y) showAICursor(res.x, res.y)
        hideAICursor()
        return
      }

      // Step 3: real Chromium mouse events at coordinates (bypasses JS sandbox — works on overlays)
      webview.sendInputEvent({ type: 'mouseMoved', x, y })
      setTimeout(() => {
        webview.sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 })
        webview.sendInputEvent({ type: 'mouseUp',   x, y, button: 'left', clickCount: 1 })
        hideAICursor()
      }, 50)

    }).catch(() => {
      // Fallback: real events anyway
      webview.sendInputEvent({ type: 'mouseMoved', x, y })
      webview.sendInputEvent({ type: 'mouseDown',  x, y, button: 'left', clickCount: 1 })
      webview.sendInputEvent({ type: 'mouseUp',    x, y, button: 'left', clickCount: 1 })
      hideAICursor()
    })
  }, 260)
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
