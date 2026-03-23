"""
WHAIP – Claude API client

Agentic loop: Claude receives (DOM snapshot + optional screenshot + voice + history) and decides
the next action. It keeps going until action=done or max_steps reached.
Disabled silently if anthropic_api_key is empty.
"""

import json
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("whaip.claude")

WHP_ACTIONS = {"scroll", "navigate", "wait", "js", "done", "speak", "ask", "set_voice"}
# "click" intentionally removed — use js + clickEl()/clickWC() instead

SYSTEM_PROMPT = """You are WHAIP, an autonomous AI agent that controls a web browser and has a voice conversation with the user.

You receive:
- DOM SNAPSHOT: all visible buttons, inputs and links with their real CSS classes and IDs.
- Optional screenshot (only on first step and after navigation).
- User's voice goal, profile/memory, and history of previous actions with their results.

Your job: decide the NEXT single action to get closer to the goal. Keep acting until done.

Respond ONLY with a valid JSON object — no markdown, no extra text.
NEVER use action="click". Always use action="js" with clickEl() or clickWC().
{
  "action": "js" | "navigate" | "scroll" | "speak" | "ask" | "set_voice" | "wait" | "done",
  "code":      "<for js: JavaScript to run — ALWAYS return a descriptive string>",
  "text":      "<for speak/ask/done: what to say aloud>",
  "direction": "up" | "down",
  "memory_key":"<for ask: key to store the answer, e.g. 'address'>",
  "voice_id":  "<for set_voice>",
  "reason":    "<one line: what you are doing and why>"
}

══ HOW TO CLICK / INTERACT WITH ELEMENTS ══════════════════════════════════════════

You receive a DOM SNAPSHOT with the REAL CSS classes and IDs of every visible element.
ALWAYS use js action with precise selectors from the snapshot. Never guess pixel coordinates.

SELECTOR PRIORITY (use the first that matches):
  1. By id:        document.querySelector('#element-id')
  2. By class:     document.querySelector('.exact-class-from-snapshot')
  3. By text:      [...document.querySelectorAll('button,a,[role="button"]')].find(e=>/TEXT/i.test(e.innerText))
  4. By attribute: document.querySelector('input[name="field-name"]')

Reading the snapshot:
  BOTONES: "Añadir al carrito" [cls=add-btn_xyz id=add @(340,520)]
    → return clickEl(document.querySelector('#add'))
    → or:    return clickEl(document.querySelector('.add-btn_xyz'))
  INPUTS:  search [placeholder="Buscar" name=q cls=search_abc @(400,150)]
    → const el=document.querySelector('input[name="q"],.search_abc'); return setInput(el,'pizza 4 quesos');

HELPER FUNCTIONS (always available in js actions):
  clickEl(el_or_selector) — smart click; returns diagnostic if not found
  setInput(el, value)     — React-safe value setter + fires input/change events
  pressEnter(el)          — fires keydown/keypress/keyup Enter events

COMMON PATTERNS:
  // Click a button by its text
  return clickEl([...document.querySelectorAll('button,[role="button"],a')].find(e=>/TEXTO/i.test(e.innerText)))

  // Fill a text input (React-safe) and press Enter
  const el = document.querySelector('#id, input[name="name"], input[placeholder*="hint" i]');
  return setInput(el,'VALUE') + ' | ' + pressEnter(el);

  // Select/dropdown
  const s=document.querySelector('select[name="size"]'); s.value='M'; s.dispatchEvent(new Event('change',{bubbles:true})); return 'selected '+s.value;

  // Radio button (React needs synthetic events + label click)
  const r=[...document.querySelectorAll('input[type="radio"]')].find(r=>(r.value+r.id+r.closest('label')?.innerText||'').toLowerCase().includes('mediana'));
  if(r){r.checked=true;['change','click','input'].forEach(t=>r.dispatchEvent(new Event(t,{bubbles:true}))); (r.closest('label')||document.querySelector('label[for="'+r.id+'"]'))?.click(); return 'radio: '+r.value;}
  return 'radio NOT FOUND: '+[...document.querySelectorAll('input[type="radio"]')].map(r=>r.value||r.id).join('|');

  // Close a modal — use classes from snapshot, then nuclear
  return clickEl(document.querySelector('.modal-close,.close-btn,[aria-label="close"],[aria-label="cerrar"]'))
    || (document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="dialog"]').forEach(e=>e.style.display='none'),'nuked');

  // WEB COMPONENTS (pie-radio, pie-button, custom elements with '-' in tag):
  // Use clickWC('text-to-match') or clickWC('tag-name') — works with shadow DOM
  // Example: clickWC('Mediana')  → finds any custom element with text "Mediana"
  // Example: clickWC('pie-radio') → clicks the first pie-radio element
  // The DOM snapshot includes a WEBCOMPONENTS section listing all custom elements found.

══ NAVIGATION FIRST ════════════════════════════════════════════════════════════════

For most tasks, NAVIGATE directly — it's instant and 100% reliable:
  YouTube:       navigate → https://www.youtube.com/results?search_query=QUERY
  Google:        navigate → https://www.google.com/search?q=QUERY
  Just Eat ES:   navigate → https://www.just-eat.es/ (then JS to fill address + search)
  Glovo ES:      navigate → https://glovoapp.com/es/es/madrid/ (adjust city)
  Amazon ES:     navigate → https://www.amazon.es/s?k=QUERY
  Google Maps:   navigate → https://www.google.com/maps/search/QUERY

AFTER NAVIGATE: always use wait (1 step) if the DOM snapshot shows readyState=loading.
DO NOT navigate to a new URL just because the DOM snapshot has few elements — the page may still be loading. Use wait instead.

══ COOKIES & ADS — IGNORE ══════════════════════════════════════════════════════════

Cookie banners and YouTube ads are auto-dismissed by the system.
NEVER spend a step on cookies or ads — they are already handled.
If you see a banner, skip it completely and do your actual task action.

══ CONVERSATIONAL ACTIONS ══════════════════════════════════════════════════════════

speak — say something (no user response needed)
  {"action":"speak","text":"Buscando pizza 4 quesos en Torrejón...","reason":"..."}

ask — ask user and wait for voice answer
  {"action":"ask","text":"¿A qué dirección te lo envío?","memory_key":"address","reason":"..."}

set_voice — change ElevenLabs voice
  Male:   Adam=pNInz6obpgDQGcFmaJgB  Antoni=ErXwobaYiN019PkySvjV  Josh=TxGEqnHWrfWFTfGW9XjX
  Female: Rachel=21m00Tcm4TlvDq8ikWAM  Bella=EXAVITQu4vr4xnSDxMaL
  {"action":"set_voice","voice_id":"pNInz6obpgDQGcFmaJgB","text":"Cambiado a Adam.","reason":"..."}

When to ask vs execute:
  - Profile already has the info → execute directly, never ask again.
  - Simple tasks (search, play, navigate) → execute, never ask.
  - Food order without address → ask once, then proceed.
  - After getting an answer → proceed immediately.

done — task complete:
  {"action":"done","text":"Listo, he añadido la pizza al carrito.","reason":"..."}
  The "text" field is spoken aloud. Always include it.

══ ANTI-LOOP RULES ═════════════════════════════════════════════════════════════════

- NEVER repeat an action that already failed. After 1 failure → completely different approach.
- If a modal/popup blocks you: use the close pattern above ONCE. If it fails → nuclear JS.
- If nuclear JS ran → assume modal gone, proceed with the actual task.
- If same element not found twice → use navigate to a direct URL instead.

Reply in the same language the user spoke.""".strip()


class ClaudeClient:

    def __init__(self, config: dict):
        self.config  = config
        self.enabled = bool(config.get("anthropic_api_key", "").strip())
        self._client = None

    def setup(self) -> None:
        if not self.enabled:
            logger.info("ClaudeClient disabled (no anthropic_api_key).")
            return
        try:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.config["anthropic_api_key"])
            logger.info("ClaudeClient ready.")
        except ImportError:
            logger.warning("ClaudeClient disabled – anthropic package not installed.")
            self.enabled = False
        except Exception as exc:
            logger.warning("ClaudeClient disabled – %s", exc)
            self.enabled = False

    # ── Public API ─────────────────────────────────────────────────────────

    async def decide(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        history: Optional[list] = None,
        memory: Optional[str] = None,
        dom_snapshot: Optional[str] = None,
    ) -> dict:
        """
        Ask Claude for the next action given current state + history.
        Never raises — returns wait on any error.
        """
        if not self.enabled or not self._client:
            return {"action": "wait", "reason": "Claude no configurado."}

        try:
            content = self._build_content(
                voice_text, hand_pos, screenshot_b64, history or [], memory, dom_snapshot
            )

            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model="claude-sonnet-4-6",
                    max_tokens=350,
                    system=SYSTEM_PROMPT,
                    messages=[{"role": "user", "content": content}],
                ),
            )

            raw = response.content[0].text
            return self._parse_response(raw)

        except Exception as exc:
            logger.error("Claude API error: %s", exc)
            return {"action": "wait", "reason": f"Error: {exc}"}

    # ── Internal ───────────────────────────────────────────────────────────

    def _build_content(
        self,
        voice_text: Optional[str],
        hand_pos: Optional[Tuple[float, float]],
        screenshot_b64: Optional[str],
        history: list,
        memory: Optional[str] = None,
        dom_snapshot: Optional[str] = None,
    ) -> list:
        content = []

        # Screenshot only when provided (first step + after navigation)
        if screenshot_b64:
            content.append({
                "type": "image",
                "source": {
                    "type":       "base64",
                    "media_type": "image/jpeg",
                    "data":       screenshot_b64,
                },
            })

        parts = []

        # User profile
        if memory:
            parts.append(f"PERFIL DEL USUARIO:\n{memory}")

        # Goal
        if voice_text:
            parts.append(f"OBJETIVO: {voice_text}")

        # Hand position (MediaPipe, when available)
        if hand_pos:
            parts.append(f"Dedo índice en: x={hand_pos[0]:.0f}, y={hand_pos[1]:.0f}")

        # DOM snapshot — the most important context for element targeting
        if dom_snapshot:
            try:
                snap = json.loads(dom_snapshot)
                ready = snap.get("readyState", "complete")
                loading_warn = " ⚠️ PÁGINA CARGANDO (readyState=loading) — usa wait antes de actuar" if ready != "complete" else ""
                lines = [f"DOM SNAPSHOT — {snap.get('url','')} | {snap.get('title','')}{loading_warn}"]

                btns = snap.get("buttons", [])
                if btns:
                    parts_b = []
                    for b in btns:
                        txt = b.get("text", "").strip()
                        cls = b.get("cls", "").strip()
                        bid = b.get("id", "").strip()
                        x, y = b.get("x", 0), b.get("y", 0)
                        desc = f'"{txt}"'
                        if bid:   desc += f" [id={bid}]"
                        if cls:   desc += f" [cls={cls[:50]}]"
                        desc += f" @({x},{y})"
                        parts_b.append(desc)
                    lines.append("BOTONES: " + " | ".join(parts_b))

                inps = snap.get("inputs", [])
                if inps:
                    parts_i = []
                    for i in inps:
                        desc = f'type={i.get("type","")} placeholder="{i.get("placeholder","")}"'
                        if i.get("name"): desc += f' name={i["name"]}'
                        if i.get("id"):   desc += f' id={i["id"]}'
                        if i.get("cls"):  desc += f' cls={i["cls"][:40]}'
                        desc += f' @({i.get("x",0)},{i.get("y",0)})'
                        parts_i.append(desc)
                    lines.append("INPUTS: " + " | ".join(parts_i))

                lnks = snap.get("links", [])
                if lnks:
                    parts_l = []
                    for lk in lnks[:15]:
                        txt = lk.get("text", "").strip()
                        href = lk.get("href", "")
                        lid = lk.get("id", "")
                        lcls = lk.get("cls", "")
                        desc = f'"{txt}" href={href[:60]}'
                        if lid:  desc += f" id={lid}"
                        if lcls: desc += f" cls={lcls[:40]}"
                        parts_l.append(desc)
                    lines.append("LINKS: " + " | ".join(parts_l))

                wcs = snap.get("webcomponents", [])
                if wcs:
                    parts_wc = [f'{w["tag"]}["{w["text"]}"' + (f' id={w["id"]}' if w["id"] else '') + ']' for w in wcs]
                    lines.append("WEB COMPONENTS (usa clickWC): " + " | ".join(parts_wc))

                pg_text = snap.get("text", "")
                if pg_text:
                    lines.append(f"TEXTO VISIBLE: {pg_text}")

                parts.append("\n".join(lines))
            except Exception:
                parts.append(f"DOM RAW: {dom_snapshot[:500]}")

        # History
        if history:
            parts.append("\nHISTORIAL DE ACCIONES:")
            for i, h in enumerate(history, 1):
                result = h.get("result", "")
                parts.append(f"  {i}. [{h.get('action')}] {h.get('reason','')} → {result}")
            parts.append(
                "\nUSA el DOM SNAPSHOT para encontrar los selectores correctos. "
                "Si algo falló, prueba un enfoque COMPLETAMENTE distinto."
            )
        else:
            parts.append("\nPrimera acción. Usa el DOM SNAPSHOT y decide qué hacer.")

        content.append({"type": "text", "text": "\n".join(parts)})
        return content

    def _parse_response(self, raw: str) -> dict:
        text = raw.strip()
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group())
                except json.JSONDecodeError:
                    return {"action": "wait", "reason": "Respuesta no parseable."}
            else:
                return {"action": "wait", "reason": "Sin JSON en respuesta."}

        action = data.get("action", "wait")
        if action not in WHP_ACTIONS:
            data["action"] = "wait"

        if not data.get("reason"):
            data["reason"] = action

        logger.info("Claude → %s | %s", data["action"], data.get("reason", ""))
        return data
