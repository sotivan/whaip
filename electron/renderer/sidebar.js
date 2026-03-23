/**
 * WHAIP – AI sidebar controller
 */

const sidebar          = document.getElementById('sidebar')
const btnSidebarToggle = document.getElementById('btn-sidebar-toggle')
const btnSidebarClose  = document.getElementById('btn-sidebar-close')
const btnMicToggle     = document.getElementById('btn-mic-toggle')
const statusIndicator  = document.getElementById('status-indicator')
const statusLabel      = document.getElementById('status-label')
const transcriptFeed   = document.getElementById('transcript-feed')

// ── Sidebar visibility ───────────────────────────────────────────────────────

function openSidebar()  { sidebar.classList.remove('sidebar-hidden') }
function closeSidebar() { sidebar.classList.add('sidebar-hidden') }
function toggleSidebar() {
  sidebar.classList.contains('sidebar-hidden') ? openSidebar() : closeSidebar()
}

btnSidebarToggle.addEventListener('click', toggleSidebar)
btnSidebarClose.addEventListener('click', closeSidebar)

// ── Agent status ─────────────────────────────────────────────────────────────

const STATUS_MAP = {
  idle:      { cls: 'status-idle',      label: 'Idle' },
  listening: { cls: 'status-listening', label: 'Escuchando…' },
  thinking:  { cls: 'status-thinking',  label: 'Pensando…' },
  acting:    { cls: 'status-acting',    label: 'Actuando…' },
  error:     { cls: 'status-idle',      label: 'Error' },
}

function setAgentStatus(state) {
  const s = STATUS_MAP[state] || STATUS_MAP.idle
  statusIndicator.className = `status-indicator ${s.cls}`
  statusLabel.textContent   = s.label
}

// ── Transcript feed ───────────────────────────────────────────────────────────

function appendTranscript(role, text) {
  const entry = document.createElement('div')
  entry.className = `transcript-entry ${role}`
  entry.innerHTML = `
    <div class="label">${role === 'user' ? '🎤 Tú' : '🤖 WHAIP'}</div>
    <div>${escapeHtml(text)}</div>
  `
  transcriptFeed.appendChild(entry)
  transcriptFeed.scrollTop = transcriptFeed.scrollHeight

  // Keep only last 50 entries in DOM
  while (transcriptFeed.children.length > 50) {
    transcriptFeed.removeChild(transcriptFeed.firstChild)
  }
}

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
}

// ── Mic toggle ────────────────────────────────────────────────────────────────

let micActive = false
const micStatusText = document.getElementById('mic-status-text')

function setMicState(active) {
  micActive = active
  btnMicToggle.textContent      = active ? '⏹ Pausar' : '🎤 Activar'
  btnMicToggle.classList.toggle('mic-on', active)
  setAgentStatus(active ? 'listening' : 'idle')
  if (micStatusText) {
    micStatusText.textContent = active ? '🟢 Escuchando…' : 'Micrófono inactivo — pulsa Activar'
    micStatusText.style.color = active ? '#22c55e' : 'var(--color-muted)'
  }
  window.whaip.sendToAgent({ type: 'mic:toggle', active })
}

btnMicToggle.addEventListener('click', () => setMicState(!micActive))

// ── WS connection badge ───────────────────────────────────────────────────────

window.whaip.onAgentStatus(({ connected }) => {
  const badge = document.getElementById('agent-conn-badge')
  if (badge) {
    badge.textContent = connected ? '● Agente conectado' : '○ Agente desconectado'
    badge.style.color = connected ? '#22c55e' : '#71717a'
  }
})

// ── Onboarding UI ─────────────────────────────────────────────────────────────

function buildOnboardingForm(questions) {
  const wrap = document.createElement('div')
  wrap.id = 'onboarding-form'
  wrap.innerHTML = `
    <div class="onboarding-header">
      <div class="onboarding-logo">👋</div>
      <h2>Hola, soy WHAIP</h2>
      <p>Cuéntame un poco sobre ti para ayudarte mejor.</p>
    </div>
    <form id="onboarding-fields">
      ${questions.map(q => `
        <div class="onb-field">
          <label for="onb-${q.key}">${q.label}</label>
          ${q.options ? `
            <div class="onb-chips" data-key="${q.key}">
              ${q.options.map(o => `<button type="button" class="chip" data-value="${o}">${o}</button>`).join('')}
              <input type="text" id="onb-${q.key}" name="${q.key}" placeholder="${q.hint}" />
            </div>
          ` : `
            <input type="text" id="onb-${q.key}" name="${q.key}" placeholder="${q.hint}" />
          `}
        </div>
      `).join('')}
      <button type="submit" class="onb-submit">Guardar y empezar →</button>
    </form>
  `

  // Chip click → toggle + append to input
  wrap.querySelectorAll('.onb-chips').forEach(chips => {
    chips.querySelectorAll('.chip').forEach(chip => {
      chip.addEventListener('click', () => {
        chip.classList.toggle('selected')
        const key = chips.dataset.key
        const input = chips.querySelector('input')
        const selected = [...chips.querySelectorAll('.chip.selected')].map(c => c.dataset.value)
        input.value = selected.join(', ')
      })
    })
  })

  wrap.querySelector('form').addEventListener('submit', e => {
    e.preventDefault()
    const answers = {}
    wrap.querySelectorAll('input[name]').forEach(inp => {
      if (inp.value.trim()) answers[inp.name] = inp.value.trim()
    })
    window.whaip.sendToAgent({ type: 'onboarding:answers', answers })
    wrap.remove()
  })

  return wrap
}

function showVoiceQuestion(text) {
  let box = document.getElementById('onboarding-voice-question')
  if (!box) {
    box = document.createElement('div')
    box.id = 'onboarding-voice-question'
    transcriptFeed.prepend(box)
  }
  box.innerHTML = `<div class="onb-voice-q">🎙 ${escapeHtml(text)}</div>`
}

// ── Incoming WHP messages ─────────────────────────────────────────────────────

window.whaip.onAgentMessage(data => {
  switch (data.type) {

    case 'status':
      setAgentStatus(data.state)
      break

    case 'transcript':
      appendTranscript(data.role, data.text)
      openSidebar()
      break

    case 'action':
      if (data.reason) appendTranscript('agent', data.reason)
      break

    case 'onboarding:start':
      openSidebar()
      break

    case 'onboarding:form': {
      openSidebar()
      const existing = document.getElementById('onboarding-form')
      if (existing) existing.remove()
      const form = buildOnboardingForm(data.questions || [])
      transcriptFeed.prepend(form)
      break
    }

    case 'onboarding:question':
      openSidebar()
      showVoiceQuestion(data.text)
      break

    case 'onboarding:tips': {
      const box = document.createElement('div')
      box.className = 'transcript-entry agent onb-tips'
      box.innerHTML = `
        <div class="label">💡 Para sacar más partido</div>
        <ul>${(data.tips || []).map(t => `<li>${escapeHtml(t)}</li>`).join('')}</ul>
      `
      transcriptFeed.appendChild(box)
      transcriptFeed.scrollTop = transcriptFeed.scrollHeight
      const vq = document.getElementById('onboarding-voice-question')
      if (vq) vq.remove()
      break
    }

    case 'onboarding:done': {
      const name = data.name ? `, ${data.name}` : ''
      appendTranscript('agent', `¡Perfil guardado${name}! Pulsa 🎤 Activar cuando quieras empezar.`)
      break
    }
  }
})

// ── Bookmark button ───────────────────────────────────────────────────────────

const btnBookmark = document.getElementById('btn-bookmark')
if (btnBookmark) {
    btnBookmark.addEventListener('click', () => {
        window.whaip.sendToAgent({ type: 'bookmark:get_current' })
    })
}

// Cmd+D / Ctrl+D to bookmark
document.addEventListener('keydown', e => {
    if ((e.metaKey || e.ctrlKey) && e.key === 'd') {
        e.preventDefault()
        window.whaip.sendToAgent({ type: 'bookmark:get_current' })
    }
})

// ── Init ──────────────────────────────────────────────────────────────────────

;(function init() {
  closeSidebar()          // sidebar closed until there's activity
  setAgentStatus('idle')
})()
