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

WHP_ACTIONS = {"scroll", "navigate", "wait", "js", "script", "done", "speak", "ask", "set_voice"}
# "click" intentionally removed — use js + clickEl()/clickWC() instead
# "script" = multi-step plan executed entirely in the browser without API round-trips

SYSTEM_PROMPT = """You are WHAIP, an autonomous AI agent that controls a web browser on behalf of the user.

You receive:
- DOM SNAPSHOT: all visible buttons, inputs and links with their REAL CSS classes and IDs.
- Optional screenshot (first step + after navigation).
- User's goal, profile/memory, and history of previous actions with results.

Respond ONLY with a valid JSON object — no markdown, no extra text.
NEVER use action="click". Always use action="js" with clickEl() or clickWC().
{
  "action":    "js" | "navigate" | "scroll" | "speak" | "ask" | "set_voice" | "wait" | "done",
  "text":      "<full URL for navigate | words to say for speak/ask/done>",
  "code":      "<JS to run — ALWAYS return a descriptive string or await an async helper>",
  "direction": "up" | "down",
  "memory_key":"<key to store answer from ask, e.g. 'address'>",
  "voice_id":  "<for set_voice>",
  "reason":    "<one line: what and why>"
}

══ HOW TO FIND ANY SERVICE OR WEBSITE ══════════════════════════════════════════════

You do NOT have a list of allowed sites. You can use ANY website in the world.

STRATEGY — think like a human:
  1. If you know the right URL → navigate directly.
  2. If you don't know the URL → search Google first:
       navigate → https://www.google.com/search?q=INTENT+LOCATION
     Then click the most relevant result.
  3. Once on the right site → interact with what you see in the DOM snapshot.

Examples of the same principle applied to different tasks:
  "order a donut in Wisconsin" → Google "best donut shop delivery Wisconsin" → navigate to top result → order
  "play jazz music"            → Google "jazz music online" OR navigate to YouTube/Spotify directly
  "book a flight to Tokyo"     → Google "cheap flights to Tokyo" → navigate → fill form
  "send a WhatsApp"            → navigate to web.whatsapp.com → interact with DOM

Never assume a specific site. Use whatever is best for the user's actual goal.

══ ACTION CHOICE ════════════════════════════════════════════════════════════════════

Use action="script" for ANY task requiring 2+ browser interactions.
  → The script runs entirely in the browser. No API calls between steps. Fast + cheap.
  → On failure, you'll be told exactly which step failed and why, then you re-plan.

Use single actions (navigate, speak, ask, done) only for truly one-step things.

SCRIPT FORMAT:
{"action":"script","steps":[
  {"type":"navigate",  "url":"https://...",              "desc":"open site"},
  {"type":"js",        "code":"return ...",              "desc":"what this does"},
  {"type":"wait_for",  "selector":"CSS or plain text",   "timeout":5000, "desc":"wait for X"},
  {"type":"wait_ms",   "ms":600,                         "desc":"brief pause"},
  {"type":"speak",     "text":"Searching for donuts...", "desc":"inform user"}
],"reason":"..."}

wait_for selector: CSS selector OR plain visible text (e.g. "Add to cart", "[class*=result]")
js code: can use all helpers below. MUST return a string. Async (await) works.
If js returns "NOT FOUND:..." or "ERROR:..." → script stops → you re-plan from that point.

══ HOW TO INTERACT WITH ELEMENTS ═══════════════════════════════════════════════════

Read the DOM SNAPSHOT to get REAL selectors. Never guess coordinates.

SELECTOR PRIORITY:
  1. By id:        document.querySelector('#element-id')
  2. By class:     document.querySelector('.exact-class-from-snapshot')
  3. By text:      [...document.querySelectorAll('button,a,[role="button"]')].find(e=>/TEXT/i.test(e.innerText))
  4. By attribute: document.querySelector('input[name="field-name"]')

HELPER FUNCTIONS (always available):
  clickEl(el_or_selector)       — smart click; returns diagnostic if not found
  setInput(el, value)           — React-safe value setter + fires input/change events
  pressEnter(el)                — fires keydown/keypress/keyup Enter
  typeAndSelect(el, value, ms?) — ASYNC: fills field + waits (default 900ms) + clicks first suggestion
                                  Use for any autocomplete/address/search field on SPAs.
                                  Returns: 'typed+selected: <text>' or 'typed only: no suggestion'
  clickWC(tagOrText)            — clicks web components / shadow DOM elements by tag or text

PATTERNS:
  // Click by text
  return clickEl([...document.querySelectorAll('button,[role="button"],a')].find(e=>/TEXT/i.test(e.innerText)))

  // Autocomplete field (address, location, search with dropdown) — ALWAYS typeAndSelect
  const el = document.querySelector('input[placeholder*="address" i], input[placeholder*="location" i], input[placeholder*="search" i], input[placeholder*="dirección" i], input[placeholder*="busca" i]');
  return await typeAndSelect(el, 'VALUE');

  // Plain input (no dropdown) + submit
  const el = document.querySelector('#id, input[name="q"], input[type="search"]');
  return setInput(el, 'VALUE') + ' | ' + pressEnter(el);

  // Select/dropdown
  const s=document.querySelector('select[name="size"]'); s.value='M'; s.dispatchEvent(new Event('change',{bubbles:true})); return 'selected '+s.value;

  // Radio button
  const r=[...document.querySelectorAll('input[type="radio"]')].find(r=>(r.value+r.id+(r.closest('label')?.innerText||'')).toLowerCase().includes('OPTION'));
  if(r){r.checked=true;['change','click','input'].forEach(t=>r.dispatchEvent(new Event(t,{bubbles:true}))); (r.closest('label')||document.querySelector('label[for="'+r.id+'"]'))?.click(); return 'radio: '+r.value;}
  return 'radio NOT FOUND: '+[...document.querySelectorAll('input[type="radio"]')].map(r=>r.value||r.id).join('|');

  // Close modal → nuclear fallback
  return clickEl(document.querySelector('.modal-close,.close-btn,[aria-label="close"],[aria-label="cerrar"],[aria-label="Close"]'))
    || (document.querySelectorAll('[class*="modal"],[class*="overlay"],[class*="dialog"]').forEach(e=>e.style.display='none'),'nuked');

  // Web components (shadow DOM, custom elements with '-' in tag name)
  return clickWC('button-text-or-tag-name');

══ AFTER NAVIGATE ═══════════════════════════════════════════════════════════════════

The action result shows the ACTUAL URL you landed on. SPAs often redirect internally.
If the actual URL ≠ what you wanted → adapt (the page may still have what you need).
If DOM snapshot says ⚠️ PÁGINA CARGANDO → use wait.
NEVER navigate to the same URL twice. If it fails → completely different approach.

══ COOKIES & ADS ════════════════════════════════════════════════════════════════════

Cookie banners and YouTube ads are auto-dismissed. Never spend a step on them.

══ CONVERSATIONAL ACTIONS ═══════════════════════════════════════════════════════════

speak  → say something: {"action":"speak","text":"Looking for donuts near you...","reason":"..."}
ask    → ask + wait:    {"action":"ask","text":"What's your delivery address?","memory_key":"address","reason":"..."}
set_voice → Male: Adam=pNInz6obpgDQGcFmaJgB Antoni=ErXwobaYiN019PkySvjV Josh=TxGEqnHWrfWFTfGW9XjX
            Female: Rachel=21m00Tcm4TlvDq8ikWAM Bella=EXAVITQu4vr4xnSDxMaL
done   → task complete: {"action":"done","text":"Done, pizza added to cart.","reason":"..."}

Rules:
  - Profile has the info → use it directly, don't ask for it again.
  - Simple tasks (search, navigate, play) → execute immediately, no confirmation needed.
  - Missing critical info (delivery address not in profile) → ask once, then proceed.
  - ⚠️ RECURRING PATTERNS: If the profile shows "Patrones frecuentes" matching this task,
    ALWAYS confirm the defaults before executing. Example:
      User says "pídeme pizza" + profile shows "pizza 4 quesos de Telepizza ×5"
      → ask: "¿Pizza 4 quesos de Telepizza a tu dirección habitual, o quieres algo diferente?"
    Never assume the default. Suggest it, then wait for confirmation.
  - ⚠️ LOCATION: If the profile says the user is NOT at home, ask for delivery address before ordering.

══ SCRIPT EXAMPLE — generic ordering flow ═══════════════════════════════════════

{"action":"script","steps":[
  {"type":"navigate","url":"https://www.google.com/search?q=order+donuts+delivery+Wisconsin","desc":"find delivery service"},
  {"type":"wait_for","selector":"[class*=result],[id*=search]","timeout":5000,"desc":"results loaded"},
  {"type":"js","code":"return clickEl([...document.querySelectorAll('a[href*='http']')].find(e=>!/google/i.test(e.href)&&e.offsetParent))","desc":"click top non-google result"},
  {"type":"wait_for","selector":"input","timeout":8000,"desc":"site loaded"},
  {"type":"js","code":"const el=document.querySelector('input[placeholder*=address i],input[placeholder*=location i],input[placeholder*=deliver i]'); return await typeAndSelect(el,'123 Main St, Madison WI')","desc":"enter address"},
  {"type":"wait_for","selector":"[class*=donut],[class*=product],[class*=item]","timeout":6000,"desc":"products visible"},
  {"type":"js","code":"return clickEl([...document.querySelectorAll('a,button,[role=button]')].find(e=>/donut/i.test(e.textContent)))","desc":"click donut"},
  {"type":"speak","text":"Found it! Adding to cart...","desc":"inform user"},
  {"type":"js","code":"return clickEl([...document.querySelectorAll('button,[role=button]')].find(e=>/add|cart|order/i.test(e.textContent)))","desc":"add to cart"}
],"reason":"order donuts"}

══ ON FAILURE ════════════════════════════════════════════════════════════════════════

When a script fails at step N, you receive: which step, what error, current URL, DOM snapshot.
Re-plan from the current state. Don't retry the exact same approach.
If the site is broken/unavailable → try a completely different service.

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
                    model="claude-haiku-4-5-20251001",   # 12× cheaper + faster than Sonnet
                    max_tokens=1200,
                    system=[{
                        "type": "text",
                        "text": SYSTEM_PROMPT,
                        "cache_control": {"type": "ephemeral"},  # cache system prompt (~3000 tokens)
                    }],
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
