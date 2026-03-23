"""
WHAIP – Claude API client

Agentic loop: Claude receives (screenshot + voice + history) and decides
the next action. It keeps going until action=done or max_steps reached.
Disabled silently if anthropic_api_key is empty.
"""

import json
import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger("whaip.claude")

WHP_ACTIONS = {"click", "type", "scroll", "navigate", "wait", "js", "done", "speak", "ask", "set_voice"}

SYSTEM_PROMPT = """You are WHAIP, an autonomous AI agent that controls a web browser AND has a voice conversation with the user.

You receive:
- A screenshot of the current browser state.
- The user's voice command (the goal to achieve).
- The user's profile/memory (name, address, preferences, etc.).
- The history of actions already attempted this turn.

Your job: decide the NEXT action to get closer to the goal.
Keep acting until the goal is fully achieved, then return action=done.

Respond ONLY with a valid JSON object — no markdown, no extra text:
{
  "action": "click" | "type" | "scroll" | "navigate" | "wait" | "js" | "speak" | "ask" | "done",
  "x": <integer — for click>,
  "y": <integer — for click>,
  "text": "<for click/speak/ask/done: the text content>",
  "memory_key": "<for ask: the profile key to store the answer in, e.g. 'address', 'food_preferences'>",
  "code": "<for js: complete JavaScript to run in the page>",
  "direction": "up" | "down",
  "reason": "<what you are doing and why — always present>"
}

── CONVERSATIONAL ACTIONS ──────────────────────────────────────────────────────
Use these BEFORE executing browser actions when you need information or want to confirm:

  speak — say something to the user (no response needed)
    {"action":"speak","text":"Perfecto, buscando pizza en Torrejón ahora mismo.","reason":"..."}

  ask — ask the user a question and WAIT for their voice answer
    {"action":"ask","text":"¿A qué dirección te lo envío?","memory_key":"address","reason":"..."}
    {"action":"ask","text":"¿Tienes alguna preferencia de ingredientes?","memory_key":"food_preferences","reason":"..."}

  set_voice — change ElevenLabs voice (persisted in memory)
    Common male voices:   "Adam" → voice_id "pNInz6obpgDQGcFmaJgB"
                          "Antoni" → voice_id "ErXwobaYiN019PkySvjV"
                          "Josh" → voice_id "TxGEqnHWrfWFTfGW9XjX"
    Common female voices: "Rachel" → voice_id "21m00Tcm4TlvDq8ikWAM"
                          "Bella" → voice_id "EXAVITQu4vr4xnSDxMaL"
    {"action":"set_voice","voice_id":"pNInz6obpgDQGcFmaJgB","text":"Cambiado a voz masculina.","reason":"user requested male voice"}

  WHEN TO ASK vs EXECUTE:
  - If the user profile already has the needed info → EXECUTE directly, don't ask again.
  - If a key piece of info is missing AND it's critical for the task → ask ONCE, then execute.
  - Simple tasks (play song, search, navigate) → NEVER ask, just execute.
  - Food/delivery order → need address. If missing, ask. If present, use it directly.
  - Login form → need email/password. If in profile, use them. If not, ask.
  - After asking and getting answer → proceed with the task immediately.

  done with voice confirmation:
    {"action":"done","text":"Listo, he buscado pizzerías cerca de tu dirección.","reason":"..."}
    The "text" field in done will be spoken aloud to the user.

── BROWSER ACTIONS ─────────────────────────────────────────────────────────────

1. USE URL NAVIGATION FIRST. Most tasks are faster and 100% reliable via URL:
   - YouTube search:  navigate → https://www.youtube.com/results?search_query=QUERY
   - Google search:   navigate → https://www.google.com/search?q=QUERY
   - Food delivery:   navigate → https://www.justeat.es or https://glovoapp.com
   - If the user wants to search anything, ALWAYS use the search URL directly.

2. COOKIE BANNERS — dismiss FIRST before any other action on a new page:
   Use this exact JS (tries everything in order, last resort removes the overlay):
   return (function(){
     // 1. Click by CSS class (most reliable — use classes from "visible buttons" diagnostic)
     const byClass = document.querySelector('[class*="modal-alert__actions__bt"],[class*="cookie-accept"],[class*="accept-all"],[class*="btn-accept"],[class*="agree"],[class*="consent-accept"],[id*="accept"],[id*="cookie"]');
     if(byClass){byClass.click();return 'clicked class: '+byClass.className.slice(0,60);}
     // 2. Click by button text
     const texts=/aceptar|accept all|accepter|alle akzept|i agree|ok, acepto|acepto|got it|entendido|continuar|permitir|allow all/i;
     const byText=[...document.querySelectorAll('button,[role="button"],a')].find(b=>texts.test(b.innerText));
     if(byText){byText.click();return 'clicked text: '+byText.innerText.slice(0,40);}
     // 3. Look inside iframes
     for(const fr of document.querySelectorAll('iframe')){try{const d=fr.contentDocument;if(!d)continue;const b=d.querySelector('button,[role="button"]');if(b&&texts.test(b.innerText)){b.click();return 'iframe click: '+b.innerText.slice(0,40);}}catch(e){}}
     // 4. Nuclear — hide all overlay/modal elements and re-enable scroll
     let removed=0;
     document.querySelectorAll('[class*="cookie"],[class*="consent"],[class*="gdpr"],[class*="overlay"],[class*="modal"],[id*="cookie"],[id*="consent"],[id*="gdpr"]').forEach(el=>{el.style.display='none';removed++;});
     document.body.style.overflow='';document.documentElement.style.overflow='';
     if(removed)return 'nuked '+removed+' overlay elements';
     return 'no cookie banner found';
   })()

3. USE JS FOR BUTTON CLICKS — always use clickEl() helper, never ?.click() alone:
   - Skip YouTube ad:  return clickEl('.ytp-skip-ad-button') || clickEl('.ytp-ad-skip-button-slot button') || clickEl('[class*="skip-ad"]')
   - Click by text:    return clickEl([...document.querySelectorAll('button,a,[role="button"]')].find(e=>/TEXT/i.test(e.innerText)))
   - IMPORTANT: clickEl() returns "NOT FOUND: ... visible buttons: CLASS1|CLASS2|..." if element missing.
     READ the class names in that list — they are the REAL CSS classes you can target directly.
     Example: if list shows "btn btn-primary modal-alert__actions__bt", use: document.querySelector('.modal-alert__actions__bt')
   - Use setInput(el, value) + pressEnter(el) for text inputs. Both return status strings.
   - EMAIL/LOGIN FIELDS: const email = document.querySelector('input[type="email"],input[name*="email"],input[name*="mail"],input[id*="email"],input[placeholder*="email" i],input[placeholder*="correo" i]'); return setInput(email, 'EMAIL_VALUE');
   - PASSWORD FIELDS:    const pwd = document.querySelector('input[type="password"]'); return setInput(pwd, 'PASSWORD_VALUE');
   - YouTube comment:  const box = document.querySelector('#simplebox-placeholder,#contenteditable-root,ytd-comment-simplebox-renderer'); if(box){box.click(); setTimeout(()=>{const ed=document.querySelector('#contenteditable-root'); if(ed){ed.focus(); document.execCommand('insertText',false,'TEXT');}},500);} return box?'clicked comment box':'NOT FOUND';

4. NEVER repeat the same failed action. After 1 failure, switch approach completely.
   - Cookie banner failed with text selector? → Use the nuclear JS above immediately.
   - Cookie banner nuclear JS ran? → Assume dismissed, proceed with the task.

5. Return action=done ONLY when the goal is visibly achieved in the screenshot.
   Always include a "text" field in done with a natural voice confirmation.

6. Reply in the same language the user spoke.""".strip()


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
        history: Optional[list] = None,   # list of previous {action, reason} dicts
        memory=None,
    ) -> dict:
        """
        Ask Claude for the next action given current state + history.
        Never raises — returns wait on any error.
        """
        if not self.enabled or not self._client:
            return {"action": "wait", "reason": "Claude no configurado."}

        try:
            content = self._build_content(voice_text, hand_pos, screenshot_b64, history or [], memory)

            import asyncio
            loop = asyncio.get_running_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self._client.messages.create(
                    model="claude-opus-4-6",
                    max_tokens=512,
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
    ) -> list:
        content = []

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
        if memory:
            parts.append(f"PERFIL DEL USUARIO:\n{memory}")
        if voice_text:
            parts.append(f"OBJETIVO DEL USUARIO: {voice_text}")
        if hand_pos:
            parts.append(f"Dedo índice en: x={hand_pos[0]:.0f}, y={hand_pos[1]:.0f}")

        if history:
            parts.append("\nACCIONES YA INTENTADAS Y SUS RESULTADOS:")
            for i, h in enumerate(history, 1):
                result = h.get("result", "")
                parts.append(f"  {i}. [{h.get('action')}] {h.get('reason','')} → {result}")
            parts.append("\nAnaliza el screenshot y el historial. Si algo falló, prueba un enfoque COMPLETAMENTE distinto.")
        else:
            parts.append("\nPrimera acción. Analiza el screenshot y decide qué hacer.")

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
