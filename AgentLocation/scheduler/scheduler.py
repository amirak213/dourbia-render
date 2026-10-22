"""
scheduler/scheduler.py — Scheduler async v8.

Tâches horaires :
  1. Rappel J-1 client
  2. Feedback J+1 client
  3. Relance propriétaire après N heures
  4. Checker meilleures offres (rebooking)
  5. Coordination alertes météo → réservations
  6. Nettoyage tokens expirés
  7. NOUVEAU v8 : LLM-as-judge sur échantillon de traces
  8. NOUVEAU v8 : Nettoyage mémoire épisodique expirée
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from datetime import date as _date, datetime, timedelta

from core.config import settings
from core.infra import get_pool, record_to_dict
from agents.tools import rechercher_voitures

log = logging.getLogger("dourbia.scheduler")


def _parse_date(s) -> _date:
    if isinstance(s, _date):
        return s
    return datetime.strptime(str(s).strip(), "%Y-%m-%d").date()


def _norm(s: str) -> str:
    return unicodedata.normalize("NFD", s.lower()).encode("ascii", "ignore").decode("ascii")


async def _tache_rappels(pool, today: _date, demain: _date):
    rows = await pool.fetch("""
        SELECT * FROM reservations
        WHERE statut='CONFIRMEE' AND rappel_envoye=FALSE AND date_debut=$1
    """, demain)
    for r in rows:
        rv = record_to_dict(r)
        try:
            from email_service import envoyer_email_rappel_client
            envoyer_email_rappel_client(rv)
        except Exception as e:
            log.warning(f"[SCHEDULER] rappel email : {e}")
        await pool.execute(
            "UPDATE reservations SET rappel_envoye=TRUE, updated_at=NOW() WHERE id=$1", rv["id"]
        )
        log.info(f"[RAPPEL] {rv['id']} → {rv.get('client_email','')}")


async def _tache_feedback(pool, today: _date):
    rows = await pool.fetch("""
        SELECT * FROM reservations
        WHERE statut='CONFIRMEE' AND feedback_envoye=FALSE AND date_fin < $1
    """, today)
    for r in rows:
        rv = record_to_dict(r)
        try:
            from email_service import envoyer_email_feedback_client
            envoyer_email_feedback_client(rv)
        except Exception as e:
            log.warning(f"[SCHEDULER] feedback email : {e}")
        await pool.execute(
            "UPDATE reservations SET feedback_envoye=TRUE, updated_at=NOW() WHERE id=$1", rv["id"]
        )


async def _tache_relance_proprietaire(pool):
    rows = await pool.fetch(f"""
        SELECT r.*, t.token FROM reservations r
        LEFT JOIN tokens_confirmation t ON t.reservation_id=r.id
        WHERE r.statut='EN_ATTENTE'
          AND r.rappel_proprietaire_envoye=FALSE
          AND r.date_reservation < NOW() - INTERVAL '{settings.delai_relance_proprietaire_h} hours'
    """)
    for r in rows:
        rv = record_to_dict(r)
        if rv.get("token"):
            try:
                from email_service import envoyer_email_relance_proprietaire
                envoyer_email_relance_proprietaire(rv, rv["token"])
            except Exception as e:
                log.warning(f"[SCHEDULER] relance email : {e}")
            await pool.execute(
                "UPDATE reservations SET rappel_proprietaire_envoye=TRUE, updated_at=NOW() WHERE id=$1",
                rv["id"]
            )


async def _tache_rebooking(pool):
    seuil_depart = (datetime.utcnow() + timedelta(hours=48)).date().isoformat()
    rows = await pool.fetch("""
        SELECT r.* FROM reservations r
        WHERE r.statut='CONFIRMEE' AND r.date_debut > $1
    """, _parse_date(seuil_depart))

    for r in rows:
        rv          = record_to_dict(r)
        rid         = rv["id"]
        prix_actuel = float(rv.get("prix_jour") or 0)
        if not prix_actuel:
            continue

        deja = await pool.fetchval("""
            SELECT COUNT(*) FROM rebooking_suggestions
            WHERE reservation_id=$1 AND statut IN ('NOTIFIEE','ACCEPTEE')
        """, rid)
        if deja:
            continue

        alternatives = await rechercher_voitures(
            ville=rv.get("voiture_ville"),
            date_debut=str(rv.get("date_debut", "")),
            date_fin=str(rv.get("date_fin", "")),
            prix_max=prix_actuel * 0.85,
            categorie=rv.get("voiture_categorie") or None,
        )
        if not alternatives.get("nombre", 0):
            continue

        meilleure = alternatives["voitures"][0]
        note_alt  = float(meilleure.get("note_client") or 0)
        economie  = round(
            (prix_actuel - float(meilleure["prix_jour"])) * int(rv.get("nb_jours") or 1), 2
        )
        if economie < 50 or note_alt < 4.0:
            continue

        suggestion_id = await pool.fetchval("""
            INSERT INTO rebooking_suggestions
                (reservation_id, voiture_alt_id, prix_actuel, prix_alt, economie_totale)
            VALUES ($1,$2,$3,$4,$5)
            ON CONFLICT DO NOTHING RETURNING id
        """, rid, meilleure["id"], prix_actuel, float(meilleure["prix_jour"]), economie)

        if not suggestion_id:
            continue

        email_envoye = False
        try:
            from email_service import email_svc
            email_envoye = email_svc.rebooking_suggestion(
                reservation=rv, voiture_alternative=meilleure, economie_totale=economie
            )
        except Exception as e:
            log.warning(f"[SCHEDULER] rebooking email : {e}")

        await pool.execute("""
            UPDATE rebooking_suggestions
            SET statut='NOTIFIEE', email_envoye=$1, notified_at=NOW() WHERE id=$2
        """, email_envoye, suggestion_id)
        log.info(f"[REBOOKING] {rid} — économie {economie} TND")


async def _tache_alertes_meteo(pool):
    alertes = await pool.fetch("""
        SELECT * FROM weather_alerts
        WHERE traitee=FALSE AND severite IN ('WARNING','CRITICAL')
          AND date_debut >= NOW()::date
        ORDER BY severite DESC, created_at ASC LIMIT 20
    """)
    for alerte in alertes:
        av    = record_to_dict(alerte)
        ville = av["ville"]
        reservations = await pool.fetch("""
            SELECT * FROM reservations
            WHERE statut='CONFIRMEE'
              AND LOWER(voiture_ville) LIKE LOWER($1)
              AND date_debut <= $2 AND date_fin >= $3
        """, f"%{_norm(ville)}%",
            _parse_date(str(av["date_fin"])),
            _parse_date(str(av["date_debut"])))

        nb = 0
        for r in reservations:
            rv = record_to_dict(r)
            if rv.get("client_email"):
                try:
                    from email_service import email_svc
                    email_svc.alerte_meteo_client(reservation=rv, alerte={
                        "ville": ville, "severite": av["severite"], "message": av["message"],
                        "date_debut": str(av["date_debut"]), "date_fin": str(av["date_fin"]),
                    })
                    nb += 1
                except Exception as e:
                    log.warning(f"[SCHEDULER] alerte meteo email : {e}")

        await pool.execute("UPDATE weather_alerts SET traitee=TRUE WHERE id=$1", av["id"])
        log.info(f"[METEO→RESA] {av['severite']} {ville} — {nb} client(s) notifié(s)")


async def _tache_nettoyage(pool):
    del_conf  = await pool.execute("DELETE FROM tokens_confirmation WHERE expires_at < NOW()")
    del_annul = await pool.execute("DELETE FROM tokens_annulation WHERE expires_at < NOW()")
    del_mem   = await pool.execute(
        "DELETE FROM episodic_memory WHERE expires_at IS NOT NULL AND expires_at < NOW()"
    )
    del_proc  = await pool.execute("""
        DELETE FROM procedural_memory
        WHERE applied_count=0 AND created_at < NOW() - INTERVAL '90 days'
    """)
    log.info(
        f"[CLEANUP] tokens_conf={del_conf} tokens_annul={del_annul} "
        f"episodic={del_mem} procedural={del_proc}"
    )


async def _tache_llm_judge(pool):
    """LLM-as-judge automatisé — détecte la dérive qualité sans intervention humaine."""
    try:
        # FIX : ne pas aggraver les problèmes Groq si le circuit est déjà ouvert
        from core.infra import cb_groq, CircuitState
        if cb_groq.state == CircuitState.OPEN:
            log.info("[SCHEDULER] LLM-judge ignoré — cb_groq OPEN")
            return

        from groq import Groq
        from observability.tracing import llm_judge_sample

        rows = await pool.fetch("""
            SELECT trace_id, session_id, user_message, assistant_reply
            FROM agent_traces
            WHERE created_at > NOW() - INTERVAL '1 hour'
              AND error IS NULL
            ORDER BY created_at DESC LIMIT 100
        """)
        if not rows:
            return

        groq_client = Groq(api_key=settings.groq_api_key)
        results     = await llm_judge_sample([record_to_dict(r) for r in rows], groq_client, sample_rate=0.10)

        if results:
            avg = sum(r.get("score_global", 0) for r in results) / len(results)
            if avg < 3.5:
                log.warning(f"[LLM-JUDGE] ⚠ Score moyen {avg:.1f}/5 — dérive qualité détectée !")
            else:
                log.info(f"[LLM-JUDGE] Score moyen {avg:.1f}/5 sur {len(results)} traces ✓")
    except Exception as e:
        log.warning(f"[LLM-JUDGE] : {e}")


async def _tache_mise_a_jour_disponibilite(pool, today: _date):
    """Mise à jour automatique de la colonne disponible de la table voitures en fonction des locations actives aujourd'hui."""
    # 1. Bloquer (disponible = FALSE) les voitures actuellement louées aujourd'hui
    await pool.execute("""
        UPDATE voitures SET disponible = FALSE, updated_at = NOW()
        WHERE disponible = TRUE AND id IN (
            SELECT voiture_id FROM reservations
            WHERE statut = 'CONFIRMEE' AND date_debut <= $1 AND date_fin >= $1
        )
    """, today)
    # 2. Libérer (disponible = TRUE) les voitures sans location active aujourd'hui (qui étaient bloquées)
    await pool.execute("""
        UPDATE voitures SET disponible = TRUE, updated_at = NOW()
        WHERE disponible = FALSE AND id NOT IN (
            SELECT voiture_id FROM reservations
            WHERE statut = 'CONFIRMEE' AND date_debut <= $1 AND date_fin >= $1
        )
    """, today)
    log.info("[SCHEDULER] Tâche mise_a_jour_disponibilite exécutée avec succès")


async def scheduler_loop():
    log.info("[SCHEDULER] Démarré — cycle toutes les heures")
    while True:
        try:
            pool   = await get_pool()
            today  = _date.today()
            demain = today + timedelta(days=1)

            tasks = [
                ("rappels",              _tache_rappels(pool, today, demain)),
                ("feedback",             _tache_feedback(pool, today)),
                ("relance_proprietaire", _tache_relance_proprietaire(pool)),
                ("rebooking",            _tache_rebooking(pool)),
                ("alertes_meteo",        _tache_alertes_meteo(pool)),
                ("nettoyage",            _tache_nettoyage(pool)),
                ("llm_judge",            _tache_llm_judge(pool)),
                ("mise_a_jour_disponibilite", _tache_mise_a_jour_disponibilite(pool, today)),
            ]
            for nom, coro in tasks:
                try:
                    await coro
                except Exception as e:
                    log.error(f"[SCHEDULER] Tâche '{nom}' : {e}")

            await asyncio.sleep(3600)

        except Exception as e:
            log.error(f"[SCHEDULER] Erreur globale : {e}")
            await asyncio.sleep(60)
