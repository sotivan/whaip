/**
 * WHAIP – Electron preload script
 * Exposes window.whaip to the renderer via contextBridge.
 */

const { contextBridge, ipcRenderer } = require('electron')

contextBridge.exposeInMainWorld('whaip', {
  // ── Config ─────────────────────────────────────────────────────────────
  getConfig: ()       => ipcRenderer.invoke('config:get'),
  saveConfig: (data)  => ipcRenderer.invoke('config:save', data),

  // ── Onboarding ─────────────────────────────────────────────────────────
  onboardingDone: ()  => ipcRenderer.send('onboarding:done'),

  // ── Screenshots ────────────────────────────────────────────────────────
  captureScreenshot:  () => ipcRenderer.invoke('screenshot:capture'),

  // ── WHP bridge ─────────────────────────────────────────────────────────
  sendToAgent:        (payload)  => ipcRenderer.send('whp:send', payload),
  onAgentMessage:     (callback) => ipcRenderer.on('whp:message',  (_e, d) => callback(d)),
  onAgentStatus:      (callback) => ipcRenderer.on('whp:status',   (_e, d) => callback(d)),
  offAgentMessage:    ()         => ipcRenderer.removeAllListeners('whp:message'),
  offAgentStatus:     ()         => ipcRenderer.removeAllListeners('whp:status'),

  // ── Utilities ──────────────────────────────────────────────────────────
  openExternal: (url) => ipcRenderer.send('open:external', url),
})
