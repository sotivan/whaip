/**
 * WHAIP – Onboarding screen logic
 */

let currentStep = 0
const TOTAL_STEPS = 4

// ── Navigation ─────────────────────────────────────────────────────────────

function goStep(n) {
  document.getElementById(`step-${currentStep}`).classList.remove('visible')
  currentStep = n
  document.getElementById(`step-${currentStep}`).classList.add('visible')
  updateProgress()
  if (n === 3) buildSummary()
}

function updateProgress() {
  for (let i = 0; i < TOTAL_STEPS; i++) {
    const dot = document.getElementById(`step-dot-${i}`)
    dot.className = 'progress-step'
    if (i < currentStep) dot.classList.add('done')
    if (i === currentStep) dot.classList.add('active')
  }
}

// ── Input helpers ───────────────────────────────────────────────────────────

function onFieldInput(el) {
  el.classList.toggle('filled', el.value.trim() !== '')
}

function val(id) {
  return document.getElementById(id)?.value?.trim() || ''
}

// ── Summary ─────────────────────────────────────────────────────────────────

const MODULES = [
  {
    label:    '🧠 Agente IA (Claude)',
    keys:     ['anthropic_api_key'],
    required: true,
  },
  {
    label: '🎤 Whisper STT',
    keys:  [],
    note:  'Siempre activo (modelo local)',
    alwaysOn: true,
  },
  {
    label: '🔊 Voz ElevenLabs',
    keys:  ['elevenlabs_api_key', 'elevenlabs_voice_id'],
  },
  {
    label: '☁️  Sync Supabase',
    keys:  ['supabase_url', 'supabase_key'],
  },
  {
    label: '📧 Google (Gmail / Drive)',
    keys:  ['google_client_id', 'google_client_secret'],
  },
]

function buildSummary() {
  const list = document.getElementById('summary-list')
  list.innerHTML = ''

  for (const mod of MODULES) {
    const on = mod.alwaysOn || mod.keys.every(k => val(k) !== '')
    const row = document.createElement('div')
    row.className = 'summary-row'
    row.innerHTML = `
      <span class="summary-label">${mod.label}</span>
      <span class="summary-status ${on ? 'status-on' : 'status-off'}">
        ${on ? '✓ Activo' : mod.required ? '⚠ Falta key' : '— Desactivado'}
      </span>
    `
    list.appendChild(row)
  }
}

// ── Launch ──────────────────────────────────────────────────────────────────

async function launch() {
  const config = {
    anthropic_api_key:    val('anthropic_api_key'),
    openai_api_key:       val('openai_api_key'),
    elevenlabs_api_key:   val('elevenlabs_api_key'),
    elevenlabs_voice_id:  val('elevenlabs_voice_id'),
    supabase_url:         val('supabase_url'),
    supabase_key:         val('supabase_key'),
    google_client_id:     val('google_client_id'),
    google_client_secret: val('google_client_secret'),
  }

  await window.whaip.saveConfig(config)
  window.whaip.onboardingDone()
}

// ── External links ──────────────────────────────────────────────────────────

function openExt(url) {
  window.whaip.openExternal(url)
}

// ── Pre-fill from existing config (if user re-opens setup) ─────────────────

async function prefill() {
  const cfg = await window.whaip.getConfig()
  const fields = [
    'anthropic_api_key', 'openai_api_key',
    'elevenlabs_api_key', 'elevenlabs_voice_id',
    'supabase_url', 'supabase_key',
    'google_client_id', 'google_client_secret',
  ]
  for (const f of fields) {
    const el = document.getElementById(f)
    if (el && cfg[f]) {
      el.value = cfg[f]
      el.classList.add('filled')
    }
  }
}

prefill()
