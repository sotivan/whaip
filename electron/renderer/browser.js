/**
 * WHAIP – Browser pane controller
 */

// webview is now managed by tabs.js — always get the active one
const webview    = document.getElementById('webview')  // initial reference, tabs.js takes over
const addressBar = document.getElementById('address-bar')
const btnBack    = document.getElementById('btn-back')
const btnForward = document.getElementById('btn-forward')
const btnReload  = document.getElementById('btn-reload')

// Delegate to active tab's webview
function wv() { return window.getActiveWebview?.() || webview }

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
    wv().src = normalizeUrl(addressBar.value)
    addressBar.blur()
  }
})

// ── Nav buttons ──────────────────────────────────────────────────────────────

btnBack.addEventListener('click',    () => wv().canGoBack?.()    && wv().goBack())
btnForward.addEventListener('click', () => wv().canGoForward?.() && wv().goForward())
btnReload.addEventListener('click',  () => wv().reload())

// ── Webview events — navigation, title, loading are handled per-tab in tabs.js ─

// did-navigate fires startAutoClean for cookie/ad dismissal on the first tab
webview.addEventListener('did-navigate', e => {
  startAutoClean(e.url)
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
  wv().executeJavaScript(COOKIE_JS).catch(() => {})
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
      wv().executeJavaScript(YOUTUBE_AD_JS).catch(() => {})
    }, 2000)
  } else {
    _adInterval = null
  }

  // Detect login forms and offer autofill if we have credentials
  setTimeout(() => {
    wv().executeJavaScript(`
        const hasPwd = !!document.querySelector('input[type="password"]');
        const hasUser = !!document.querySelector('input[type="email"],input[type="text"][name*="user" i],input[name*="email" i]');
        if (hasPwd && hasUser) {
            const m = location.href.match(/https?:\\/\\/([^/?#]+)/);
            const domain = m ? m[1].replace(/^www\\./, '') : '';
            domain;
        } else { ''; }
    `).then(domain => {
        if (domain) {
            window.whaip.sendToAgent({ type: 'autofill:request', domain })
        }
    }).catch(() => {})
  }, 1500)
}

// did-stop-loading per-tab is handled in tabs.js

// ── WHP action executor ───────────────────────────────────────────────────────

async function executeAction(cmd) {
  switch (cmd.action) {
    case 'click':     return handleClick(cmd.x, cmd.y, cmd.text)
    case 'type':      return handleType(cmd.text)
    case 'scroll':    return handleScroll(cmd.direction)
    case 'navigate':  return handleNavigate(cmd.text, cmd._id)
    case 'js':        return handleJS(cmd.code, cmd._id)
    case 'script':    return executeScript(cmd.steps || [], cmd._id)
    case 'wait':      return
    case 'done':      return window.dispatchEvent(new CustomEvent('whaip:done', { detail: cmd }))
    default: console.warn('[browser] unknown action:', cmd.action)
  }
}

// ── JS helpers injected into every Claude-generated code block ───────────────

const AGENT_HELPERS = `
  function setInput(el, value) {
    if (!el) return 'ERROR: el is null';
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (s) s.set.call(el, value); else el.value = value;
    el.dispatchEvent(new Event('input',  { bubbles:true }));
    el.dispatchEvent(new Event('change', { bubbles:true }));
    return 'set "' + value + '" on ' + (el.id || el.className.slice(0,30) || el.tagName);
  }
  function pressEnter(el) {
    if (!el) return 'ERROR: el is null';
    ['keydown','keypress','keyup'].forEach(t =>
      el.dispatchEvent(new KeyboardEvent(t, { key:'Enter', keyCode:13, bubbles:true })));
    return 'enter pressed';
  }
  async function typeAndSelect(el, value, waitMs) {
    if (!el) return 'ERROR: el is null';
    el.focus(); el.click();
    const s = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, 'value');
    if (s) s.set.call(el, value); else el.value = value;
    ['input','change'].forEach(t => el.dispatchEvent(new Event(t, {bubbles:true})));
    el.dispatchEvent(new KeyboardEvent('keydown', {key:'a', bubbles:true}));
    await new Promise(r => setTimeout(r, waitMs || 900));
    const SUGG = '[class*="suggest"],[class*="autocomplete"],[class*="Suggest"],[class*="Autocomplete"],[role="option"],[role="listbox"] li,[class*="dropdown"] li,[class*="result-item"],[class*="ResultItem"],[class*="address-item"],[class*="AddressItem"],[class*="prediction"],[class*="Prediction"]';
    const items = [...document.querySelectorAll(SUGG)].filter(e => e.offsetParent !== null && e.textContent.trim().length > 3);
    if (items[0]) { items[0].click(); return 'typed+selected: ' + items[0].textContent.trim().slice(0,60); }
    return 'typed only — no suggestion found for: "' + value + '"';
  }
  function clickEl(sel) {
    let el;
    if (typeof sel === 'string') {
      try { el = document.querySelector(sel); }
      catch(e) {
        // Invalid CSS selector (e.g. React IDs with / = + : chars) — try getElementById
        const m = sel.match(/^#(.+)$/);
        if (m) el = document.getElementById(m[1]);
      }
    } else { el = sel; }
    if (!el) {
      const avail = [...document.querySelectorAll('button,[role="button"],a,pie-button')]
        .map(b => (b.id||b.className||b.innerText||b.tagName||'').slice(0,30)).filter(Boolean).slice(0,8).join(' | ');
      return 'NOT FOUND: ' + (typeof sel==='string'?sel:'?') + ' — available: ' + avail;
    }
    el.click();
    return 'clicked: ' + (el.id||el.innerText||el.className||el.tagName).slice(0,50);
  }
  function clickWC(tagOrText) {
    const byTag  = tagOrText.includes('-') ? [...document.querySelectorAll(tagOrText)] : [];
    const byText = [...document.querySelectorAll('*')].filter(e =>
      e.tagName.includes('-') && e.textContent.toLowerCase().includes(tagOrText.toLowerCase()));
    const el = byTag[0] || byText[0];
    if (el) { el.click(); return 'clicked WC: ' + el.tagName + ' ' + el.textContent.trim().slice(0,40); }
    const avail = [...document.querySelectorAll('*')].filter(e=>e.tagName.includes('-'))
      .map(e=>e.tagName+'['+e.textContent.trim().slice(0,20)+']').slice(0,8).join(' | ');
    return 'WC NOT FOUND: ' + tagOrText + ' — available: ' + avail;
  }
`

function buildJS(code) {
  return `(async function() { ${AGENT_HELPERS} return (async function(){ ${code} })(); })()`
}

function handleJS(code, actionId) {
  if (!code) return
  wv().executeJavaScript(buildJS(code))
    .then(result => window.whaip.sendToAgent({
      type: 'action:result', action_id: actionId, ok: true,
      result: String(result ?? 'ok'), url: wv().getURL?.() || wv().src,
    }))
    .catch(err => window.whaip.sendToAgent({
      type: 'action:result', action_id: actionId, ok: false,
      error: err.message, url: wv().getURL?.() || wv().src,
    }))
}

// ── Script executor: runs a full plan without API round-trips ─────────────────

function navigateAndWait(url, timeoutMs) {
  return new Promise((resolve, reject) => {
    _pendingNavId = null   // don't trigger the global listener
    const activeWv = wv()
    const t = setTimeout(() => {
      activeWv.removeEventListener('did-finish-load', onLoad)
      activeWv.removeEventListener('did-fail-load',   onFail)
      reject(new Error('navigate timeout'))
    }, timeoutMs || 12000)
    function onLoad() {
      clearTimeout(t)
      activeWv.removeEventListener('did-finish-load', onLoad)
      activeWv.removeEventListener('did-fail-load',   onFail)
      addressBar.value = activeWv.getURL?.() || activeWv.src
      window.whaip.sendToAgent({ type: 'page:context', url: activeWv.getURL?.() || activeWv.src, title: '' })
      resolve()
    }
    function onFail(e) {
      if (e.errorCode === -3) return  // SPA redirect; did-finish-load follows
      clearTimeout(t)
      activeWv.removeEventListener('did-finish-load', onLoad)
      activeWv.removeEventListener('did-fail-load',   onFail)
      reject(new Error(e.errorDescription + ' (' + e.errorCode + ')'))
    }
    activeWv.addEventListener('did-finish-load', onLoad)
    activeWv.addEventListener('did-fail-load',   onFail)
    activeWv.src = normalizeUrl(url)
    addressBar.value = activeWv.src
  })
}

async function waitForContent(selector, timeoutMs) {
  const deadline = Date.now() + (timeoutMs || 5000)
  const js = `(function(){
    try {
      const el = document.querySelector(${JSON.stringify(selector)});
      if (el && el.offsetParent !== null) return true;
      return [...document.querySelectorAll('*')].some(e =>
        e.offsetParent !== null &&
        e.textContent.trim().toLowerCase().includes(${JSON.stringify(selector.toLowerCase())}));
    } catch(e) { return false; }
  })()`
  while (Date.now() < deadline) {
    const found = await wv().executeJavaScript(js).catch(() => false)
    if (found) return true
    await new Promise(r => setTimeout(r, 300))
  }
  return false
}

async function executeScript(steps, scriptId) {
  const url = () => wv().getURL?.() || wv().src
  const fail = (i, desc, error) => window.whaip.sendToAgent({
    type: 'script:result', script_id: scriptId, ok: false,
    failed_step: i, failed_desc: desc, error, url: url(),
  })

  for (let i = 0; i < steps.length; i++) {
    const step = steps[i]
    const desc = step.desc || step.type
    console.log(`[script ${scriptId}] step ${i+1}/${steps.length}: ${desc}`)

    try {
      if (step.type === 'js') {
        const r = String(await wv().executeJavaScript(buildJS(step.code)) ?? '')
        console.log(`[script] →`, r.slice(0, 120))
        if (r.startsWith('ERROR:') || r.startsWith('NOT FOUND:') || r.startsWith('WC NOT FOUND:'))
          return fail(i, desc, r)

      } else if (step.type === 'navigate') {
        await navigateAndWait(step.url)
        setTimeout(runCookieDismiss, 800)
        setTimeout(runCookieDismiss, 2500)
        await new Promise(r => setTimeout(r, 400))  // brief settle

      } else if (step.type === 'wait_for') {
        const found = await waitForContent(step.selector, step.timeout || 5000)
        if (!found) return fail(i, desc, 'timeout waiting for: ' + step.selector)

      } else if (step.type === 'wait_ms') {
        await new Promise(r => setTimeout(r, step.ms || 500))

      } else if (step.type === 'speak') {
        window.whaip.sendToAgent({ type: 'script:speak', text: step.text })
        await new Promise(r => setTimeout(r, 200))
      }

    } catch (e) {
      const msg = e?.message || (typeof e === 'object' ? JSON.stringify(e) : String(e)) || 'unknown error'
      return fail(i, desc, msg)
    }
  }

  window.whaip.sendToAgent({
    type: 'script:result', script_id: scriptId, ok: true,
    result: `completed ${steps.length} steps`, url: url(),
  })
}

// ── AI cursor ─────────────────────────────────────────────────────────────────

const aiCursor      = document.getElementById('ai-cursor')
const aiCursorPulse = document.getElementById('ai-cursor-pulse')

function showAICursor(x, y) {
  // x, y are webview-relative coords — offset by webview's position in layout
  const rect = wv().getBoundingClientRect()
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

    wv().executeJavaScript(textScript).then(raw => {
      const res = JSON.parse(raw)
      if (res.found) {
        // Update cursor to actual element position
        if (res.x && res.y) showAICursor(res.x, res.y)
        hideAICursor()
        return
      }

      // Step 3: real Chromium mouse events at coordinates (bypasses JS sandbox — works on overlays)
      wv().sendInputEvent({ type: 'mouseMoved', x, y })
      setTimeout(() => {
        wv().sendInputEvent({ type: 'mouseDown', x, y, button: 'left', clickCount: 1 })
        wv().sendInputEvent({ type: 'mouseUp',   x, y, button: 'left', clickCount: 1 })
        hideAICursor()
      }, 50)

    }).catch(() => {
      // Fallback: real events anyway
      wv().sendInputEvent({ type: 'mouseMoved', x, y })
      wv().sendInputEvent({ type: 'mouseDown',  x, y, button: 'left', clickCount: 1 })
      wv().sendInputEvent({ type: 'mouseUp',    x, y, button: 'left', clickCount: 1 })
      hideAICursor()
    })
  }, 260)
}

function handleType(text) {
  if (!text) return
  wv().executeJavaScript(`
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
  wv().executeJavaScript(
    `window.scrollBy({ top: ${dy}, behavior: 'smooth' })`
  ).catch(console.error)
}

// Track the action_id of the in-flight navigate so we can report success/failure
let _pendingNavId = null

function handleNavigate(url, actionId) {
  _pendingNavId = actionId || null
  wv().src = normalizeUrl(url)
  addressBar.value = wv().src
}

// Report navigate result when page finishes loading or fails
webview.addEventListener('did-finish-load', () => {
  if (_pendingNavId) {
    const actualUrl = webview.getURL ? webview.getURL() : webview.src
    window.whaip.sendToAgent({
      type:      'action:result',
      action_id: _pendingNavId,
      ok:        true,
      result:    'página cargada',
      url:       actualUrl,
    })
    _pendingNavId = null
  }
})

webview.addEventListener('did-fail-load', e => {
  if (_pendingNavId && e.errorCode !== -3 /* ERR_ABORTED can be a redirect, ignore */) {
    window.whaip.sendToAgent({
      type:      'action:result',
      action_id: _pendingNavId,
      ok:        false,
      error:     `${e.errorDescription} (${e.errorCode}) — ${e.validatedURL}`,
      url:       webview.getURL ? webview.getURL() : webview.src,
    })
    _pendingNavId = null
  }
  // ERR_ABORTED (-3) usually means a redirect mid-load; did-finish-load fires after
})

// ── Screenshot responder ──────────────────────────────────────────────────────

// ── DOM snapshot extractor ────────────────────────────────────────────────────
// Returns structured list of all visible interactive elements so Claude can
// write precise CSS selectors instead of guessing pixel coordinates.

const DOM_EXTRACTOR_JS = `
(function() {
  function vis(el) {
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.top < window.innerHeight && r.bottom > 0
      && window.getComputedStyle(el).visibility !== 'hidden'
      && window.getComputedStyle(el).display !== 'none';
  }
  const out = { url: location.href, title: document.title, readyState: document.readyState, buttons: [], inputs: [], links: [], text: '' };

  // Include web components (custom elements with '-' in tag name)
  document.querySelectorAll('button,[role="button"],[type="submit"],[type="button"],[role="tab"],[role="menuitem"],[role="option"],pie-button,pie-icon-button,pie-radio,[class*="radio"],[class*="Radio"]').forEach(el => {
    if (!vis(el)) return;
    const r = el.getBoundingClientRect();
    out.buttons.push({
      text: (el.innerText || el.value || el.title || el.getAttribute('aria-label') || '').trim().slice(0, 60),
      cls:  el.className.toString().trim().slice(0, 80),
      id:   el.id || '',
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top  + r.height / 2),
    });
  });

  document.querySelectorAll('input:not([type="hidden"]),textarea,select').forEach(el => {
    if (!vis(el)) return;
    const r = el.getBoundingClientRect();
    out.inputs.push({
      type:        el.type || el.tagName.toLowerCase(),
      placeholder: el.placeholder || '',
      name:        el.name  || '',
      id:          el.id    || '',
      cls:         el.className.toString().trim().slice(0, 60),
      value:       (el.value || '').slice(0, 40),
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top  + r.height / 2),
    });
  });

  const seenLinks = new Set();
  document.querySelectorAll('a[href]').forEach(el => {
    if (!vis(el) || !el.innerText.trim()) return;
    const key = el.href.slice(0, 80) + '|' + el.innerText.trim().slice(0, 30);
    if (seenLinks.has(key)) return;
    seenLinks.add(key);
    const r = el.getBoundingClientRect();
    out.links.push({
      text: el.innerText.trim().slice(0, 60),
      href: el.href.slice(0, 100),
      cls:  el.className.toString().trim().slice(0, 60),
      id:   el.id || '',
      x: Math.round(r.left + r.width / 2),
      y: Math.round(r.top  + r.height / 2),
    });
  });

  out.text = [...document.querySelectorAll('h1,h2,h3,[role="heading"],label')]
    .filter(vis).map(e => e.innerText.trim()).filter(Boolean).slice(0, 15).join(' | ').slice(0, 400);

  // Web components (custom elements — PIE-RADIO, etc.)
  const wcEls = [...document.querySelectorAll('*')].filter(e =>
    e.tagName && e.tagName.includes('-') && vis(e) && e.textContent.trim()
  );
  if (wcEls.length) {
    out.webcomponents = wcEls.slice(0, 20).map(e => ({
      tag:  e.tagName.toLowerCase(),
      text: e.textContent.trim().slice(0, 50),
      cls:  e.className?.toString().trim().slice(0, 60) || '',
      id:   e.id || '',
    }));
  }

  out.buttons = out.buttons.slice(0, 35);
  out.inputs  = out.inputs.slice(0, 15);
  out.links   = out.links.slice(0, 30);
  return JSON.stringify(out);
})()`

window.whaip.onAgentMessage(async data => {
  if (data.type === 'screenshot:request') {
    const b64 = await window.whaip.captureScreenshot()
    window.whaip.sendToAgent({ type: 'screenshot:response', data: b64 })
    return
  }
  if (data.type === 'geo:request') {
    wv().executeJavaScript(`
      new Promise(resolve => {
        if (!navigator.geolocation) { resolve(null); return; }
        navigator.geolocation.getCurrentPosition(
          p => resolve({ lat: p.coords.latitude, lng: p.coords.longitude, accuracy: p.coords.accuracy }),
          () => resolve(null),
          { timeout: 6000, maximumAge: 60000 }
        );
      })
    `).then(geo => {
      window.whaip.sendToAgent({ type: 'geo:response', ...(geo || { error: 'unavailable' }) })
    }).catch(() => {
      window.whaip.sendToAgent({ type: 'geo:response', error: 'unavailable' })
    })
    return
  }
  if (data.type === 'dom:request') {
    try {
      const raw = await wv().executeJavaScript(DOM_EXTRACTOR_JS)
      window.whaip.sendToAgent({ type: 'dom:response', data: raw })
    } catch (e) {
      window.whaip.sendToAgent({ type: 'dom:response', data: null })
    }
    return
  }
  if (data.type === 'bookmark:get_current') {
    const pageUrl = wv().getURL?.() || wv().src
    const m = pageUrl.match(/https?:\/\/([^/?#]+)/)
    const domain = m ? m[1].replace(/^www\./, '') : ''
    window.whaip.sendToAgent({
        type:    'bookmark:save',
        url:     pageUrl,
        title:   wv().getTitle?.() || '',
        tags:    '',
        favicon: domain ? `https://www.google.com/s2/favicons?domain=${domain}&sz=16` : '',
    })
    return
  }
  if (data.type === 'password:get_domain') {
    // Get domain and ask user for credentials via a small inline form
    const url = wv().getURL?.() || wv().src
    const m = url.match(/https?:\/\/([^/?#]+)/)
    const domain = m ? m[1].replace(/^www\./, '') : ''
    if (domain) {
        showPasswordSavePrompt(domain)
    }
    return
  }
  if (data.type === 'autofill:fill') {
    // Fill login form with credentials received from agent
    wv().executeJavaScript(buildJS(`
        const u = document.querySelector('input[type="email"],input[type="text"][name*="user" i],input[name*="email" i],input[id*="user" i],input[id*="email" i]');
        const p = document.querySelector('input[type="password"]');
        if(u) setInput(u, ${JSON.stringify(data.username)});
        if(p) setInput(p, ${JSON.stringify(data.password)});
        return (u||p) ? 'autofilled' : 'fields not found';
    `)).catch(() => {})
    return
  }
  if (data.type === 'action' && data.action) {
    executeAction(data)
  }
})

// ── Password save prompt ──────────────────────────────────────────────────────

function showPasswordSavePrompt(domain) {
    const existing = document.getElementById('whaip-pwd-prompt')
    if (existing) existing.remove()
    const div = document.createElement('div')
    div.id = 'whaip-pwd-prompt'
    div.style.cssText = 'position:fixed;bottom:16px;right:16px;z-index:9999;background:#1a1a1e;border:1px solid #7c3aed;border-radius:8px;padding:16px;width:280px;color:#e4e4e7;font-size:13px;box-shadow:0 4px 20px rgba(0,0,0,0.5)'
    div.innerHTML = `
        <div style="font-weight:600;margin-bottom:8px">🔐 Guardar contraseña para <b>${domain}</b></div>
        <input id="whaip-pwd-user" placeholder="Usuario o email" style="width:100%;background:#0e0e10;border:1px solid #2e2e34;border-radius:6px;color:#e4e4e7;padding:6px 8px;margin-bottom:6px;font-size:12px;box-sizing:border-box">
        <input id="whaip-pwd-pass" type="password" placeholder="Contraseña" style="width:100%;background:#0e0e10;border:1px solid #2e2e34;border-radius:6px;color:#e4e4e7;padding:6px 8px;margin-bottom:10px;font-size:12px;box-sizing:border-box">
        <div style="display:flex;gap:6px">
            <button id="whaip-pwd-save" style="flex:1;background:#7c3aed;border:none;border-radius:6px;color:#fff;padding:7px;cursor:pointer;font-size:12px">Guardar</button>
            <button id="whaip-pwd-cancel" style="flex:1;background:transparent;border:1px solid #2e2e34;border-radius:6px;color:#71717a;padding:7px;cursor:pointer;font-size:12px">Cancelar</button>
        </div>
    `
    document.body.appendChild(div)
    div.querySelector('#whaip-pwd-save').onclick = () => {
        const username = div.querySelector('#whaip-pwd-user').value.trim()
        const password = div.querySelector('#whaip-pwd-pass').value
        if (username && password) {
            window.whaip.sendToAgent({ type: 'password:save', domain, username, password })
        }
        div.remove()
    }
    div.querySelector('#whaip-pwd-cancel').onclick = () => div.remove()
    div.querySelector('#whaip-pwd-user').focus()
}

// ── Init ──────────────────────────────────────────────────────────────────────

;(async function init() {
  const cfg = await window.whaip.getConfig()
  window._homeUrl = cfg?.browser?.home_url || 'https://www.google.com'
  // Pre-load home URL now (webview is hidden behind start screen via visibility:hidden).
  // This way Google is already loaded when the start screen dismisses — no black flash.
  const activeWv = wv()
  if (activeWv && (!activeWv.src || activeWv.src === 'about:blank')) {
    activeWv.src = window._homeUrl
  }
  addressBar.value = window._homeUrl
  btnBack.style.opacity    = '0.35'
  btnForward.style.opacity = '0.35'
})()

// Called by start-screen.js when the start screen is dismissed.
// Home is already pre-loaded in init(); only navigate if the webview is still blank.
window.loadHomeUrl = function() {
  const activeWv = wv()
  if (!activeWv) return
  const currentUrl = activeWv.getURL?.() || activeWv.src || ''
  if (!currentUrl || currentUrl === 'about:blank') {
    activeWv.src = window._homeUrl || 'https://www.google.com'
    addressBar.value = activeWv.src
  }
}
