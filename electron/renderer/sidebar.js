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

// ── Incoming WHP messages ─────────────────────────────────────────────────────

window.whaip.onAgentMessage(data => {
  switch (data.type) {
    case 'status':
      setAgentStatus(data.state)
      break
    case 'transcript':
      appendTranscript(data.role, data.text)
      openSidebar()   // auto-open when agent starts talking
      break
    case 'action':
      if (data.reason) appendTranscript('agent', data.reason)
      break
  }
})

// ── Init ──────────────────────────────────────────────────────────────────────

;(function init() {
  closeSidebar()          // sidebar closed until there's activity
  setAgentStatus('idle')
})()
