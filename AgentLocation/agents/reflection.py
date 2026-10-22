from __future__ import annotations
import asyncio, json, logging
from core.config import settings
from memory.memory_manager import store_lesson, recall_lessons

log = logging.getLogger("dourbia.reflection")

_EVAL_PROMPT = """Évalue la réponse agent (location voitures Tunisie).

ERREURS CRITIQUES (needs_replay=true) :
  C1. Voiture inventée sans appeler rechercher_avec_fallback_scraping
  C2. reserver_voiture appelé avec données incomplètes
  C3. Écrit "CONFIRMÉE" au lieu de "EN_ATTENTE"
  C5. Propose de réserver via Dourbia des résultats scraping
  C6. Confirme une réservation (dossier RES-...) sans avoir appelé reserver_voiture
  C7. Utilise le placeholder RES-XXXXXX au lieu d'un vrai numéro retourné par reserver_voiture

ERREURS MINEURES (correction sans replay) :
  M1. Pas en français  M2. Numéro dossier absent APRÈS un appel réussi à reserver_voiture
  M3. Ton robotique    M4. Prix total non calculé

User: "{user_message}"
Outils: {tools_called}
Résultats: {tool_results}
Réponse: "{agent_reply}"


"correction" doit être la réécriture complète de la réponse de Yasmine en français naturel.
PAS une liste d'erreurs. PAS des instructions. UNE vraie réponse client.
Si needs_replay=true, mettre correction=null.
   
JSON uniquement:
{{"ok":true/false,"erreurs_critiques":[],"erreurs_mineures":[],"error_type":null,
"trigger_pattern":null,"lesson":null,
"correction":"RÉÉCRITURE COMPLÈTE de la réponse agent en français, ou null si needs_replay=true",
"needs_replay":false}}"""

async def evaluate_response(user_message, agent_reply, tools_called, tool_results, groq_client):
    if not settings.reflection_enabled:
        return {"ok":True,"needs_replay":False}
    tools_s = [{"name":t.get("name",""),"args":str(t.get("args",""))[:80]} for t in (tools_called or [])]
    results_s = [str(r)[:150] for r in (tool_results or [])]
    try:
        resp = await asyncio.to_thread(
            groq_client.chat.completions.create,
            model=settings.groq_model_fast,
            max_tokens=400,
            temperature=0,
            response_format={"type":"json_object"},
            messages=[{"role":"user","content":_EVAL_PROMPT.format(
                user_message=user_message[:400],
                tools_called=json.dumps(tools_s,ensure_ascii=False),
                tool_results=json.dumps(results_s,ensure_ascii=False),
                agent_reply=agent_reply[:1500]  # FIX : était 600, trop court avec max_tokens=1200
            )}]
        )
        return json.loads(resp.choices[0].message.content)
    except Exception as e:
        log.debug(f"[REFLECTION] evaluate_response : {e}")
        return {"ok":True,"needs_replay":False}

async def reflexion_loop(user_message, agent_reply, tools_called, tool_results,
                          history, system_prompt, groq_client, replay_fn, max_replays=1):
    triggered=False; corrected=False; stored_lessons=[]
    current_reply=agent_reply; current_tools=tools_called; current_results=tool_results

    for attempt in range(max_replays+1):
        ev = await evaluate_response(user_message, current_reply, current_tools, current_results, groq_client)
        ok=ev.get("ok",True); needs_replay=ev.get("needs_replay",False)
        error_type=ev.get("error_type"); trigger=ev.get("trigger_pattern")
        lesson=ev.get("lesson"); correction=ev.get("correction")
        critiques=ev.get("erreurs_critiques",[]); mineurs=ev.get("erreurs_mineures",[])

        if ok: break
        triggered = True
        log.info(f"[REFLECTION] T{attempt+1} critiques={critiques} mineurs={mineurs} replay={needs_replay}")

        if error_type and trigger and lesson:
            lid = await store_lesson(trigger_pattern=trigger, lesson=lesson, error_type=error_type)
            if lid: stored_lessons.append(lid)

        if not needs_replay and correction and isinstance(correction, str):
            if len(correction) > 50 and not any(
               kw in correction for kw in ["Appeler", "appeler", "C1", "C2", "M1", "M2",
                                     "compléter", "utiliser le statut", "écrire en français"]
            ):
                current_reply = correction; corrected = True
                log.info("[REFLECTION] Correction appliquée (sans replay)")
            else:
                log.warning("[REFLECTION] Correction rejetée (ressemble à un résumé d'erreurs)")
            break

        if needs_replay and replay_fn and attempt < max_replays:
            lessons = await recall_lessons(user_message, top_k=3)
            lesson_injection = "\n[LEÇONS — APPLIQUER MAINTENANT]\n"
            for l in lessons:
                lesson_injection += f"  ⚠ [{l['error_type']}] {l['lesson']}\n"
            if lesson: lesson_injection += f"  ⚠ [ACTUEL — {error_type}] {lesson}\n"
            enhanced = system_prompt + lesson_injection
            try:
                new_reply, new_tools, new_results = await replay_fn(history=history, system_prompt=enhanced)
                current_reply=new_reply; current_tools=new_tools; current_results=new_results; corrected=True
                log.info(f"[REFLECTION] Replay {attempt+1} effectué")
            except Exception as e:
                log.error(f"[REFLECTION] Replay erreur : {e}"); break
        else:
            if correction: current_reply=correction; corrected=True
            break

    return current_reply, triggered, corrected, stored_lessons
