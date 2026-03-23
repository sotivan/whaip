/**
 * WHAIP – Electron main process
 */

const { app, BrowserWindow, ipcMain, shell } = require('electron')
const path  = require('path')
const fs    = require('fs')
const { spawn } = require('child_process')
const WebSocket  = require('ws')

// ─── Config ────────────────────────────────────────────────────────────────

const CONFIG_PATH = path.join(__dirname, '..', 'whaip.config.yaml')

function loadConfig() {
  try {
    const YAML = require('yaml')
    const raw  = fs.readFileSync(CONFIG_PATH, 'utf8')
    return YAML.parse(raw) || {}
  } catch (e) {
    return {}
  }
}

function saveConfig(data) {
  try {
    const YAML   = require('yaml')
    const current = loadConfig()
    const merged  = deepMerge(current, data)
    fs.writeFileSync(CONFIG_PATH, YAML.stringify(merged), 'utf8')
    return true
  } catch (e) {
    console.error('[config] save error:', e.message)
    return false
  }
}

function isFirstRun(cfg) {
  return !cfg.anthropic_api_key || cfg.anthropic_api_key.trim() === ''
}

function deepMerge(target, source) {
  const out = Object.assign({}, target)
  for (const key of Object.keys(source)) {
    if (source[key] && typeof source[key] === 'object' && !Array.isArray(source[key])) {
      out[key] = deepMerge(target[key] || {}, source[key])
    } else {
      out[key] = source[key]
    }
  }
  return out
}

// ─── Python agent process ──────────────────────────────────────────────────

let agentProcess = null

function startAgentProcess() {
  const agentPath = path.join(__dirname, '..', 'agent', 'main.py')
  if (!fs.existsSync(agentPath)) {
    console.warn('[agent] main.py not found, skipping agent start')
    return
  }

  // Try venv python first, fall back to system python3
  const venvPython = path.join(__dirname, '..', '.venv', 'bin', 'python')
  const python     = fs.existsSync(venvPython) ? venvPython : 'python3'

  agentProcess = spawn(python, [agentPath], {
    cwd:   path.join(__dirname, '..', 'agent'),
    stdio: ['ignore', 'pipe', 'pipe'],
  })

  agentProcess.stdout.on('data', d => console.log('[agent]', d.toString().trim()))
  agentProcess.stderr.on('data', d => console.error('[agent]', d.toString().trim()))
  agentProcess.on('exit', code => console.log('[agent] exited with code', code))
  console.log('[agent] started (pid', agentProcess.pid, ')')
}

function stopAgentProcess() {
  if (agentProcess) {
    agentProcess.kill('SIGTERM')
    agentProcess = null
  }
}

// ─── WebSocket bridge (WHP) ────────────────────────────────────────────────

let wsClient        = null
let wsReconnectTimer = null
let mainWindow_ref  = null

function connectToAgent(config) {
  const host = config?.ws?.host || '127.0.0.1'
  const port = config?.ws?.port || 8765

  function connect() {
    try {
      wsClient = new WebSocket(`ws://${host}:${port}`)

      wsClient.on('open', () => {
        console.log('[ws] connected to agent')
        if (mainWindow_ref?.webContents) {
          mainWindow_ref.webContents.send('whp:status', { connected: true })
        }
      })

      wsClient.on('message', raw => {
        try {
          const data = JSON.parse(raw)
          if (mainWindow_ref?.webContents) {
            mainWindow_ref.webContents.send('whp:message', data)
          }
        } catch (e) {
          console.error('[ws] bad JSON from agent:', raw)
        }
      })

      wsClient.on('close', () => {
        console.log('[ws] disconnected, retry in 3s…')
        if (mainWindow_ref?.webContents) {
          mainWindow_ref.webContents.send('whp:status', { connected: false })
        }
        wsReconnectTimer = setTimeout(connect, 3000)
      })

      wsClient.on('error', err => {
        // silently ignore connection-refused (agent may not be running yet)
        if (err.code !== 'ECONNREFUSED') console.error('[ws]', err.message)
      })
    } catch (e) {
      wsReconnectTimer = setTimeout(connect, 3000)
    }
  }

  connect()
}

function sendToAgent(payload) {
  if (wsClient && wsClient.readyState === WebSocket.OPEN) {
    wsClient.send(JSON.stringify(payload))
  }
}

// ─── Screenshot ────────────────────────────────────────────────────────────

async function captureWebview(win) {
  try {
    const image = await win.webContents.capturePage()
    return image.toJPEG(80).toString('base64')
  } catch (e) {
    console.error('[screenshot]', e.message)
    return null
  }
}

// ─── Windows ───────────────────────────────────────────────────────────────

function createOnboardingWindow() {
  const win = new BrowserWindow({
    width:  680,
    height: 780,
    resizable: false,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
    },
  })
  win.loadFile(path.join(__dirname, 'renderer', 'onboarding.html'))
  return win
}

function createMainWindow(config) {
  const win = new BrowserWindow({
    width:  1400,
    height: 900,
    minWidth:  960,
    minHeight: 600,
    titleBarStyle: 'hiddenInset',
    webPreferences: {
      preload:          path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration:  false,
      webviewTag:       true,
    },
  })

  win.loadFile(path.join(__dirname, 'renderer', 'index.html'))
  mainWindow_ref = win

  win.on('closed', () => { mainWindow_ref = null })

  if (process.argv.includes('--dev')) {
    win.webContents.openDevTools({ mode: 'detach' })
  }

  return win
}

// ─── IPC handlers ──────────────────────────────────────────────────────────

function registerIpcHandlers() {
  // Config read
  ipcMain.handle('config:get', () => loadConfig())

  // Config save (from onboarding)
  ipcMain.handle('config:save', (_event, data) => saveConfig(data))

  // Onboarding complete → open main window
  ipcMain.on('onboarding:done', (event) => {
    const senderWin = BrowserWindow.fromWebContents(event.sender)
    const config    = loadConfig()
    const mainWin   = createMainWindow(config)
    connectToAgent(config)
    startAgentProcess()
    senderWin?.close()
  })

  // WHP outbound (renderer → agent)
  ipcMain.on('whp:send', (_event, payload) => sendToAgent(payload))

  // Screenshot
  ipcMain.handle('screenshot:capture', async () => {
    if (!mainWindow_ref) return null
    return captureWebview(mainWindow_ref)
  })

  // Open external link in system browser
  ipcMain.on('open:external', (_event, url) => shell.openExternal(url))
}

// ─── App lifecycle ─────────────────────────────────────────────────────────

app.whenReady().then(() => {
  registerIpcHandlers()
  const config = loadConfig()

  if (isFirstRun(config)) {
    createOnboardingWindow()
  } else {
    createMainWindow(config)
    connectToAgent(config)
    startAgentProcess()
  }
})

app.on('window-all-closed', () => {
  stopAgentProcess()
  clearTimeout(wsReconnectTimer)
  if (process.platform !== 'darwin') app.quit()
})

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) {
    const config = loadConfig()
    if (isFirstRun(config)) {
      createOnboardingWindow()
    } else {
      createMainWindow(config)
    }
  }
})

app.on('before-quit', stopAgentProcess)
