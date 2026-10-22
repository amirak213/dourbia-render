"""
api/routes.py — Routes FastAPI v8.

Nouveautés vs v7 :
  - /metrics   endpoint Prometheus-compatible
  - /health    health check détaillé (DB + Redis + pgvector + circuit breakers)
  - /api/memory   inspecter mémoire épisodique (admin)
  - /api/lessons  inspecter mémoire procédurale (admin)
  - /api/circuit_breakers  état des circuit breakers (admin)
"""

from __future__ import annotations

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from core.config import settings
from core.database import init_db
from core.infra import (
    close_pool, close_redis, get_pool, get_redis,
    record_to_dict, cb_groq, cb_scraping, cb_guard,
)
from core.types import ChatRequest, WeatherAlertRequest
from agents.agent import run_agent
from agents.tools import consulter_reservations, statistiques_flotte
from observability.tracing import agent_metrics
from scheduler.scheduler import scheduler_loop

log = logging.getLogger("dourbia.api")
limiter = Limiter(key_func=get_remote_address)


# ══════════════════════════════════════════════════════════════
# AUTH
# ══════════════════════════════════════════════════════════════

async def require_admin(x_api_key: str = Header(default="")):
    if not settings.admin_api_key:
        raise HTTPException(503, detail="ADMIN_API_KEY non configurée.")
    if x_api_key != settings.admin_api_key:
        raise HTTPException(401, detail="Clé API invalide.")


# ══════════════════════════════════════════════════════════════
# LIFESPAN
# ══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    log.info("[STARTUP] Initialisation Dourbia v8...")
    try:
        await init_db()
        await get_redis()
    except Exception as e:
        log.exception(f"[STARTUP] Échec initialisation DB ou Redis : {e}")

    try:
        from memory.memory_manager import _get_embedding_model
        await _get_embedding_model()
        log.info("[STARTUP] SentenceTransformer prêt.")
    except Exception:
        log.exception("[STARTUP] Échec préchargement embeddings — première requête sera lente")

    asyncio.create_task(scheduler_loop())

    try:
        stats = await statistiques_flotte()
        log.info(
            f"[STARTUP] Prêt — {stats['total_vehicules']} véhicules "
            f"({stats['disponibles']} disponibles) | "
            f"villes: {', '.join(stats.get('villes', []))}"
        )
    except Exception as e:
        log.warning(f"[STARTUP] Impossible de charger les stats de la flotte : {e}")

    yield
    await close_pool()
    await close_redis()
    log.info("[SHUTDOWN] Propre.")


# ══════════════════════════════════════════════════════════════
# APP
# ══════════════════════════════════════════════════════════════


app = FastAPI(title="Dourbia Agent Yasmine v8.0", version="8.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins if hasattr(settings, "allowed_origins") else ["*"],  # FIX : restreindre en prod via ALLOWED_ORIGINS env var
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization", "X-API-Key"],
)


# ══════════════════════════════════════════════════════════════
# ROUTES PUBLIQUES
# ══════════════════════════════════════════════════════════════

@app.get("/")
async def index():
    stats = await statistiques_flotte()
    return {
        "status": "ok", "version": "8.0-pgvector-reflexion",
        "vehicules": stats["total_vehicules"], "disponibles": stats["disponibles"],
    }


@app.get("/health")
async def health():
    checks = {}
    try:
        pool = await get_pool()
        await pool.fetchval("SELECT 1")
        checks["db"] = "ok"
    except Exception as e:
        checks["db"] = f"error: {e}"

    try:
        r = await get_redis()
        result = r.ping()
        if asyncio.iscoroutine(result):
            await result

        checks["redis"] = "ok"
    except Exception as e:
        checks["redis"] = f"error: {e}"

    try:
        pool = await get_pool()
        await pool.fetchval("SELECT '[1,2,3]'::vector <=> '[1,2,3]'::vector")
        checks["pgvector"] = "ok"
    except Exception as e:
        checks["pgvector"] = f"unavailable: {e}"

    checks["circuit_breakers"] = {
        "groq":     cb_groq.state.value,
        "scraping": cb_scraping.state.value,
        "guard":    cb_guard.state.value,
    }
    overall = "ok" if checks["db"] == "ok" and checks["redis"] == "ok" else "degraded"
    return JSONResponse(
        {"status": overall, "checks": checks, "metrics": agent_metrics.to_dict()},
        status_code=200 if overall == "ok" else 207,
    )


@app.get("/metrics", response_class=PlainTextResponse)
async def prometheus_metrics():
    cb_lines = "\n".join([
        f'dourbia_circuit_open{{name="{cb.name}"}} {1 if cb.state.value == "open" else 0}'
        for cb in [cb_groq, cb_scraping, cb_guard]
    ])
    return agent_metrics.to_prometheus() + "\n" + cb_lines


@app.post("/chat")
@limiter.limit("30/minute")
async def chat_endpoint(request: Request, body: ChatRequest):
    reply, tokens = await run_agent(body.message, body.session_id)
    return {"reply": reply, "tokens_used": tokens}


@app.get("/ui", response_class=HTMLResponse)
async def frontend():
    import os
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend.html")
    try:
        with open(path, encoding="utf-8") as f:
            return HTMLResponse(content=f.read())
    except FileNotFoundError:
        return HTMLResponse("<h1>frontend.html introuvable — place le fichier à la racine</h1>", 404)


# ══════════════════════════════════════════════════════════════
# ROUTES ADMIN
# ══════════════════════════════════════════════════════════════

@app.get("/api/reservations")
async def api_reservations(_=Depends(require_admin)):
    return (await consulter_reservations())["reservations"]


@app.get("/api/flotte")
async def api_flotte():
    return await statistiques_flotte()


@app.get("/api/traces")
async def api_traces(session_id: str | None = None, _=Depends(require_admin)):
    pool = await get_pool()
    if session_id:
        rows = await pool.fetch(
            "SELECT * FROM agent_traces WHERE session_id=$1 ORDER BY created_at DESC LIMIT 50",
            session_id,
        )
    else:
        rows = await pool.fetch("SELECT * FROM agent_traces ORDER BY created_at DESC LIMIT 100")
    return [record_to_dict(r) for r in rows]


@app.get("/api/memory")
async def api_memory(session_id: str, _=Depends(require_admin)):
    """Inspecter la mémoire épisodique vectorielle d'une session."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT id, content, importance, metadata, access_count, created_at
        FROM episodic_memory WHERE session_id=$1
        ORDER BY importance DESC, created_at DESC LIMIT 50
    """, session_id)
    return [record_to_dict(r) for r in rows]


@app.get("/api/lessons")
async def api_lessons(_=Depends(require_admin)):
    """Inspecter les leçons apprises (mémoire procédurale Reflexion)."""
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT id, trigger_pattern, lesson, error_type, applied_count, success_rate, created_at
        FROM procedural_memory ORDER BY applied_count DESC, created_at DESC LIMIT 100
    """)
    return [record_to_dict(r) for r in rows]


@app.get("/api/circuit_breakers")
async def api_circuit_breakers(_=Depends(require_admin)):
    return {
        "groq":     cb_groq.get_metrics(),
        "scraping": cb_scraping.get_metrics(),
        "guard":    cb_guard.get_metrics(),
    }


@app.get("/api/rebooking_suggestions")
async def api_rebooking(statut: str | None = None, _=Depends(require_admin)):
    pool = await get_pool()
    if statut:
        rows = await pool.fetch(
            "SELECT * FROM rebooking_suggestions WHERE statut=$1 ORDER BY created_at DESC LIMIT 50",
            statut.upper(),
        )
    else:
        rows = await pool.fetch(
            "SELECT * FROM rebooking_suggestions ORDER BY created_at DESC LIMIT 100"
        )
    return [record_to_dict(r) for r in rows]


@app.post("/api/weather_alert")
async def recevoir_alerte_meteo(body: WeatherAlertRequest, _=Depends(require_admin)):
    pool = await get_pool()
    alert_id = await pool.fetchval("""
        INSERT INTO weather_alerts (ville, date_debut, date_fin, severite, message, source)
        VALUES ($1,$2,$3,$4,$5,$6) RETURNING id
    """,
        body.ville,
        datetime.strptime(body.date_debut, "%Y-%m-%d").date(),
        datetime.strptime(body.date_fin,   "%Y-%m-%d").date(),
        body.severite.value,
        body.message,
        body.source,
    )
    log.info(f"[METEO] Alerte {body.severite.value} {body.ville} | id={alert_id}")
    return {"status": "ok", "alert_id": str(alert_id)}


# ══════════════════════════════════════════════════════════════
# PAGES HTML : CONFIRMATION / REFUS / ANNULATION
# ══════════════════════════════════════════════════════════════

def _html_page(titre: str, couleur: str, message: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Dourbia - {titre}</title>
<style>body{{font-family:Arial,sans-serif;background:#0e0e12;color:#e8e4d8;
display:flex;align-items:center;justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;
padding:40px;max-width:480px;width:90%;text-align:center}}
h2{{color:{couleur};font-size:22px;margin-bottom:12px}}p{{color:#8a8578;font-size:14px;line-height:1.7}}
a.btn{{display:inline-block;background:linear-gradient(135deg,#8a6f32,#c9a84c);color:#0e0e12;
padding:10px 24px;border-radius:8px;text-decoration:none;font-weight:bold;margin-top:20px}}
</style></head><body><div class="card"><h2>{titre}</h2><p>{message}</p>
<a href="/" class="btn">Retour</a></div></body></html>"""


@app.get("/confirmer/{token}", response_class=HTMLResponse)
async def confirmer(token: str):
    pool = await get_pool()
    row  = await pool.fetchrow(
        "SELECT reservation_id FROM tokens_confirmation WHERE token=$1 AND expires_at > NOW()", token
    )
    if not row:
        return HTMLResponse(_html_page("Lien invalide", "#e74c3c", "Ce lien est invalide ou expiré."), 404)
    r = await pool.fetchrow("SELECT * FROM reservations WHERE id=$1", row["reservation_id"])
    if not r:
        return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
    rv = record_to_dict(r)
    if rv["statut"] != "EN_ATTENTE":
        return HTMLResponse(_html_page("Déjà traitée", "#e8b86d", f"Statut : {rv['statut']}."), 200)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE reservations SET statut='CONFIRMEE', updated_at=NOW() WHERE id=$1", rv["id"]
            )
            await conn.execute("""
                UPDATE voitures SET disponible = FALSE, updated_at = NOW()
                WHERE id = $1 AND EXISTS (
                    SELECT 1 FROM reservations
                    WHERE id = $2 AND date_debut <= CURRENT_DATE AND date_fin >= CURRENT_DATE
                )
            """, rv["voiture_id"], rv["id"])
            await conn.execute("DELETE FROM tokens_confirmation WHERE token=$1", token)

    token_annul = secrets.token_urlsafe(32)
    expires_at  = datetime.utcnow() + timedelta(hours=settings.token_expiry_hours)
    await pool.execute(
        "INSERT INTO tokens_annulation (token, reservation_id, expires_at) VALUES ($1,$2,$3)",
        token_annul, rv["id"], expires_at,
    )
    try:
        from email_service import envoyer_email_confirmation_client
        envoyer_email_confirmation_client(rv, token_annulation=token_annul)
    except Exception as e:
        log.warning(f"[EMAIL] confirmation : {e}")
    log.info(f"[CONFIRM] {rv['id']} confirmée")
    return HTMLResponse(_html_page(
        "Réservation confirmée ✅", "#27ae60",
        f"La réservation <b>{rv['id']}</b> est confirmée.<br>Email envoyé au client.",
    ), 200)

def escape_html(text: str) -> str:
    return (str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;"))

@app.get("/refuser/{token}", response_class=HTMLResponse)
async def refuser(token: str):
    pool = await get_pool()
    row  = await pool.fetchrow(
        "SELECT reservation_id FROM tokens_confirmation WHERE token=$1 AND expires_at > NOW()", token
    )
    if not row:
        return HTMLResponse(_html_page("Lien invalide", "#e74c3c", "Lien invalide ou expiré."), 404)
    r = await pool.fetchrow("SELECT * FROM reservations WHERE id=$1", row["reservation_id"])
    if not r:
        return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
    rv  = record_to_dict(r)
    if rv["statut"] != "EN_ATTENTE":
        return HTMLResponse(_html_page("Déjà traitée", "#e8b86d", f"Statut : {rv['statut']}"), 200)
    # FIX XSS : échapper toutes les variables DB avant injection dans le HTML
    rid = escape_html(rv.get("id","")); vehicule = escape_html(rv.get("voiture_details","")); client_n = escape_html(rv.get("client_nom",""))
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Dourbia - Refuser</title>
<style>body{{font-family:Arial;background:#0e0e12;color:#e8e4d8;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;padding:40px;max-width:520px;width:90%}}
h2{{color:#e74c3c}}.info{{background:#12121a;border-radius:8px;padding:12px;margin-bottom:20px;font-size:14px;color:#aaa;line-height:1.8}}
select,textarea{{width:100%;padding:10px;border-radius:6px;border:1px solid #3a3a4a;background:#12121a;
color:#e8e4d8;font-size:14px;box-sizing:border-box;margin-bottom:16px}}textarea{{height:100px;resize:vertical}}
.btn{{background:#e74c3c;color:white;border:none;padding:12px 28px;border-radius:6px;font-weight:bold;cursor:pointer;font-size:15px;width:100%}}</style></head>
<body><div class="card"><h2>Refuser la demande</h2>
<div class="info"><b>Ref :</b> {rid}<br><b>Client :</b> {client_n}<br><b>Véhicule :</b> {vehicule}</div>
<form method="POST" action="/refuser_confirmer/{token}">
<select name="raison_type">
<option value="La voiture n'est pas disponible aux dates sélectionnées.">Voiture non disponible</option>
<option value="Le véhicule est en cours de maintenance.">En maintenance</option>
<option value="Les documents fournis sont incomplets.">Documents incomplets</option>
<option value="La demande ne respecte pas nos conditions.">Non-respect des conditions</option>
</select>
<textarea name="raison_custom" placeholder="Précision optionnelle..."></textarea>
<button type="submit" class="btn">Confirmer le refus</button>
</form></div></body></html>""")


@app.post("/refuser_confirmer/{token}", response_class=HTMLResponse)
async def refuser_confirmer(token: str, request: Request):
    pool = await get_pool()
    row  = await pool.fetchrow(
        "SELECT reservation_id FROM tokens_confirmation WHERE token=$1 AND expires_at > NOW()", token
    )
    if not row:
        return HTMLResponse(_html_page("Lien invalide", "#e74c3c", "Lien invalide ou expiré."), 404)
    r = await pool.fetchrow("SELECT * FROM reservations WHERE id=$1", row["reservation_id"])
    if not r:
        return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
    rv = record_to_dict(r)
    if rv["statut"] != "EN_ATTENTE":
        return HTMLResponse(_html_page("Déjà traitée", "#e8b86d", f"Statut : {rv['statut']}"), 200)
    form   = await request.form()
    raison_custom = form.get("raison_custom")
    raison_type = form.get("raison_type")
    raison: str = (
        str(raison_custom).strip() if isinstance(raison_custom, str) and raison_custom.strip()
        else str(raison_type) if isinstance(raison_type, str)
        else ""
    )
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.execute(
                "UPDATE reservations SET statut='REFUSEE', raison_refus=$1, updated_at=NOW() WHERE id=$2",
                raison, rv["id"],
            )
            await conn.execute("DELETE FROM tokens_confirmation WHERE token=$1", token)
            await conn.execute("DELETE FROM tokens_annulation WHERE reservation_id=$1", rv["id"])
    try:
        from email_service import envoyer_email_refus_client
        envoyer_email_refus_client(rv, raison)
    except Exception as e:
        log.warning(f"[EMAIL] refus : {e}")
    log.info(f"[REFUS] {rv['id']}")
    return HTMLResponse(_html_page(
        "Demande refusée", "#e74c3c",
        f"<b>{rv['id']}</b> refusée.<br>Client informé par email.",
    ), 200)


@app.get("/annuler_client/{token}", response_class=HTMLResponse)
async def annuler_client_lien(token: str):
    pool = await get_pool()
    row  = await pool.fetchrow(
        "SELECT reservation_id FROM tokens_annulation WHERE token=$1 AND expires_at > NOW()", token
    )
    if not row:
        return HTMLResponse(_html_page("Lien invalide", "#e74c3c", "Lien invalide ou expiré."), 404)
    r = await pool.fetchrow("SELECT * FROM reservations WHERE id=$1", row["reservation_id"])
    if not r:
        return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
    rv    = record_to_dict(r)
    if rv["statut"] == "ANNULEE":
        return HTMLResponse(_html_page("Déjà annulée", "#e8b86d", f"<b>{rv['id']}</b> déjà annulée."), 200)
    rid   = rv.get("id",""); vehicule = rv.get("voiture_details","")
    d1    = str(rv.get("date_debut","")); d2 = str(rv.get("date_fin",""))
    prix  = rv.get("prix_total",""); statut = rv.get("statut","")
    badge = "#27ae60" if statut == "CONFIRMEE" else "#e8b86d"
    return HTMLResponse(f"""<!DOCTYPE html>
<html lang="fr"><head><meta charset="UTF-8"><title>Dourbia - Annuler</title>
<style>body{{font-family:Arial;background:#0e0e12;color:#e8e4d8;display:flex;align-items:center;
justify-content:center;min-height:100vh;margin:0}}
.card{{background:#1a1a24;border:1px solid #2a2a38;border-radius:12px;padding:40px;max-width:500px;width:90%;text-align:center}}
h2{{color:#e74c3c}}.info{{background:#12121a;border-radius:8px;padding:14px;margin:16px 0;font-size:14px;line-height:1.9;text-align:left}}
.warn{{background:#2a1a1a;border-left:4px solid #e74c3c;padding:12px;margin:16px 0;border-radius:4px;font-size:13px;color:#f0a0a0;text-align:left}}
.status{{display:inline-block;padding:4px 12px;border-radius:20px;font-size:12px;font-weight:bold;background:{badge};color:#000;margin-bottom:10px}}
.btn-c{{background:#e74c3c;color:white;border:none;padding:12px 28px;border-radius:6px;font-weight:bold;cursor:pointer;font-size:15px;text-decoration:none;display:inline-block;margin:8px}}
.btn-k{{background:#2d2d4e;color:#e8b86d;border:2px solid #e8b86d;padding:12px 28px;border-radius:6px;font-weight:bold;text-decoration:none;display:inline-block;margin:8px}}</style></head>
<body><div class="card"><div style="font-size:48px">⚠️</div><h2>Annuler ma réservation ?</h2>
<span class="status">{statut}</span>
<div class="info"><b>Dossier :</b> {rid}<br><b>Véhicule :</b> {vehicule}<br><b>Période :</b> {d1} → {d2}<br><b>Total :</b> {prix} TND</div>
<div class="warn">⚠️ Action <b>irréversible</b>.</div>
<form method="POST" action="/annuler_client_confirmer/{token}">
<a href="{settings.chatbot_url}" class="btn-k">← Garder ma réservation</a>
<button type="submit" class="btn-c">Confirmer l'annulation</button>
</form></div></body></html>""")


@app.post("/annuler_client_confirmer/{token}", response_class=HTMLResponse)
async def annuler_client_confirmer(token: str):
    pool = await get_pool()
    row  = await pool.fetchrow(
        "SELECT reservation_id FROM tokens_annulation WHERE token=$1 AND expires_at > NOW()", token
    )
    if not row:
        return HTMLResponse(_html_page("Lien invalide", "#e74c3c", "Lien invalide ou expiré."), 404)
    async with pool.acquire() as conn:
        async with conn.transaction():
            r = await conn.fetchrow(
                "SELECT * FROM reservations WHERE id=$1 FOR UPDATE", row["reservation_id"]
            )
            if not r:
                return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
            rv = record_to_dict(r)
            if rv["statut"] in ("ANNULEE", "REFUSEE"):
                return HTMLResponse(_html_page("Déjà traitée","#e8b86d",f"Statut : <b>{rv['statut']}</b>."), 200)
            await conn.execute(
                "UPDATE reservations SET statut='ANNULEE', updated_at=NOW() WHERE id=$1", rv["id"]
            )
            await conn.execute("""
                UPDATE voitures SET disponible = TRUE, updated_at = NOW()
                WHERE id = $1 AND disponible = FALSE AND NOT EXISTS (
                    SELECT 1 FROM reservations
                    WHERE voiture_id = $1 AND statut = 'CONFIRMEE' AND id != $2
                      AND date_debut <= CURRENT_DATE AND date_fin >= CURRENT_DATE
                )
            """, rv["voiture_id"], rv["id"])
            await conn.execute("DELETE FROM tokens_annulation WHERE token=$1", token)
            await conn.execute("DELETE FROM tokens_confirmation WHERE reservation_id=$1", rv["id"])
    try:
        from email_service import envoyer_email_annulation_client
        envoyer_email_annulation_client(rv, source="client")
    except Exception as e:
        log.warning(f"[EMAIL] annulation : {e}")
    log.info(f"[ANNUL_CLIENT] {rv['id']} annulée via lien")
    return HTMLResponse(_html_page(
        "Réservation annulée", "#e8b86d",
        f"<b>{rv['id']}</b> annulée.<br>"
        f'<a href="{settings.chatbot_url}" style="color:#e8b86d">Nouvelle réservation →</a>',
    ), 200)


@app.get("/feedback/{reservation_id}", response_class=HTMLResponse)
async def feedback(reservation_id: str, note: int = 0):
    if not 1 <= note <= 5:
        return HTMLResponse(_html_page("Note invalide", "#e74c3c", "Note invalide (1-5)."), 400)
    pool = await get_pool()
    r    = await pool.fetchrow("SELECT * FROM reservations WHERE id=$1", reservation_id)
    if not r:
        return HTMLResponse(_html_page("Introuvable", "#e74c3c", "Réservation introuvable."), 404)
    rv = record_to_dict(r)
    await pool.execute(
        "UPDATE reservations SET note_feedback=$1, date_feedback=NOW() WHERE id=$2", note, reservation_id
    )
    if note <= 2:
        try:
            from email_service import email_svc
            email_svc.alerte_feedback_negatif(rv, note)
        except Exception as e:
            log.warning(f"[EMAIL] feedback négatif : {e}")
    etoiles = "⭐" * note
    msgs = {5:("Merci ! 🎉","Votre enthousiasme nous touche."),4:("Merci ! 😊","Ravi que tout se soit bien passé."),
            3:("Merci.","Nous prenons note."),2:("Merci.","Nous allons faire mieux."),
            1:("Désolés.","Nous traitons ce problème en priorité.")}
    titre, corps = msgs[note]
    return HTMLResponse(_html_page(titre, "#e8b86d", f"{etoiles}<br><br>{corps}"), 200)
