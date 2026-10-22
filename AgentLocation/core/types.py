from __future__ import annotations
import re
from datetime import date as _date, datetime
from enum import Enum
from typing import Optional
from pydantic import BaseModel, field_validator, model_validator

class StatutReservation(str, Enum):
    EN_ATTENTE = "EN_ATTENTE"; CONFIRMEE = "CONFIRMEE"; ANNULEE = "ANNULEE"; REFUSEE = "REFUSEE"

class Severite(str, Enum):
    INFO = "INFO"; WARNING = "WARNING"; CRITICAL = "CRITICAL"

class IntentionClient(str, Enum):
    DECOUVERTE = "decouverte"; RECHERCHE = "recherche"; RESERVATION = "reservation"
    ANNULATION = "annulation"; SUIVI = "suivi"; METEO = "meteo"; FAQ = "faq"; INCONNU = "inconnu"

class ClientProfile(BaseModel):
    client_nom: Optional[str] = None
    client_tel: Optional[str] = None
    client_email: Optional[str] = None
    ville_preferee: Optional[str] = None
    budget_max: Optional[float] = None
    categorie_pref: Optional[str] = None
    nb_places_min: Optional[int] = None
    transmission: Optional[str] = None
    climatisation: Optional[bool] = None
    dates_debut: Optional[str] = None
    dates_fin: Optional[str] = None

    @field_validator("client_tel")
    @classmethod
    def valider_tel(cls, v):
        if v is None: return v
        tel = v.strip().replace(" ","").replace("-","")
        for p in ("+216","00216"):
            if tel.startswith(p): tel = tel[len(p):]
        if not re.fullmatch(r"[2579]\d{7}", tel): raise ValueError(f"Tel invalide: {v}")
        return tel

    @field_validator("client_email")
    @classmethod
    def valider_email(cls, v):
        if v is None: return v
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", v.strip()): raise ValueError(f"Email invalide: {v}")
        return v.strip().lower()

    @field_validator("dates_debut","dates_fin")
    @classmethod
    def valider_dates(cls, v):
        if v is None: return v
        v = v.strip()
        if re.match(r"^\d{1,2}[-/.]\d{1,2}$", v):
            sep = "-" if "-" in v else ("/" if "/" in v else ".")
            v = f"{v}{sep}{_date.today().year}"
            
        for fmt in ("%d/%m/%Y","%d-%m-%Y","%d.%m.%Y"):
            try: return datetime.strptime(v,fmt).strftime("%Y-%m-%d")
            except: continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$",v): return None
        return v

class ReservationRequest(BaseModel):
    voiture_id: str; client_nom: str; client_tel: str; client_email: str
    date_debut: str; date_fin: str

    @field_validator("client_nom")
    @classmethod
    def nom_valide(cls, v):
        if v.strip().lower() in {"client","unknown","inconnu","test","nom","prenom"} or len(v.strip()) < 2:
            raise ValueError("Nom invalide")
        return v.strip()

    @field_validator("date_debut","date_fin")
    @classmethod
    def date_valide(cls, v):
        v = v.strip()
        # Si le format est DD-MM ou DD/MM ou DD.MM (sans année)
        if re.match(r"^\d{1,2}[-/.]\d{1,2}$", v):
            sep = "-" if "-" in v else ("/" if "/" in v else ".")
            v = f"{v}{sep}{_date.today().year}"
            
        for fmt in ("%d/%m/%Y","%d-%m-%Y","%d.%m.%Y"):
            try: return datetime.strptime(v,fmt).strftime("%Y-%m-%d")
            except: continue
        if not re.match(r"^\d{4}-\d{2}-\d{2}$",v): raise ValueError(f"Date invalide: {v}")
        return v

class ChatRequest(BaseModel):
    message: str; session_id: str = "default"

    @field_validator("message")
    @classmethod
    def sanitiser(cls, v):
        v = v.strip()
        if len(v) > 2000: raise ValueError("Message trop long")
        return v

class WeatherAlertRequest(BaseModel):
    ville: str; date_debut: str; date_fin: str
    severite: Severite; message: str; source: str = "weather_agent"

class AgentState(BaseModel):
    session_id: str; user_message: str
    intention: IntentionClient = IntentionClient.INCONNU
    profil: dict = {}; history: list = []; tool_calls: list = []; tool_results: list = []
    reply: str = ""; tokens_used: int = 0; reflection_ok: bool = True
    correction_applied: bool = False; error: Optional[str] = None; latency_ms: int = 0
    episodic_context: list = []; guard_score: float = 0.0; guard_blocked: bool = False
