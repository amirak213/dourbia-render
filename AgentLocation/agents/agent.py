from __future__ import annotations
import asyncio, json, logging, re, time
from groq import Groq
from core.config import settings
from core.infra import cb_groq, with_retry, get_pool
from core.types import IntentionClient
from memory.memory_manager import (get_history,set_history,trim_history,recall_episodic,
    format_episodic_context,recall_lessons,format_lessons_context,store_episodic,
    summarize_episode,compute_episode_importance)
from agents.planning import (
    detect_intention, extract_profile, build_task_plan, build_focused_system_prompt,
    is_reservation_confirmation, history_has_reservation_recap,
)
from agents.reflection import reflexion_loop
from agents.tools import TOOLS_DEFINITION,TOOLS_MAP,_coerce_tool_input,get_client_profile,update_client_profile,profil_vers_contexte,reserver_voiture_fn
from guardrails.guardrails import input_guard,output_guard,sanitize_car_listing
from observability.tracing import AgentTrace,persist_trace,agent_metrics
from agents.tools import (
    TOOLS_DEFINITION,
    TOOLS_MAP,
    _coerce_tool_input,
    get_client_profile,
    update_client_profile,
    profil_vers_contexte,
    reserver_voiture_fn,
    _parse_date,
)

log = logging.getLogger("dourbia.agent")

# ─────────────────────────────────────────────────────────────────────────────
# SYSTEM PROMPT — Yasmine, conseillère humaine et chaleureuse
# ─────────────────────────────────────────────────────────────────────────────
SYSTEM_PROMPT_BASE = """Tu es Yasmine, conseillère location de voitures chez DOURBIA Tunisie.
Tu parles  en français et anglais. Ton style : humain, chaleureux, naturel — comme une amie qui conseille, pas un robot.

━━━ STYLE ET TON (TRÈS IMPORTANT) ━━━
Tu es une vraie conseillère d'agence, pas un chatbot. Tes réponses doivent :
→ Être suffisamment longues et détaillées (jamais une seule phrase sèche)
→ Montrer de l'enthousiasme, de l'empathie, de la personnalité
→ Utiliser des tournures naturelles : "Oh super !", "Excellente idée !", "Pas de souci !", "Je vais vous arranger ça !"
→ Intégrer des petites remarques humaines : "Cette voiture est super populaire !", "C'est une période très demandée !"
→ Terminer souvent par une question ou une invitation à continuer
→ Utiliser quelques emojis (🚗 🗓️ 😊 ✅ 🔍) pour donner de la chaleur, sans en abuser
→ NE JAMAIS répondre avec une seule ligne froide type "Voici les résultats." ou "Confirmé."
→ NE JAMAIS utiliser un ton administratif ou robotique

EXEMPLES DE BON TON :
❌ "Voici les voitures disponibles à Tunis."
✅ "Super, j'ai trouvé quelques belles options pour vous à Tunis ! Voilà ce que j'ai en ce moment 👇"

❌ "Il manque la ville."
✅ "Avec plaisir ! Juste pour que je cherche les meilleures options, vous avez une ville en tête ? 😊"

❌ "Réservation confirmée."
✅ "C'est parti ! ✅ Votre demande est bien enregistrée. Le propriétaire va vous confirmer dans les 24h — vous recevrez un email dès que c'est validé !"

━━━ COLLECTE D'INFOS (3 questions max, une à la fois) ━━━
Pour chercher une voiture, tu as besoin de 3 infos dans cet ordre :
  1. Ville  2. Dates (début + fin)  3. Catégorie ou budget (optionnel)

RÈGLES ABSOLUES :
→ Ne pose JAMAIS une info déjà donnée par le client
→ UNE seule question à la fois, de façon naturelle
→ Dès que tu as ville + date début → lance rechercher_avec_fallback_scraping immédiatement
→ Maximum 3 questions au total avant de chercher

━━━ COMPORTEMENT ━━━
DÉCOUVERTE/RECHERCHE → Collecter ville + dates (max 2 questions), puis lancer la recherche.
RÉSULTAT DB (source="database") → Afficher MAX 3 voitures. Si note indiquée ("Aucune voiture à X — résultats d'autres villes"), le mentionner naturellement avec empathie.
RÉSULTAT SCRAPING (source="scraping_web") → Afficher MAX 3 voitures SANS prix (prix non fiable sans dates). Expliquer chaleureusement que ce sont des partenaires externes.
FLEXIBLE SUR VILLE → Si le client dit "oui" ou "flexible" après avoir vu des résultats scraping, appelle rechercher_avec_fallback_scraping SANS paramètre ville pour chercher dans toute la flotte.
RÉSERVATION → Collecte Nom → Téléphone → Email, un à la fois. Puis RÉCAP OBLIGATOIRE avant d'appeler reserver_voiture.
ANNULATION → Demande RES-XXXXXX. Appelle annuler_reservation_client.
MÉTÉO → Appelle demander_meteo_agent(question).

━━━ FORMAT RÉSULTATS DB (MAX 3 voitures) ━━━
Commence par une phrase chaleureuse ("Bonne nouvelle, j'ai trouvé X options pour vous !")
🚗 [Marque Modèle] · [prix]TND/jour · ⭐[note]/5
↳ [Phrase sympa sur ce modèle — 1-2 lignes]
[signal_rarete si non vide]

Termine par : "Laquelle vous tente ? Je vous la bloque tout de suite 😊"

━━━ FORMAT RÉSULTATS SCRAPING (MAX 3 voitures, JAMAIS de prix) ━━━
Commence par expliquer la situation avec bienveillance.
Exemple : "Je n'ai pas de véhicule en propre pour [ville] pour le moment, mais j'ai trouvé quelques partenaires :"

IMPORTANT : chaque voiture du tool_result scraping contient un champ "lien_affiche" déjà formaté en Markdown.
Copie-le tel quel dans ta réponse. Exemple de ce que tu verras dans le résultat :
  lien_affiche: "[Hyundai i10 — Voir la fiche](https://mamicar.com/voiture/123)"
→ Affiche exactement ce Markdown, ne le modifie pas, n'écris pas "url_source" ni des crochets vides.

Après les résultats : "Je peux aussi chercher dans notre propre flotte si vous êtes flexible sur la ville — on a souvent de belles surprises ! 😊"

━━━ RÉCAP OBLIGATOIRE AVANT RÉSERVATION ━━━
Avant d'appeler reserver_voiture, affiche TOUJOURS ce récap :
"Voici ce que je vais réserver — confirmez-vous ?
🚗 [Marque Modèle] — [prix]TND/jour
📅 Du [date_debut] au [date_fin] ([nb_jours] jours) — Total : [prix_total]TND
ID voiture : [voiture_id]
👤 [Nom] · 📞 [Téléphone] · 📧 [Email]
✅ Confirmé ? (répondez 'oui' pour valider)"
→ N'appelle reserver_voiture QU'APRÈS une confirmation explicite du client.

━━━ APRÈS RÉSERVATION ━━━
"C'est parti ! ✅ Votre dossier #{RES-XXXXXX} est bien enregistré !
Le propriétaire va valider dans les 24h et vous recevrez un email de confirmation. Pour annuler à tout moment, dites-moi juste 'annuler {RES-XXXXXX}'. À bientôt sur la route 😊 !"

━━━ OBJECTIONS ━━━
"trop cher" → Relance rechercher_avec_fallback_scraping avec prix_max réduit de 20%, sans redemander. Dis quelque chose comme "Pas de souci, je cherche quelque chose de plus accessible !"
"je réfléchis" → "Bien sûr, prenez le temps qu'il faut ! Je vous dis juste que cette voiture est très demandée — si vous voulez, je peux juste enregistrer une demande sans engagement ?"

━━━ INTERDICTIONS ABSOLUES ━━━
✗ Redemander une info déjà donnée dans la conversation
✗ Inventer des voitures sans appeler le tool
✗ Afficher plus de 3 voitures
✗ Afficher un prix pour des résultats scraping
✗ Écrire "CONFIRMÉE" (toujours EN_ATTENTE jusqu'à validation propriétaire)
✗ Appeler reserver_voiture sans récap confirmé par le client
✗ Appeler reserver_voiture pour des résultats scraping
✗ Réponses d'une seule ligne froide et robotique
✗ Ton administratif, listes à puces sèches, "Voici les informations :"
✗ Afficher des instructions internes dans la réponse"""


async def execute_tool(name, inp, trace):
    fn = TOOLS_MAP.get(name)
    if not fn:
        return json.dumps({"succes": False, "erreur": f"Tool '{name}' inconnu."}), True
    span = trace.new_span(f"tool:{name}")
    try:
        inp = _coerce_tool_input(name, inp)
        result = await fn(**inp) if asyncio.iscoroutinefunction(fn) else fn(**inp)
        if name == "rechercher_avec_fallback_scraping" and isinstance(result, dict) and result.get("source") == "scraping_web":
            result["voitures"] = [sanitize_car_listing(c, c.get("url_source", "")) for c in result.get("voitures", [])]
        span.finish("ok")
        return json.dumps(result, ensure_ascii=False, default=str), False
    except Exception as e:
        span.finish("error", str(e))
        return json.dumps({"succes": False, "erreur": str(e)}), True


async def _execute_node(history, system_prompt, groq_client, trace):
    tools_called = []; tool_results = []; tool_errors = []
    tokens_used = 0; reply = ""

    async def _call(h):
        return await asyncio.to_thread(
            groq_client.chat.completions.create,
            # FIX : max_tokens 800→1200, temperature 0.3→0.55 pour réponses plus riches
            model=settings.groq_model, max_tokens=500, temperature=0.2,
            tools=TOOLS_DEFINITION, tool_choice="auto",
            # FIX : trim_history avec budget plus large (6000 tokens) pour ne pas perdre le contexte
            messages=[{"role": "system", "content": system_prompt}, *trim_history(h, max_tokens=600)])

    working = list(history)
    for _ in range(settings.agent_max_iterations):
        span = trace.new_span("llm:turn")
        try:
            response = await cb_groq.call(with_retry(lambda h=working: _call(h), max_retries=3, base_delay=1.0))
            span.finish("ok")
        except Exception as e:
            span.finish("error", str(e)); raise
        tokens_used += response.usage.total_tokens if response.usage else 0
        msg = response.choices[0].message
        tcs = getattr(msg, "tool_calls", None)
        entry = {"role": "assistant", "content": msg.content or ""}
        if tcs:
            entry["tool_calls"] = [{"id": tc.id, "type": "function",
                "function": {"name": tc.function.name, "arguments": tc.function.arguments}} for tc in tcs]
        working.append(entry)
        if not tcs:
            reply = msg.content or ""
            break
        results = await asyncio.gather(*[
            execute_tool(tc.function.name, json.loads(tc.function.arguments) if tc.function.arguments else {}, trace)
            for tc in tcs])
        for tc, (rs, err) in zip(tcs, results):
            log.info(f"[TOOL] {tc.function.name} → {rs[:120]}")
            working.append({"role": "tool", "tool_call_id": tc.id,
                "content": rs[:3000] + ("..." if len(rs) > 3000 else "")})
            tools_called.append({"name": tc.function.name, "args": tc.function.arguments})
            tool_results.append(rs[:500])
            if err: tool_errors.append({"tool": tc.function.name, "error": rs[:200]})
    history.clear(); history.extend(working)
    return reply, tools_called, tool_results, tool_errors, tokens_used


def _looks_like_fake_reservation(reply: str, tools_called: list) -> bool:
    names = {t.get("name") for t in (tools_called or [])}
    if "reserver_voiture" in names:
        return False
    if "RES-XXXXXX" in reply or "#{RES-" in reply:
        return True
    low = reply.lower()
    return ("dossier #" in low or "bien enregistr" in low) and "res-" in low


def make_replay_fn(groq_client, trace):
    async def replay_fn(history, system_prompt):
        r, tc, tr, _, __ = await _execute_node(list(history), system_prompt, groq_client, trace)
        return r, tc, tr
    return replay_fn


def _parse_last_reservation_recap(history: list) -> dict | None:
    for msg in reversed(history or []):
        if msg.get("role") != "assistant":
            continue

        content = msg.get("content") or ""
        low = content.lower()
        if "voici ce que je vais réserver" not in low and "confirmez-vous" not in low:
            continue

        car = re.search(r"🚗\s*(.+?)\s*[—-]\s*(\d+(?:[.,]\d+)?)\s*TND", content)
        dates = re.search(
            r"Du\s+(\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{4})?)\s+au\s+(\d{1,2}[-/.]\d{1,2}(?:[-/.]\d{4})?)",
            content,
            re.IGNORECASE,
        )
        client = re.search(
            r"👤\s*([^·\n]+)\s*·\s*📞\s*([+\d\s-]+)\s*·\s*📧\s*([^\s\n]+)",
            content,
        )
        voiture_id = re.search(r"ID voiture\s*:\s*([A-Za-z0-9_-]+)", content, re.IGNORECASE)

        if not (car and dates and client):
            return None

        return {
            "voiture_label": car.group(1).strip(),
            "voiture_id": voiture_id.group(1).strip() if voiture_id else None,
            "prix_jour": float(car.group(2).replace(",", ".")),
            "date_debut": dates.group(1).strip(),
            "date_fin": dates.group(2).strip(),
            "client_nom": client.group(1).strip(),
            "client_tel": client.group(2).strip(),
            "client_email": client.group(3).strip(),
        }

    return None


async def _confirm_reservation_from_recap(history: list) -> str | None:
    recap = _parse_last_reservation_recap(history)
    if not recap:
        return None

    pool = await get_pool()
    if recap.get("voiture_id"):
        row = await pool.fetchrow(
            """
        SELECT id, marque, modele, prix_jour
        FROM voitures
        WHERE id = $1
          AND disponible = TRUE
          AND id NOT IN (
              SELECT voiture_id
              FROM reservations
              WHERE statut IN ('EN_ATTENTE', 'CONFIRMEE')
                AND date_debut < $3
                AND date_fin > $2
          )
        LIMIT 1
        """,
            recap["voiture_id"],
            _parse_date(recap["date_debut"]),
            _parse_date(recap["date_fin"]),
        )
    else:
        row = await pool.fetchrow(
            """
        SELECT id, marque, modele, prix_jour
        FROM voitures
        WHERE LOWER($1) LIKE '%' || LOWER(marque) || '%'
          AND LOWER($1) LIKE '%' || LOWER(modele) || '%'
          AND disponible = TRUE
          AND id NOT IN (
              SELECT voiture_id
              FROM reservations
              WHERE statut IN ('EN_ATTENTE', 'CONFIRMEE')
                AND date_debut < $3
                AND date_fin > $2
          )
        ORDER BY note_client DESC, nb_reservations DESC
        LIMIT 1
        """,
            recap["voiture_label"],
            _parse_date(recap["date_debut"]),
            _parse_date(recap["date_fin"]),
        )
    if not row:
        return "Je n'arrive pas à retrouver cette voiture dans la base. Pouvez-vous refaire la sélection ?"

    result = await reserver_voiture_fn(
        voiture_id=row["id"],
        client_nom=recap["client_nom"],
        client_tel=recap["client_tel"],
        client_email=recap["client_email"],
        date_debut=recap["date_debut"],
        date_fin=recap["date_fin"],
    )

    if not result.get("succes"):
        return f"Désolée, je n'ai pas pu enregistrer la réservation : {result.get('erreur', 'erreur inconnue')}"

    rid = result["reservation_id"]
    return (
        f"C'est parti ! ✅ Votre dossier #{rid} est bien enregistré !\n"
        f"Le propriétaire va valider dans les 24h et vous recevrez un email de confirmation. "
        f"Pour annuler à tout moment, dites-moi juste 'annuler {rid}'. À bientôt sur la route 😊 !"
    )


async def run_agent(user_message: str, session_id: str = "default") -> tuple[str, int]:
    groq_client = Groq(api_key=settings.groq_api_key)
    pool = await get_pool()
    trace = AgentTrace(session_id=session_id, user_message=user_message)
    start_ms = int(time.time() * 1000)
    reply = ""; tokens_used = 0; guard_blocked = False; guard_score = 0.0
    tools_called = []; tool_results = []; tool_errors = []
    reflection_triggered = False; correction_applied = False; episodic_hits = 0
    error_str = None; intention = IntentionClient.INCONNU

    try:
        # ── NŒUD 1 : GUARD ────────────────────────────────────────────────
        gs = trace.new_span("guard:input")
        is_safe, guard_score, guard_reason = await input_guard(user_message, groq_client)
        gs.finish("ok" if is_safe else "error", guard_reason)
        if not is_safe:
            guard_blocked = True
            reply = "Je ne peux pas traiter cette demande. Avez-vous une question sur la location de voitures ?"
            agent_metrics.record_turn(int(time.time()*1000)-start_ms, 0, False, True, 0, 0, False)
            return reply, 0

        # ── NŒUD 2 : PLAN ─────────────────────────────────────────────────
        ps = trace.new_span("plan")
        intention_t   = asyncio.create_task(detect_intention(user_message, groq_client))
        profile_db_t  = asyncio.create_task(get_client_profile(pool, session_id))
        history_t     = asyncio.create_task(get_history(session_id))
        lessons_t     = asyncio.create_task(recall_lessons(user_message, top_k=3))
        episodic_t    = asyncio.create_task(recall_episodic(session_id, user_message, top_k=4))
        extract_t     = asyncio.create_task(extract_profile(user_message, groq_client))

        (intention, conf), profil_db, history, lessons, episodes, profil_message = \
            await asyncio.gather(intention_t, profile_db_t, history_t, lessons_t, episodic_t, extract_t)
        
        if is_reservation_confirmation(user_message) and history_has_reservation_recap(history):
            direct_reply = await _confirm_reservation_from_recap(history)
            if direct_reply:
                reply = direct_reply
                tools_called = [{"name": "reserver_voiture", "args": "direct_confirmation_from_recap"}]
                history.append({"role": "user", "content": user_message})
                history.append({"role": "assistant", "content": reply})
                await set_history(session_id, history)
                return reply, 0
            
        episodic_hits = len(episodes)
        ps.finish("ok")
        log.info(f"[PLAN] {intention.value} ({conf:.0%}) | episodes={episodic_hits}")

        # ── FUSION profil DB + infos extraites du message courant ─────────
        # FIX CRITIQUE : les dates du message courant (profil_message) sont fusionnées
        # EN PREMIER — elles ont priorité sur le profil DB qui ne stocke pas les dates.
        profil_fusionné = dict(profil_db)
        if profil_message:
            msg_data = profil_message.model_dump(exclude_none=True)
            for k, v in msg_data.items():
                if v is not None:
                    # Pour les dates : toujours prendre le message courant (plus récent)
                    if k in ("dates_debut", "dates_fin"):
                        profil_fusionné[k] = v
                    # Pour les autres champs : ne pas écraser ce qui existe déjà en DB
                    elif not profil_fusionné.get(k):
                        profil_fusionné[k] = v

        if is_reservation_confirmation(user_message) and history_has_reservation_recap(history):
            intention = IntentionClient.RESERVATION
            conf = max(conf, 0.95)
            log.info("[PLAN] Confirmation récap détectée → forcer reserver_voiture")

        plan = build_task_plan(intention, profil_fusionné, user_message)
        if is_reservation_confirmation(user_message) and history_has_reservation_recap(history):
            plan.needs_reservation = True
            plan.missing_fields = []
        system_prompt = build_focused_system_prompt(
            SYSTEM_PROMPT_BASE, plan,
            format_episodic_context(episodes),
            format_lessons_context(lessons),
            profil_vers_contexte(profil_fusionné))
        history.append({"role": "user", "content": user_message})

        # ── NŒUD 3 : EXECUTE ──────────────────────────────────────────────
        es = trace.new_span("execute")
        try:
            reply, tools_called, tool_results, tool_errors, tokens_used = \
                await _execute_node(history, system_prompt, groq_client, trace)
            if _looks_like_fake_reservation(reply, tools_called):
                log.warning("[AGENT] Confirmation sans reserver_voiture — replay forcé")
                while history and history[-1].get("role") in ("tool", "assistant"):
                    history.pop()
                forced_prompt = system_prompt + (
                    "\n\n[FOCUS CRITIQUE — REPLAY] Ta réponse précédente était INVALIDE : "
                    "tu as confirmé sans appeler reserver_voiture. "
                    "APPELLE reserver_voiture MAINTENANT avec les données du récap, "
                    "puis affiche le vrai reservation_id retourné par l'outil."
                )
                reply, tools_called, tool_results, tool_errors, extra_tokens = \
                    await _execute_node(history, forced_prompt, groq_client, trace)
                tokens_used += extra_tokens
            es.finish("ok")
        except RuntimeError as e:
            es.finish("error", str(e)); error_str = str(e)
            reply = "Notre service est momentanément surchargé. Réessayez dans quelques secondes 🙏"
        except Exception as e:
            es.finish("error", str(e)); error_str = str(e)
            err = str(e)
            if "429" in err:
                m = re.search(r"try again in ([\w.]+)", err, re.IGNORECASE)
                reply = f"Beaucoup de demandes en ce moment !{' Réessayez dans '+m.group(1)+'.' if m else ''}"
            else:
                reply = "Erreur technique momentanée — réessayez dans quelques secondes."
        if not reply:
            reply = "Désolée, je n'ai pas pu traiter votre demande. Réessayez !"

        # ── NŒUD 4 : REFLECT ──────────────────────────────────────────────
        if not error_str:
            rs = trace.new_span("reflect")
            reply_raw, reflection_triggered, correction_applied, _ = await reflexion_loop(
                user_message=user_message, agent_reply=reply,
                tools_called=tools_called, tool_results=tool_results,
                history=history, system_prompt=system_prompt,
                groq_client=groq_client, replay_fn=make_replay_fn(groq_client, trace), max_replays=1)

            rs.finish("ok")
            reply = str(reply_raw) if not isinstance(reply_raw, str) else reply_raw

        reply = reply if isinstance(reply, str) else str(reply)
        reply, out_warnings = output_guard(reply, session_id)
        if out_warnings: log.warning(f"[OUTPUT GUARD] {out_warnings}")

        # ── NŒUD 5 : MEMORIZE ─────────────────────────────────────────────
        async def _upd_profile():
            if profil_message:
                await update_client_profile(pool, session_id, profil_message)

        async def _store_ep():
            # FIX : ne stocker en mémoire épisodique que les tours significatifs
            # pour ne pas polluer le contexte avec des échanges de slot-filling
            has_reservation = any(t.get("name") == "reserver_voiture" for t in tools_called)
            has_error = bool(error_str or tool_errors)
            importance = await compute_episode_importance(tools_called, has_reservation, has_error)
            # Ignorer les tours sans outils ET de faible importance (simples Q/R de collecte)
            if not tools_called and importance < 0.5:
                return
            summary = await summarize_episode(user_message, reply, tools_called, groq_client)
            await store_episodic(
                session_id=session_id, content=summary, importance=importance,
                metadata={"intention": intention.value,
                          "tools": [t.get("name") for t in tools_called],
                          "had_error": bool(error_str)})

        async def _save_history():
            # FIX : logger explicitement si set_history échoue pour détecter les pertes de contexte
            try:
                await set_history(session_id, history)
            except Exception as e:
                log.error(f"[AGENT] set_history ÉCHEC pour {session_id} — contexte perdu : {e}")

        await asyncio.gather(_upd_profile(), _store_ep(), _save_history(),
                             return_exceptions=True)

    except Exception as e:
        error_str = str(e); log.error(f"[AGENT] Erreur : {e}")
        reply = "Erreur technique momentanée — réessayez dans quelques secondes."

    finally:
        latency_ms = int(time.time()*1000) - start_ms
        agent_metrics.record_turn(latency_ms, tokens_used, reflection_triggered, guard_blocked,
                                   len(tools_called), len(tool_errors), bool(error_str))
        asyncio.create_task(persist_trace(
            session_id=session_id, trace_id=trace.trace_id,
            user_message=user_message, assistant_reply=reply, intention=intention.value,
            tools_called=tools_called, tool_errors=tool_errors,
            reflection_triggered=reflection_triggered, correction_applied=correction_applied,
            guard_blocked=guard_blocked, guard_score=guard_score,
            tokens_used=tokens_used, latency_ms=latency_ms, model_used=settings.groq_model,
            episodic_hits=episodic_hits, error=error_str, spans=trace.spans))
        log.info(f"[AGENT] {session_id} | {intention.value} | tools={len(tools_called)} | {latency_ms}ms")

    return str(reply), tokens_used