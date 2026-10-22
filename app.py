import sys
import os

sys.path.insert(
    0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "AgentPrincipal")
)
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address
from pydantic import BaseModel, Field
import uuid
from AgentPrincipal.chat import chat
from typing import TYPE_CHECKING, Optional, List, Any
from langdetect import detect_langs, DetectorFactory
from deep_translator import GoogleTranslator
from AgentPrincipal.geo_service import get_geo_service
from AgentPrincipal.orchestrateur import (
    OrchestratorAgent,
    _run_circuit_recommendation_sync,
    _load_circuit_v2_modules,
    CircuitRecommendationBusinessError,
)
from AgentPrincipal.chat import get_orchestrateur

from AgentPrincipal.session_memory import (
    get_active_circuit,
    get_profile,
    update_profile,
)

import asyncio
import re
import traceback
import time
from contextlib import asynccontextmanager
from AgentPrincipal.wizard_state_machine import (
    WizardState,
    WizardStore,
    question_for_state,
)
from AgentPrincipal.redis_client import get_redis, close_redis

_circuit_v2_mods = _load_circuit_v2_modules()
CircuitRecommendationResponse = _circuit_v2_mods["CircuitRecommendationResponse"]
if TYPE_CHECKING:
    from AgentHistorique.backend.app.schemas.circuit_agent import (
        CircuitRecommendationRequest as CircuitRecommendRequest,
    )
else:
    CircuitRecommendRequest = _circuit_v2_mods["CircuitRecommendationRequest"]
limiter = Limiter(key_func=get_remote_address)
# Set seed for consistent language detection
DetectorFactory.seed = 0

async def _purge_loop():
    from AgentPrincipal.session_memory import purge_inactive_sessions, _sessions
    while True:
        await asyncio.sleep(1800)  # toutes les 30 min
        purge_inactive_sessions()
        # Nettoyage des dicts locaux à app.py, alignés sur les sessions encore actives
        active_ids = set(_sessions.keys())
        for d in (session_languages, session_announced):
            for sid in list(d.keys()):
                if sid not in active_ids:
                    d.pop(sid, None)
# Initialize translator
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("[STARTUP] Préchargement de l'orchestrateur (modèle embeddings)...")
    get_orchestrateur()
    print("[STARTUP] Orchestrateur prêt.")
    purge_task = asyncio.create_task(_purge_loop())
    yield
    print("[SHUTDOWN] Fermeture des connexions...")
    purge_task.cancel()
    await close_redis()
    print("[SHUTDOWN] Terminé.")


app = FastAPI(title="Dourbia Chatbot API", version="1.0.0", lifespan=lifespan)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip()
        for o in os.environ.get(
            "FRONTEND_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
        ).split(",")
        if o.strip()
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from fastapi.responses import JSONResponse as _JSONResponse
from sqlalchemy.exc import OperationalError as _SAOperationalError
import psycopg2 as _psycopg2


@app.exception_handler(_SAOperationalError)
@app.exception_handler(_psycopg2.OperationalError)
async def _database_unavailable_handler(request: Request, exc: Exception):
    return _JSONResponse(
        status_code=503,
        content={"detail": "Base de données temporairement indisponible. Réessayez dans quelques instants."},
        headers={"Retry-After": "5"},
    )


# Store session contexts
sessions = {}


# Translation utility functions

_translation_cache: dict[tuple[str, str, str], str] = {}
_translation_blocked_until = 0.0
TRANSLATION_COOLDOWN_SECONDS = 120
TRANSLATION_CACHE_MAX = 1000

def _translate(text: str, source_lang: str, target_lang: str) -> str:
    global _translation_blocked_until
    cache_key = (text, source_lang, target_lang)
    cached = _translation_cache.get(cache_key)
    if cached is not None:
        return cached

    if time.monotonic() < _translation_blocked_until:
        return text
    max_attempts = 2
    for attempt in range(max_attempts):
        try:
            result = GoogleTranslator(source=source_lang, target=target_lang).translate(text)
            if len(_translation_cache) >= TRANSLATION_CACHE_MAX:
                try:
                    _translation_cache.pop(next(iter(_translation_cache)))
                except (RuntimeError, KeyError, StopIteration):
                    pass
            _translation_cache[cache_key] = result
            return result
        except Exception as e:
            err_msg = str(e).lower()
            is_rate_limit = "429" in str(e) or "too many requests" in err_msg
            if is_rate_limit and attempt < max_attempts - 1:
                time.sleep(2 ** attempt)
                continue
            if is_rate_limit:
                _translation_blocked_until = time.monotonic() + TRANSLATION_COOLDOWN_SECONDS
                print(f"[Dourbia] Translation rate limit reached. Blocking translations for {TRANSLATION_COOLDOWN_SECONDS} seconds.")
            print(f"[Dourbia] Translation ERROR ({source_lang}->{target_lang}): {e}")
            return text

    return text


SUPPORTED_LANGUAGES = {"fr", "en", "ar", "it", "de"}
LANGUAGE_CONFIDENCE_THRESHOLD = 0.70
# Mots-outils des langues latines/germaniques non françaises : évite qu'un message
# français fait de noms propres (ex. "Thermes d'Antonin") soit pris pour de l'anglais.
_LANG_MARKERS = {
    "en": {"the", "is", "are", "what", "tell", "about", "for", "and", "would",
           "how", "where", "when", "can", "you", "does", "with", "this",
           "that", "of", "my", "i"},
    "it": {"che", "di", "per", "sono", "quale", "come", "della"},
    "de": {"der", "das", "und", "ist", "ich", "wie", "nicht", "mit"},
}


def detect_language(text: str) -> str:
    """Detect a supported language, falling back to French when uncertain."""
    try:
        candidates = detect_langs(text)
        if not candidates:
            return "fr"

        candidate = candidates[0]
        if (
            candidate.lang not in SUPPORTED_LANGUAGES
            or candidate.prob < LANGUAGE_CONFIDENCE_THRESHOLD
        ):
            return "fr"

        if candidate.lang in _LANG_MARKERS:
            words = set(re.findall(r"[^\W\d_]+", text.lower()))
            if not words & _LANG_MARKERS[candidate.lang]:
                return "fr"

        return candidate.lang
    except Exception as e:
        print(f"[Dourbia] Language detection ERROR: {e}")
        return "fr"


def translate_to_french(text: str, source_lang: str) -> str:
    """Translate text to French"""
    if source_lang == "fr":
        return text
    return _translate(text, source_lang, "fr")


def translate_from_french(text: str, target_lang: str) -> str:
    """Translate text from French to target language"""
    if target_lang == "fr":
        return text
    return _translate(text, "fr", target_lang)

class PackCard(BaseModel):
    code: Optional[str] = None
    title: str
    emoji: str = "🎒"
    description: Optional[str] = None
    duration: Optional[str] = None
    capacity: Optional[int] = None
    audience: Optional[str] = None
    location: Optional[str] = None

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    language: Optional[str] = None
    action: Optional[dict] = None


from typing import List, Optional


class SourceItem(BaseModel):
    source_type: str
    source_id: Optional[int] = None
    title: Optional[str] = None
    score: Optional[float] = None
    url: Optional[str] = None
    provider: Optional[str] = None


class MemoryContext(BaseModel):
    preferred_language: str
    interests: List[str]
    available_time_minutes: Optional[int] = None
    mobility_mode: Optional[str] = None
    last_mentioned_monuments: List[str]
    primary_site_id: Optional[int] = None
    primary_site_name: Optional[str] = None
    last_substantive_user_message: Optional[str] = None


class LatencyDebug(BaseModel):
    memory_retrieval_ms: Optional[float] = None
    retrieval_ms: Optional[float] = None
    prompt_construction_ms: Optional[float] = None
    llm_generation_ms: Optional[float] = None
    memory_update_ms: Optional[float] = None
    web_search_ms: Optional[float] = None


class WizardOption(BaseModel):
    value: str
    label: str
    meta: Optional[dict] = None


class WizardCircuitStop(BaseModel):
    order: int
    name: str
    visit_duration_min: int
    price: Optional[float] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None


class WizardCircuitSummary(BaseModel):
    title: str
    summary: str
    monuments: List[WizardCircuitStop] = Field(default_factory=list)
    total_duration_min: float
    total_price: float
    budget_max: Optional[float] = None
    unknown_price_count: int = 0
    route: Optional[dict] = None


class WizardUI(BaseModel):
    state: str
    question: str
    input_type: str  # "single_select" | "multi_select" | "budget_form" | "mobility_form" | "time_form" | "preferences_form" | "confirm"
    options: List[WizardOption] = Field(default_factory=list)
    has_more: bool = False  # utilisé par place_selection pour signaler "voir plus"
    budget_ok: Optional[bool] = None  # renseigné uniquement pour CIRCUIT_REVIEW
    budget_warning: Optional[str] = None  # message d'alerte si budget_ok=False
    circuit: Optional[WizardCircuitSummary] = (
        None  # renseigné uniquement pour CIRCUIT_REVIEW
    )


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: List[SourceItem] = Field(default_factory=list)
    memory_context: MemoryContext
    suggested_actions: List[str] = Field(default_factory=list)
    latency_ms: Optional[float] = None
    latency_debug: Optional[LatencyDebug] = None
    wizard_ui: Optional[WizardUI] = None
    packs: Optional[List[PackCard]] = None


@app.post("/api/circuits/recommend", response_model=CircuitRecommendationResponse)
@limiter.limit("20/minute")
async def recommend_circuit_endpoint(request: Request, req: CircuitRecommendRequest):
    try:
        result = await asyncio.to_thread(_run_circuit_recommendation_sync, req)
    except CircuitRecommendationBusinessError as e:
        raise HTTPException(status_code=422, detail=str(e))
    return result.response


class LocationRequest(BaseModel):
    session_id: str
    lat: float
    lon: float
    langue: Optional[str] = "FR"


class PositionRequest(BaseModel):
    user_id: Optional[str] = None
    session_id: Optional[str] = None
    latitude: float
    longitude: float
    langue: Optional[str] = "FR"


class LocationResponse(BaseModel):
    triggered: bool  # True si un monument est détecté
    monument_id: Optional[str] = None
    nom: Optional[str] = None
    distance_m: Optional[float] = None
    message_aziz: Optional[str] = None


class PositionResponse(BaseModel):
    triggered: bool
    monument: Optional[str] = None
    monument_id: Optional[str] = None
    distance_m: Optional[float] = None


class SessionResponse(BaseModel):
    session_id: str


session_languages = {}
session_announced: dict[str, set] = {}


def _get_sorted_monument_options(
    offset: int = 0, limit: int = 5
) -> tuple[List[WizardOption], bool]:
    """Retourne les monuments triés par priorité décroissante, paginés."""
    mods = _load_circuit_v2_modules()
    SessionLocal = mods["SessionLocal"]
    Monument = mods["Monument"]

    db = SessionLocal()
    try:
        query = db.query(Monument)
        monuments = query.order_by(Monument.priority.desc().nullslast()).all()
    finally:
        db.close()

    page = monuments[offset : offset + limit]
    has_more = (offset + limit) < len(monuments)

    options = [
        WizardOption(
            value=m.id_str,
            label=m.name_fr or "Inconnu",
            meta={"priority": float(m.priority) if m.priority is not None else None},
        )
        for m in page
    ]
    return options, has_more


def _build_wizard_ui(wizard) -> Optional[WizardUI]:
    """Construit la spec de cards pour l'état wizard courant. None si pas de card à afficher."""
    if wizard is None:
        return None

    state = wizard.state
    state_value = state.value if isinstance(state, WizardState) else str(state)

    if state in (
        WizardState.IDLE,
        WizardState.CIRCUIT_GENERATION,
    ):
        return None

    question = question_for_state(state, lang="FR")

    if state == WizardState.GUIDE_MODE_READY:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="confirm",
            options=[
                WizardOption(value="yes", label="Oui, activer le Guide GPS"),
                WizardOption(value="no", label="Non merci"),
            ],
        )

    if state == WizardState.CIRCUIT_ADJUSTMENT:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="single_select",
            options=[
                WizardOption(value="budget", label="Ajuster le budget"),
                WizardOption(value="mobility", label="Ajuster le mode de déplacement"),
                WizardOption(value="time", label="Ajuster la durée et les horaires"),
                WizardOption(value="places", label="Ajuster les lieux"),
            ],
        )

    if state == WizardState.PLACE_SELECTION:
        options, has_more = _get_sorted_monument_options(
            offset=wizard.places_offset if getattr(wizard, "places_offset", 0) else 0,
            limit=5,
        )
        return WizardUI(
            state=state_value,
            question=question,
            input_type="multi_select",
            options=options,
            has_more=has_more,
        )

    if state == WizardState.CUSTOMIZATION_BUDGET:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="budget_form",
            options=[
                WizardOption(value="etudiant", label="Étudiant"),
                WizardOption(value="resident", label="Résident"),
                WizardOption(value="etranger", label="Étranger"),
                WizardOption(value="enseignant", label="Enseignant"),
                WizardOption(value="retraite", label="Retraité"),
                WizardOption(value="enfant", label="Enfant"),
            ],
        )

    if state == WizardState.CUSTOMIZATION_MOBILITY:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="mobility_form",
            options=[
                WizardOption(value="walking", label="À pied", meta={"type": "transport"}),
                WizardOption(value="bike", label="Vélo", meta={"type": "transport"}),
                WizardOption(value="car", label="Voiture", meta={"type": "transport"}),
                WizardOption(value="public_transport", label="Transport public", meta={"type": "transport"}),
                WizardOption(value="normale", label="Normale", meta={"type": "mobilite"}),
                WizardOption(value="reduite", label="Réduite", meta={"type": "mobilite"}),
                WizardOption(value="limitee", label="Limitée", meta={"type": "mobilite"}),
            ],
        )

    if state == WizardState.CUSTOMIZATION_PREFERENCES:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="preferences_form",
            options=[
                WizardOption(value="Romaine", label="Romaine", meta={"type": "epoque"}),
                WizardOption(value="Punique", label="Punique", meta={"type": "epoque"}),
                WizardOption(value="Byzantine", label="Byzantine", meta={"type": "epoque"}),
                WizardOption(value="Coloniale", label="Coloniale", meta={"type": "epoque"}),
                WizardOption(value="musee", label="Musée", meta={"type": "fonction"}),
                WizardOption(value="religieux", label="Religieux", meta={"type": "fonction"}),
                WizardOption(value="culturel", label="Culturel", meta={"type": "fonction"}),
                WizardOption(value="habitation", label="Habitation", meta={"type": "fonction"}),
            ],
        )

    if state == WizardState.CUSTOMIZATION_TIME:
        return WizardUI(
            state=state_value,
            question=question,
            input_type="time_form",
            options=[],
        )

    if state == WizardState.CIRCUIT_REVIEW:
        result = wizard.circuit_result or {}
        circuit_data = result.get("circuit", {})
        constraints = result.get("constraints", {})
        route_data = result.get("route")

        budget_ok = constraints.get("budget_ok")
        budget_warning = None
        if budget_ok is False:
            budget_warning = (
                f"Le coût estimé ({circuit_data.get('total_price', '?')} DT) dépasse "
                f"votre budget maximal ({(wizard.budget or {}).get('amount', '?')} DT)."
            )
        circuit_summary = None
        if circuit_data:
            circuit_summary = WizardCircuitSummary(
                title=circuit_data.get("title", "Votre circuit"),
                summary=circuit_data.get("summary", ""),
                monuments=[
                    WizardCircuitStop(
                        order=m.get("order", i + 1),
                        name=m.get("name", "?"),
                        visit_duration_min=m.get("visit_duration_min", 0),
                        price=m.get("price", 0.0),
                        latitude=m.get("latitude"),
                        longitude=m.get("longitude"),
                    )
                    for i, m in enumerate(circuit_data.get("monuments", []))
                ],
                total_duration_min=circuit_data.get("total_duration_min", 0),
                total_price=circuit_data.get("total_price", 0.0),
                budget_max=(wizard.budget or {}).get("amount"),
                unknown_price_count=circuit_data.get("unknown_price_count", 0),
                route=route_data,
            )
        return WizardUI(
            state=state_value,
            question=question,
            input_type="confirm",
            options=[
                WizardOption(value="confirm_circuit", label="Confirmer ce circuit"),
                WizardOption(value="adjust_circuit", label="Ajuster ce circuit"),
            ],
            budget_ok=budget_ok,
            budget_warning=budget_warning,
            circuit=circuit_summary,
        )

    # État non mappé explicitement (ex: CIRCUIT_ADJUSTMENT pas encore branché) — pas de card
    return None


def _translate_chat_response(response_fr: str, detected_language: str) -> str:
    if not detected_language or detected_language == "fr":
        return response_fr
    return translate_from_french(response_fr, detected_language)


@app.post("/api/chat", response_model=ChatResponse)
@limiter.limit("20/minute")
async def chat_endpoint(request: Request, req: ChatRequest):
    try:

        message = req.message or ""
        if not message and not req.action:
            raise HTTPException(status_code=400, detail="Message is required")

        session_id = req.session_id or str(uuid.uuid4())
        if session_id not in sessions:
            sessions[session_id] = True

        if req.action:
            # Payload structuré (clic sur card) — pas de traduction nécessaire,
            # question_for_state() gère déjà le texte de sortie en FR
            detected_language = session_languages.get(session_id, "fr")

            if req.language and req.language in SUPPORTED_LANGUAGES:
                detected_language = req.language
            session_languages[session_id] = detected_language

            response_fr = await chat(session_id, message, action=req.action)
            response = (
                response_fr  # pas de traduction pour l'instant sur les réponses wizard
            )
        else:
            if session_id in session_languages:
                detected_language = session_languages[session_id]
            else:
                if req.language and req.language in SUPPORTED_LANGUAGES:
                    detected_language = req.language
                elif len(message.split()) >= 4:
                    detected_language = detect_language(message)
                else:
                    detected_language = "fr"  # fallback par défaut
                session_languages[session_id] = detected_language

            print(f"[Dourbia] Detected language: {detected_language}")

            message_fr = await asyncio.to_thread(
                translate_to_french, message, detected_language)
            print(f"[Dourbia] Original message: {message}")
            print(f"[Dourbia] Translated to FR: {message_fr}")

            response_fr = await chat(session_id, message_fr, action=req.action)

        response =await asyncio.to_thread(
            _translate_chat_response, response_fr, detected_language)

        profil = get_profile(session_id)
        wizard_store = WizardStore(await get_redis())
        wizard = await wizard_store.get(session_id)
        wizard_ui = _build_wizard_ui(wizard)

        raw_packs = profil.get("last_packs")
        packs_ui = [PackCard(**p) for p in raw_packs] if raw_packs else None
        if raw_packs:
            update_profile(
                session_id, {"last_packs": None}
            )  # évite de refaire apparaître les packs au tour suivant

        return ChatResponse(
            session_id=session_id,
            answer=response,
            sources=[],
            memory_context=MemoryContext(
                preferred_language=detected_language,
                interests=profil.get("preferences", []),
                available_time_minutes=profil.get("duree_min"),
                mobility_mode=profil.get("mobilite"),
                last_mentioned_monuments=profil.get("lieux_vus", []),
                primary_site_id=profil.get("monument_en_attente_id"),
                primary_site_name=profil.get("monument_en_attente_nom"),
                last_substantive_user_message=req.message,
            ),
            suggested_actions=[],
            latency_ms=None,
            latency_debug=None,
            wizard_ui=wizard_ui,
            packs=packs_ui,
        )

    except HTTPException:
        raise

    except Exception as e:
        print(f"[Dourbia] Error: {str(e)}")
        traceback.print_exc()
        raise HTTPException(status_code=500, detail="Une erreur interne est survenue.")


@app.post("/api/position", response_model=PositionResponse)
@limiter.limit("30/minute")
async def position_endpoint(request: Request, req: PositionRequest):
    """Reçoit une mise à jour GPS et déclenche un événement de proximité si un monument du circuit actif est à portée."""
    session_id = req.user_id or req.session_id or ""
    if not session_id:
        return PositionResponse(triggered=False)

    profil = get_profile(session_id)
    etapes = profil.get("circuit_etapes") or []
    circuit_id = profil.get("circuit_confirme_id") or get_active_circuit(session_id)
    if not etapes and not circuit_id:
        return PositionResponse(triggered=False)

    try:
        geo = get_geo_service()
        if etapes:
            nearby = geo.get_nearby_from_stops(
                lat=req.latitude, lon=req.longitude, stops=etapes, rayon_m=100
            )
        else:
            nearby = await geo.get_nearby_monuments_for_circuit(
                lat=req.latitude,
                lon=req.longitude,
                circuit_id=str(circuit_id),
                langue=(req.langue or "FR").upper(),
                rayon_override_m=100,
            )
    except Exception as exc:
        print(f"[Dourbia] Erreur /api/position : {exc}")
        return PositionResponse(triggered=False)

    if not nearby:
        return PositionResponse(triggered=False)

    # Anti-spam : chaque monument n'est annoncé qu'une fois par session
    deja_annonces = session_announced.setdefault(session_id, set())
    monument = next(
        (m for m in nearby if (m.get("id") or m.get("nom")) not in deja_annonces),
        None,
    )
    if monument is None:
        return PositionResponse(triggered=False)
    deja_annonces.add(monument.get("id") or monument.get("nom"))
    orchestrateur = get_orchestrateur()
    await orchestrateur.handle_proximity_trigger(
        user_id=session_id,
        monument_id=str(monument.get("id", "")),
        monument_nom=monument.get("nom", "Monument"),
        langue=(req.langue or "FR").upper(),
    )

    return PositionResponse(
        triggered=True,
        monument=monument.get("nom"),
        monument_id=str(monument.get("id", "")),
        distance_m=monument.get("distance_m"),
    )


@app.post("/api/sessions", response_model=SessionResponse)
@limiter.limit("10/minute")
async def create_session(request: Request):
    session_id = str(uuid.uuid4())
    sessions[session_id] = True
    return SessionResponse(session_id=session_id)


class MonumentItemResponse(BaseModel):
    id: int
    name_fr: str
    name_en: Optional[str] = None
    name_ar: Optional[str] = None
    latitude: float
    longitude: float
    visit_duration_min: Optional[int] = None
    dominant_period: Optional[str] = None
    function: Optional[str] = None
    popularity: Optional[float] = None
    image_url: Optional[str] = None


class MonumentsListResponse(BaseModel):
    monuments: List[MonumentItemResponse]


@app.get("/api/monuments", response_model=MonumentsListResponse)
@limiter.limit("60/minute")
async def get_monuments(request: Request):
   mods = _load_circuit_v2_modules()
   SessionLocal = mods["SessionLocal"]
   Monument = mods["Monument"]

   db = SessionLocal()
   try:
       
        monuments = db.query(Monument).order_by(
            Monument.priority.desc().nullslast()
        ).all()
   finally:
        db.close()

   result = []
   for m in monuments:
       
        if m.latitude_float is None or m.longitude_float is None:
            continue

        result.append(
            MonumentItemResponse(
                id=int(m.id_str),
                name_fr=m.name_fr or "Inconnu",
                name_en=m.name_en,
                name_ar=m.name_ar,
                latitude=m.latitude_float,
                longitude=m.longitude_float,
                visit_duration_min=(
                    int(m.visit_duration_minutes)
                    if m.visit_duration_minutes is not None
                    else None
                ),
                dominant_period=m.dominant_period,
                function=m.function,
                popularity=(
                    float(m.priority) if m.priority is not None else None
                ),
                image_url=m.panoramic_image_url,
            )
        )

   return MonumentsListResponse(monuments=result)


@app.post("/api/location", response_model=LocationResponse)
@limiter.limit("30/minute")
async def location_endpoint(request: Request, req: LocationRequest):
    """
    Endpoint appelé par le frontend toutes les 30s en mode guide terrain.

    - Recoit la position GPS de l'utilisateur
    - Detecte les monuments dans un rayon de 150m
    - Si un nouveau monument est trouvé (pas encore annoncé cette session)
      → retourne triggered=True avec le message qu'Aziz va prononcer
    - Sinon → triggered=False (le frontend ne fait rien)

    Anti-spam : chaque monument n'est annoncé qu'une seule fois par session.
    """
    try:
        session_id = req.session_id
        lat = req.lat
        lon = req.lon
        langue = (req.langue or "FR").upper()

        # Récupère ou crée le set des monuments déjà annoncés
        if session_id not in session_announced:
            session_announced[session_id] = set()
        already_announced = session_announced[session_id]

        # Détection monuments proches
        geo = get_geo_service()
        circuit_actif = get_active_circuit(session_id)

        if circuit_actif:

            nearby = await geo.get_nearby_monuments_for_circuit(
                lat=lat,
                lon=lon,
                circuit_id=circuit_actif,
                langue=langue,
                rayon_override_m=150,
            )
        else:
            # Pas de circuit choisi → pas de suggestion proactive (mode narrateur pur)
            nearby = []

        if not nearby:
            return LocationResponse(triggered=False)

        # Prend le monument le plus proche non encore annoncé
        nouveau = None
        for monument in nearby:
            if monument["id"] not in already_announced:
                nouveau = monument
                break

        if not nouveau:
            # Tous les monuments proches ont déjà été annoncés
            return LocationResponse(triggered=False)

        # Marquer comme annoncé
        already_announced.add(nouveau["id"])

        # Synchroniser avec l'orchestrateur : pose monument_en_attente
        # pour que la prochaine réponse "oui" de l'utilisateur déclenche
        # la présentation narrative complète (_handle_terrain_question)
        orchestrateur = get_orchestrateur()
        await orchestrateur.handle_proximity_trigger(
            user_id=session_id,
            monument_id=nouveau["id"],
            monument_nom=nouveau["nom"],
            langue=langue,
        )

        # Construire le message qu'Aziz va prononcer
        message_aziz = _build_proximity_message(nouveau, langue)

        return LocationResponse(
            triggered=True,
            monument_id=nouveau["id"],
            nom=nouveau["nom"],
            distance_m=nouveau["distance_m"],
            message_aziz=message_aziz,
        )

    except Exception as e:
        print(f"[Dourbia] Erreur /api/location : {e}")
        return LocationResponse(triggered=False)


def _build_proximity_message(monument: dict, langue: str) -> str:
    """
    Génère le message de proximité qu'Aziz prononce quand un monument est détecté.
    Multilingue. Simple et direct — pas de LLM pour cette notification.
    """
    nom = monument["nom"]
    distance = int(monument["distance_m"])
    duree = monument.get("duree_visite_min", 0)
    statut = monument.get("statut", "").lower()

    # Alerte statut fermé
    ferme = "fermé" in statut or "ferme" in statut or "closed" in statut.lower()

    if langue == "AR":
        msg = f"🗺️ أنت الآن بالقرب من **{nom}** (على بُعد {distance} متر)."
        if ferme:
            msg += "\n⚠️ المعلم مغلق حالياً."
        else:
            if duree:
                msg += f"\n⏱️ مدة الزيارة المقترحة: {duree} دقيقة."
            msg += "\n\nهل تريدني أن أحكي لك تاريخ هذا المكان؟"

    elif langue == "EN":
        msg = f"🗺️ You are now near **{nom}** ({distance}m away)."
        if ferme:
            msg += "\n⚠️ This site is currently closed."
        else:
            if duree:
                msg += f"\n⏱️ Suggested visit time: {duree} minutes."
            msg += "\n\nWould you like me to tell you about the history of this place?"

    else:  # FR + IT + DE → fallback FR
        msg = f"🗺️ Je remarque que vous êtes près de **{nom}** (à {distance}m)."
        if ferme:
            msg += "\n⚠️ Ce site est actuellement fermé."
        else:
            if duree:
                msg += f"\n⏱️ Durée de visite conseillée : {duree} minutes."
            msg += "\n\nSouhaitez-vous que je vous raconte l'histoire de ce lieu ?"

    return msg


@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "Dourbia Chatbot API"}


@app.get("/health/ready")
async def health_ready():
    """Readiness : Postgres (circuits + RAG historique) et Redis, timeouts courts."""
    from fastapi.responses import JSONResponse

    def _probe_pg(env_name: str) -> None:
        import psycopg2

        dsn = re.sub(
            r"^postgres(?:ql)?(?:\+\w+)?://", "postgresql://", os.environ.get(env_name, "")
        )
        conn = psycopg2.connect(dsn, connect_timeout=3)
        try:
            cur = conn.cursor()
            cur.execute("SELECT 1")
        finally:
            conn.close()

    checks: dict[str, str] = {}
    for label, env_name in (
        ("postgres_circuit", "CIRCUIT_DATABASE_URL"),
        ("postgres_historical", "HISTORICAL_DATABASE_URL"),
    ):
        try:
            await asyncio.wait_for(asyncio.to_thread(_probe_pg, env_name), timeout=5)
            checks[label] = "ok"
        except Exception as exc:
            checks[label] = f"error: {type(exc).__name__}"
    try:
        r = await get_redis()
        await asyncio.wait_for(r.ping(), timeout=3)
        checks["redis"] = "ok"
    except Exception as exc:
        checks["redis"] = f"error: {type(exc).__name__}"
    ready = all(v == "ok" for v in checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={"status": "ready" if ready else "not_ready", "checks": checks},
    )


@app.get("/api/guide-status/{session_id}")
@limiter.limit("30/minute")
async def guide_status(request: Request, session_id: str):
    """Le frontend poll ceci après chaque réponse chat pour savoir s'il doit démarrer le GPS."""
    profil = get_profile(session_id)
    return {
        "mode_guide_actif": profil.get("mode_guide_actif", False),
        "circuit_id": profil.get("circuit_confirme_id"),
        "circuit_nom": profil.get("circuit_confirme_nom"),
    }


@app.get("/api/wizard-options/{session_id}")
@limiter.limit("30/minute")
async def wizard_options(
    request: Request, session_id: str, offset: int = 0, limit: int = 5
):
    """Pagination read-only pour select_places — n'écrit jamais dans Redis."""
    wizard_store = WizardStore(await get_redis())
    wizard = await wizard_store.get(session_id)
    if wizard is None or wizard.state != WizardState.PLACE_SELECTION:
        raise HTTPException(
            status_code=400, detail="Wizard pas en état PLACE_SELECTION"
        )

    options, has_more = _get_sorted_monument_options(offset=offset, limit=limit)
    return {"options": [o.model_dump() for o in options], "has_more": has_more}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
