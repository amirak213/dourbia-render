from __future__ import annotations
import asyncio, logging, re, unicodedata
from typing import Optional
from core.config import settings
from core.infra import cb_guard, with_retry

log = logging.getLogger("dourbia.guardrails")

_INJECTION_PATTERNS = [
    r"ignore\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"disregard\s+(?:all\s+)?(?:previous|prior)\s+instructions",
    r"forget\s+everything",
    r"<\s*system\s*>", r"\[INST\]", r"you\s+are\s+now\s+(?:a|an|the)\s+",
    r"ignore[rz]\s+(?:toutes?\s+)?(?:les?\s+)?instructions?\s+précédentes",
    r"oublie[rz]\s+(?:tout|toutes\s+les\s+instructions)",
    r"tu\s+es\s+maintenant\s+(?:un|une)\s+",
    r"act\s+as\s+(?:a|an)\s+", r"pretend\s+(?:to\s+be|you\s+are)\s+",
    r"repeat\s+(?:your\s+)?(?:system\s+)?prompt",
    r"révèle\s+(?:tes|vos)\s+instructions",
    r"SELECT\s+\*\s+FROM", r"DROP\s+TABLE",
]
_COMPILED = [re.compile(p, re.IGNORECASE | re.UNICODE) for p in _INJECTION_PATTERNS]

def _normalize_unicode(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    homoglyphs = {"а":"a","е":"e","о":"o","р":"p","с":"c","х":"x","у":"y","і":"i","ѕ":"s"}
    return "".join(homoglyphs.get(c, c) for c in normalized)

async def input_guard(message: str, groq_client=None) -> tuple[bool, float, str]:
    if not message or not message.strip():
        return True, 0.0, ""
    normalized = _normalize_unicode(message.lower())
    for pattern in _COMPILED:
        if pattern.search(normalized):
            log.warning(f"[GUARD] Injection pattern : {message[:80]}")
            return False, 1.0, f"Pattern injection: {pattern.pattern[:40]}"

    if settings.guardrails_enabled and groq_client and settings.groq_api_key:
        try:
            async def _call():
                return await asyncio.to_thread(
                    groq_client.chat.completions.create,
                    model=settings.groq_model_guard, max_tokens=10,
                    messages=[{"role":"user","content":f"<|begin_of_text|><|start_header_id|>user<|end_header_id|>\n\n{message[:500]}\n<|eot_id|>"}])
            response = await cb_guard.call(with_retry(_call, max_retries=1, base_delay=0.5))
            text = response.choices[0].message.content.strip().lower()
            if text.startswith("unsafe"):
                cat = text.split("\n")[1] if "\n" in text else "unknown"
                log.warning(f"[GUARD] Llama Guard UNSAFE [{cat}] : {message[:60]}")
                return False, 0.95, f"Llama Guard: unsafe [{cat}]"
            return True, 0.05, ""
        except Exception as e:
            log.debug(f"[GUARD] Llama Guard indispo : {e}")
            return True, 0.0, ""
    return True, 0.0, ""

_DANGEROUS_HTML = re.compile(
    r"<(?:script|iframe|object|embed|form|meta|link)[^>]*>.*?</(?:script|iframe|object|embed|form)>|javascript:|on\w+\s*=",
    re.IGNORECASE | re.DOTALL)
_SCRAPE_INJECT = re.compile(
    r"(?:ignore|forget|disregard)\s+(?:previous|all)\s+(?:instructions?|rules?)|system\s*:\s*you\s+are|\[SYSTEM\]|\[INST\]|<system>",
    re.IGNORECASE)

def sanitize_scraped_content(content: str, source_url: str = "") -> str:
    if not content: return content
    cleaned = _DANGEROUS_HTML.sub("", content)
    if _SCRAPE_INJECT.search(cleaned):
        log.warning(f"[SCRAPE GUARD] Injection indirecte dans {source_url}")
        cleaned = _SCRAPE_INJECT.sub("[CONTENU FILTRÉ]", cleaned)
    return cleaned[:2000]

def sanitize_car_listing(car: dict, source_url: str = "") -> dict:
    safe = {}
    for f in ["marque","modele","agence","ville","source_label"]:
        v = car.get(f,"")
        safe[f] = sanitize_scraped_content(str(v), source_url)[:100] if isinstance(v,str) else ""
    for f in ["prix_jour","note"]:
        safe[f] = None
    safe["disponible_scraping"] = bool(car.get("disponible_scraping",False))
    url = car.get("url_source","")
    safe["url_source"] = url[:200] if isinstance(url,str) and url.startswith("https://") else ""
    # FIX BUG URL : conserver le lien Markdown pré-formaté pour l'affichage
    lien = car.get("lien_affiche","")
    safe["lien_affiche"] = lien[:300] if isinstance(lien,str) else ""
    return safe

def output_guard(reply: str, session_id: str = "") -> tuple[str, list]:
    """
    FIX : Liste de leaks élargie pour couvrir les marqueurs internes du system prompt.
    """
    warnings = []
    leaks = [
        "INTERDICTIONS ABSOLUES", "LEÇONS APPRISES", "build_system_prompt", "GROQ_API_KEY",
        # Marqueurs internes du system prompt qui peuvent fuiter
        "[FOCUS]", "━━━ COLLECTE", "━━━ COMPORTEMENT", "━━━ INTERDICTIONS",
        "build_focused_system_prompt", "SYSTEM_PROMPT_BASE",
        "LEÇONS APPRISES", "[MÉMOIRE CLIENT]", "[CONTEXTE MÉMORISÉ",
    ]
    for leak in leaks:
        if leak in reply:
            log.error(f"[OUTPUT GUARD] Fuite system prompt : {leak}")
            reply = reply.replace(leak, "[CONTENU MASQUÉ]")
            warnings.append(f"Fuite: {leak}")
    return reply, warnings


import html as _html_mod

def escape_html(value: str) -> str:
    """Échappe les caractères HTML dangereux pour prévenir le XSS."""
    return _html_mod.escape(str(value), quote=True)
