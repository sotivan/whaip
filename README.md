# WHAIP

WHAIP is an AI-powered desktop browser that you control with your voice and hand gestures — a built-in agent sees the screen, understands your intent, and acts on the browser for you in real time.

---

## Install

```bash
curl -fsSL https://raw.githubusercontent.com/[usuario]/whaip/main/scripts/install.sh | bash
```

Requirements: **Node 18+**, **Python 3.10+**, **git**.

---

## Configure

Open `~/.whaip/whaip.config.yaml` (or run `whaip config`) and fill in the keys you want to enable.
Leaving a key empty disables that module silently — nothing breaks.

```yaml
# Minimum to get started (AI control)
anthropic_api_key: "sk-ant-..."

# Optional: voice synthesis
elevenlabs_api_key: "..."
elevenlabs_voice_id: "21m00Tcm4TlvDq8ikWAM"

# Optional: remote sync
supabase_url: "https://xxxx.supabase.co"
supabase_key: "..."

# Optional: Google sign-in
google_client_id: "..."
google_client_secret: "..."

# Agent tuning
agent:
  whisper_model: "base"   # tiny | base | small | medium | large
  language: "es"          # speech recognition language
```

---

## Start

```bash
whaip start          # launches the full Electron app + Python agent
```

Or run them separately for development:

```bash
# Terminal 1 – Python agent
whaip agent

# Terminal 2 – Electron window
npm --prefix ~/.whaip start
```

---

## How it works

1. **Voice** — Whisper listens to your microphone and transcribes commands.
2. **Vision** — MediaPipe tracks your index finger on the webcam.
3. **Screenshot** — Electron captures the current browser viewport.
4. **Claude** — All three inputs are sent to Claude, which returns a WHP action JSON.
5. **Execute** — Electron performs the action (click, type, scroll, navigate…) in the webview.
6. **Speak** — ElevenLabs reads the agent's reasoning aloud.
7. **Repeat** — the loop continues.

---

## Project layout

```
whaip/
├── electron/          # Electron main process + renderer UI
├── agent/             # Python agent (voice, vision, Claude, memory)
│   └── integrations/  # ElevenLabs, Supabase, Google OAuth
├── network/           # P2P layer (WHP protocol over libp2p)
├── scripts/           # install.sh
└── whaip.config.yaml  # all configuration lives here
```

---

## License

MIT
