from __future__ import annotations
import logging, os
from datetime import date as _date
from core.config import settings
from core.infra import get_pool, record_to_dict

log = logging.getLogger("dourbia.database")

DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS voitures (
    id TEXT PRIMARY KEY, immatriculation TEXT, marque TEXT NOT NULL, modele TEXT,
    type_vehicule TEXT, categorie TEXT, annee INTEGER, couleur TEXT,
    places INTEGER DEFAULT 5, portes INTEGER DEFAULT 4, carburant TEXT,
    transmission TEXT, puissance_cv INTEGER DEFAULT 0, climatisation BOOLEAN DEFAULT FALSE,
    kilometrage INTEGER DEFAULT 0, prix_jour NUMERIC(10,2) DEFAULT 0,
    caution NUMERIC(10,2) DEFAULT 0, disponible BOOLEAN DEFAULT TRUE,
    statut_excel TEXT, agence TEXT, ville TEXT, extras TEXT DEFAULT '',
    note_client NUMERIC(3,2) DEFAULT 0, nb_reservations INTEGER DEFAULT 0,
    electrique BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS reservations (
    id TEXT PRIMARY KEY, type TEXT DEFAULT 'voiture',
    client_nom TEXT NOT NULL, client_tel TEXT NOT NULL, client_email TEXT,
    voiture_id TEXT NOT NULL REFERENCES voitures(id),
    voiture_details TEXT, voiture_categorie TEXT, voiture_immat TEXT,
    voiture_agence TEXT, voiture_ville TEXT, voiture_extras TEXT DEFAULT '',
    voiture_electrique BOOLEAN DEFAULT FALSE,
    date_debut DATE NOT NULL, date_fin DATE NOT NULL, nb_jours INTEGER NOT NULL,
    prix_jour NUMERIC(10,2) NOT NULL, caution NUMERIC(10,2) DEFAULT 0,
    prix_total NUMERIC(10,2) NOT NULL, statut TEXT DEFAULT 'EN_ATTENTE',
    raison_refus TEXT, note_feedback INTEGER CHECK (note_feedback BETWEEN 1 AND 5),
    date_feedback TIMESTAMPTZ, date_reservation TIMESTAMPTZ DEFAULT NOW(),
    rappel_envoye BOOLEAN DEFAULT FALSE, feedback_envoye BOOLEAN DEFAULT FALSE,
    rappel_proprietaire_envoye BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tokens_confirmation (
    token TEXT PRIMARY KEY, reservation_id TEXT NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS tokens_annulation (
    token TEXT PRIMARY KEY, reservation_id TEXT NOT NULL REFERENCES reservations(id) ON DELETE CASCADE,
    expires_at TIMESTAMPTZ NOT NULL, created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS client_profiles (
    session_id TEXT PRIMARY KEY, client_nom TEXT, client_tel TEXT, client_email TEXT,
    ville_preferee TEXT, budget_max NUMERIC(10,2), categorie_pref TEXT,
    nb_places_min INTEGER, transmission TEXT, climatisation BOOLEAN,
    preferences JSONB DEFAULT '{}', derniere_resa TEXT REFERENCES reservations(id),
    nb_conversations INTEGER DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS episodic_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL, content TEXT NOT NULL,
    embedding vector(384), importance FLOAT DEFAULT 0.5,
    metadata JSONB DEFAULT '{}', access_count INTEGER DEFAULT 0,
    last_accessed TIMESTAMPTZ, created_at TIMESTAMPTZ DEFAULT NOW(),
    expires_at TIMESTAMPTZ DEFAULT NOW() + INTERVAL '30 days'
);

CREATE TABLE IF NOT EXISTS procedural_memory (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    trigger_embedding vector(384), trigger_pattern TEXT NOT NULL,
    lesson TEXT NOT NULL, error_type TEXT NOT NULL,
    applied_count INTEGER DEFAULT 0, success_rate FLOAT DEFAULT 0.0,
    created_at TIMESTAMPTZ DEFAULT NOW(), updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS agent_traces (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    session_id TEXT NOT NULL, trace_id TEXT, user_message TEXT NOT NULL,
    assistant_reply TEXT, intention TEXT,
    tools_called JSONB DEFAULT '[]', tool_errors JSONB DEFAULT '[]',
    reflection_triggered BOOLEAN DEFAULT FALSE, reflection_result TEXT,
    correction_applied BOOLEAN DEFAULT FALSE,
    guard_blocked BOOLEAN DEFAULT FALSE, guard_score FLOAT DEFAULT 0.0,
    tokens_used INTEGER DEFAULT 0, latency_ms INTEGER, model_used TEXT,
    episodic_hits INTEGER DEFAULT 0, error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS scoring_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(), ville TEXT NOT NULL,
    mois INTEGER NOT NULL, annee INTEGER NOT NULL,
    nb_resa INTEGER DEFAULT 0, nb_auto_ok INTEGER DEFAULT 0, nb_litiges INTEGER DEFAULT 0,
    seuil_calcule NUMERIC(4,3), updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ville, mois, annee)
);

CREATE TABLE IF NOT EXISTS rebooking_suggestions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    reservation_id TEXT NOT NULL REFERENCES reservations(id),
    voiture_alt_id TEXT NOT NULL REFERENCES voitures(id),
    prix_actuel NUMERIC(10,2) NOT NULL, prix_alt NUMERIC(10,2) NOT NULL,
    economie_totale NUMERIC(10,2) NOT NULL, statut TEXT DEFAULT 'DETECTEE',
    email_envoye BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(), notified_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS weather_alerts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ville TEXT NOT NULL, date_debut DATE NOT NULL, date_fin DATE NOT NULL,
    severite TEXT NOT NULL, message TEXT NOT NULL,
    source TEXT DEFAULT 'weather_agent', traitee BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_res_statut ON reservations(statut);
CREATE INDEX IF NOT EXISTS idx_res_date ON reservations(date_debut);
CREATE INDEX IF NOT EXISTS idx_voitures_ville ON voitures(ville);
CREATE INDEX IF NOT EXISTS idx_voitures_dispo ON voitures(disponible) WHERE disponible=TRUE;
CREATE INDEX IF NOT EXISTS idx_traces_session ON agent_traces(session_id, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_session ON episodic_memory(session_id, created_at DESC);
"""
import asyncio
import asyncpg
import logging

logger = logging.getLogger(__name__)

async def create_pool_with_retry(dsn: str, retries: int = 5, delay: float = 2.0):
    for attempt in range(1, retries + 1):
        try:
            pool = await asyncpg.create_pool(dsn, min_size=2, max_size=10)
            logger.info(f"[DB] Pool créé (tentative {attempt})")
            return pool
        except (asyncpg.PostgresConnectionError, ConnectionResetError, OSError) as e:
            logger.warning(f"[DB] Tentative {attempt}/{retries} échouée : {e}")
            if attempt == retries:
                raise
            await asyncio.sleep(delay * attempt)  # backoff exponentiel
            
            
async def init_db():
    pool = await get_pool()
    async with pool.acquire() as conn:
        for stmt in DDL.strip().split(";"):
            s = stmt.strip()
            if s:
                try: await conn.execute(s)
                except Exception as e:
                    msg = str(e).lower()
                    if "already exists" not in msg: log.debug(f"[DDL] {e}") # type: ignore[union-attr]

    count = await pool.fetchval("SELECT COUNT(*) FROM voitures")
    if count == 0:
        voitures = _charger_excel()
        if voitures:
            await _seed_voitures(voitures)
            log.info(f"[DB] {len(voitures)} voitures importées")
    else:
        log.info(f"[DB] {count} voitures en base")

async def _seed_voitures(voitures):
    pool = await get_pool()
    sql = """INSERT INTO voitures (id,immatriculation,marque,modele,type_vehicule,categorie,
    annee,couleur,places,portes,carburant,transmission,puissance_cv,climatisation,
    kilometrage,prix_jour,caution,disponible,statut_excel,agence,ville,extras,
    note_client,nb_reservations,electrique) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,
    $11,$12,$13,$14,$15,$16,$17,$18,$19,$20,$21,$22,$23,$24,$25) ON CONFLICT (id) DO NOTHING"""
    async with pool.acquire() as conn:
        async with conn.transaction():
            await conn.executemany(sql, [
                (v["id"],v["immatriculation"],v["marque"],v["modele"],v["type_vehicule"],
                 v["categorie"],v["annee"],v["couleur"],v["places"],v["portes"],v["carburant"],
                 v["transmission"],v["puissance_cv"],bool(v["climatisation"]),v["kilometrage"],
                 v["prix_jour"],v["caution"],bool(v["disponible"]),v["statut_excel"],
                 v["agence"],v["ville"],v["extras"],v["note_client"],v["nb_reservations"],
                 bool(v["electrique"])) for v in voitures])

def _charger_excel():
    try:
        import pandas as pd
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","dataset_location_voitures.xlsx")
        if not os.path.exists(path):
            log.warning(f"[EXCEL] Introuvable : {path}"); return []
        xl = pd.ExcelFile(path); sn = xl.sheet_names[0]
        for s in xl.sheet_names:
            if isinstance(s, str) and "v" in s.lower() and "hicule" in s.lower():
                 sn = s
                 break
        df = pd.read_excel(path, sheet_name=sn)
        def si(v,d=0):
            try: return int(v) if not pd.isna(v) else d
            except: return d
        def sf(v,d=0.0):
            try: return float(v) if not pd.isna(v) else d
            except: return d
        out = []
        for _,row in df.iterrows():
            statut=str(row.get("Statut","")).strip(); carburant=str(row.get("Carburant","")).strip()
            clim=str(row.get("Climatisation","")).strip().lower()=="oui"
            # Normaliser pour être insensible aux accents (Électrique / Electrique)
            import unicodedata as _ud
            def _norm_str(s: str) -> str: return _ud.normalize("NFD",s.lower()).encode("ascii","ignore").decode("ascii")
            elec = _norm_str(str(carburant)) in ("electrique",) or _norm_str(str(row.get("Catégorie",row.get("Categorie","")))).strip() == "electrique"
            extras_r=row.get("Extras / Options","")
            extras="" if pd.isna(extras_r) or str(extras_r).strip().lower()=="aucun" else str(extras_r).strip()
            modele=""
            for col in row.index:
                if "mod" in col.lower() and "le" in col.lower(): modele=str(row[col]).strip(); break
            out.append({"id":str(row["ID"]).strip(),"immatriculation":str(row.get("Immatriculation","")).strip(),
                "marque":str(row["Marque"]).strip(),"modele":modele,
                "type_vehicule":str(row.get("Type de véhicule",row.get("Type de vehicule",""))).strip(),
                "categorie":str(row.get("Catégorie",row.get("Categorie",""))).strip(),
                "annee":si(row.get("Année",row.get("Annee",0))),"couleur":str(row.get("Couleur","")).strip(),
                "places":si(row.get("Nombre de places",5),5),"portes":si(row.get("Nombre de portes",4),4),
                "carburant":carburant,"transmission":str(row.get("Transmission","")).strip(),
                "puissance_cv":si(row.get("Puissance (CV)",0)),"climatisation":clim,
                "kilometrage":si(row.get("Kilométrage (km)",row.get("Kilometrage (km)",0))),
                "prix_jour":sf(row.get("Prix/jour (TND)",0)),"caution":sf(row.get("Caution (TND)",0)),
                "disponible":statut=="Disponible","statut_excel":statut,
                "agence":str(row.get("Agence","")).strip(),"ville":str(row.get("Ville","")).strip(),
                "extras":extras,"note_client":sf(row.get("Note client (/ 5)",0)),
                "nb_reservations":si(row.get("Nb réservations",row.get("Nb reservations",0))),"electrique":elec})
        log.info(f"[EXCEL] {len(out)} voitures lues"); return out
    except Exception as e:
        log.error(f"[EXCEL] Erreur : {e}"); return []
