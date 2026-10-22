"""
geo_service.py — Service de géolocalisation terrain pour le mode guide Aziz.

Fonctionnalités :
- Calcul de distance Haversine (pure Python, zéro dépendance externe)
- Détection des monuments dans le rayon de proximité depuis sig_dourbia
- Normalisation des coordonnées (virgule/point)
- Réponse multilingue prête pour l'orchestrateur

Utilise le même db.py (psycopg2) que le reste du projet.

Usage :
    from geo_service import GeoService, get_geo_service

    service = get_geo_service()
    monuments = await service.get_nearby_monuments(lat=36.856, lon=10.331, langue="FR")
"""

import asyncio
import logging
import math
import sys
import os
import time
from typing import Optional
from contextlib import contextmanager

import psycopg2
from psycopg2 import pool as _pg_pool

# ── Connexion dédiée à la base des monuments (conteneur Docker dourbia_db) ──
# Indépendante du db.py d'AgentMeteo : AgentCircuit (ancienne source de get_conn)
# a été supprimé, et le port 5432 (base "dourbia" ou "sig_dourbia" hors Docker)
# ne contient pas la table monuments — seule l'instance Docker (5433) l'a.
_DOURBIA_DB_CONFIG = {
    "host": os.getenv("DOURBIA_PG_HOST", "127.0.0.1"),
    "port": int(os.getenv("DOURBIA_PG_PORT", "5433")),
    "dbname": os.getenv("DOURBIA_PG_DB", "dourbia"),
    "user": os.getenv("DOURBIA_PG_USER", "dourbia"),
    "password": os.getenv("DOURBIA_PG_PASSWORD", "dourbia"),
}
_dourbia_pool: Optional[_pg_pool.ThreadedConnectionPool] = None


def _get_dourbia_pool() -> _pg_pool.ThreadedConnectionPool:
    global _dourbia_pool
    if _dourbia_pool is None:
        _dourbia_pool = _pg_pool.ThreadedConnectionPool(1, 5, **_DOURBIA_DB_CONFIG)
    return _dourbia_pool


@contextmanager
def get_conn():
    p = _get_dourbia_pool()
    conn = p.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        p.putconn(conn)

log = logging.getLogger("chatbot.geo_service")

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURATION
# ─────────────────────────────────────────────────────────────────────────────

# Rayon de détection par défaut (mètres)
RAYON_DEFAUT_M = 150

# Rayon maximum absolu pour éviter les faux positifs
RAYON_MAX_M = 500

# Colonnes de description selon la langue
DESCRIPTION_COLS = {
    "FR": ("nom_monument_fr", "description_fr"),
    "EN": ("nom_monument_en", "description_en"),
    "AR": ("nom_monument_ar", "description_ar"),
    "IT": ("nom_monument_fr", "description_fr"),  # fallback FR
    "DE": ("nom_monument_fr", "description_fr"),  # fallback FR
}

# Cache monuments par circuit (~100 entrées max)
_CIRCUIT_MONUMENTS_CACHE: dict[str, tuple[list, float]] = {}
_CIRCUIT_CACHE_TTL_SEC = 60
_CIRCUIT_CACHE_MAX_FALLBACK_SEC = 600


def invalidate_circuit_monuments_cache(circuit_id: str = None) -> None:
    """Invalide le cache d'un circuit spécifique, ou tout le cache si circuit_id=None."""
    global _CIRCUIT_MONUMENTS_CACHE
    if circuit_id is None:
        _CIRCUIT_MONUMENTS_CACHE = {}
    else:
        _CIRCUIT_MONUMENTS_CACHE.pop(circuit_id, None)


# Cache monuments global (tous les monuments)
_MONUMENTS_CACHE: Optional[tuple[list, float]] = None
_MONUMENTS_CACHE_TTL_SEC = 60
_MONUMENTS_CACHE_MAX_FALLBACK_SEC = 600


def invalidate_monuments_cache() -> None:
    """Invalide le cache global des monuments."""
    global _MONUMENTS_CACHE
    _MONUMENTS_CACHE = None


# ─────────────────────────────────────────────────────────────────────────────
# FORMULE HAVERSINE
# ─────────────────────────────────────────────────────────────────────────────


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calcule la distance en mètres entre deux points GPS (formule Haversine).
    Pure Python, zéro dépendance.

    Args:
        lat1, lon1 : Position utilisateur
        lat2, lon2 : Position monument

    Returns:
        Distance en mètres (float)
    """
    R = 6_371_000  # Rayon de la Terre en mètres

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def _parse_coord(value: Optional[str]) -> Optional[float]:
    """
    Parse une coordonnée GPS stockée en texte.
    Gère les deux formats présents en DB : virgule (36,856) et point (36.856).

    Returns:
        float ou None si invalide
    """
    if value is None:
        return None
    try:
        return float(str(value).strip().replace(",", "."))
    except (ValueError, TypeError):
        log.warning(f"[GEO] Coordonnée invalide ignorée : {value!r}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# REQUÊTE DB (synchrone — wrappée dans asyncio.to_thread)
# ─────────────────────────────────────────────────────────────────────────────


def _fetch_monuments_sync() -> list[dict]:
    """
    Charge tous les monuments avec coordonnées valides depuis sig_dourbia.
    Synchrone (psycopg2) — à appeler via asyncio.to_thread().
    """
    sql = """
        SELECT
            id_monument,
            nom_monument_fr,
            nom_monument_en,
            nom_monument_ar,
            latitude_monument,
            longitude_monument,
            description_fr,
            description_en,
            description_ar,
            duree_visite_en_min,
            statut_monument,
            accessibilite_monument,
            horaire_ouverture_ete,
            horaire_fermeture_ete,
            horaire_ouverture_hiver,
            horaire_fermeture_hiver,
            adresse_monument,
            importance_monument
        FROM monuments
        WHERE latitude_monument IS NOT NULL
          AND longitude_monument IS NOT NULL
          AND latitude_monument <> ''
          AND longitude_monument <> ''
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    return [dict(zip(cols, row)) for row in rows]


async def _get_monuments_cached(force_refresh: bool = False) -> list[dict]:
    """Charge tous les monuments avec cache TTL + fallback sur cache expiré."""
    global _MONUMENTS_CACHE
    now = time.monotonic()
    cached = _MONUMENTS_CACHE

    if (
        cached is not None
        and not force_refresh
        and (now - cached[1]) <= _MONUMENTS_CACHE_TTL_SEC
    ):
        return cached[0]

    try:
        rows = await asyncio.to_thread(_fetch_monuments_sync)
        _MONUMENTS_CACHE = (rows, now)
        log.info(f"[GEO] {len(rows)} monuments chargés depuis la DB")
        return rows
    except Exception:
        if cached is not None and (now - cached[1]) <= _MONUMENTS_CACHE_MAX_FALLBACK_SEC:
            log.warning(
                f"[GEO] Refetch échoué, "
                f"fallback sur cache expiré ({len(cached[0])} monuments)"
            )
            return cached[0]
        log.error(
            "[GEO] Erreur DB, pas de cache fallback disponible",
            exc_info=True,
        )
        raise


def _fetch_monument_by_id_sync(monument_id: str) -> Optional[dict]:
    """Charge un monument par ID. Synchrone."""
    sql = "SELECT * FROM monuments WHERE id = %s::numeric"
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (monument_id,))
            cols = [desc[0] for desc in cur.description]
            row = cur.fetchone()

    if not row:
        return None
    return dict(zip(cols, row))


def _fetch_monuments_for_circuit_sync(circuit_id: str) -> list[dict]:
    """
    Charge les monuments d'un circuit spécifique, dans l'ordre du circuit,
    via jointure avec tab_circuit_monument.
    Synchrone (psycopg2) — à appeler via asyncio.to_thread().
    """
    sql = """
        SELECT
            m.id_monument,
            m.nom_monument_fr,
            m.nom_monument_en,
            m.nom_monument_ar,
            m.latitude_monument,
            m.longitude_monument,
            m.description_fr,
            m.description_en,
            m.description_ar,
            m.duree_visite_en_min,
            m.statut_monument,
            m.accessibilite_monument,
            m.horaire_ouverture_ete,
            m.horaire_fermeture_ete,
            m.horaire_ouverture_hiver,
            m.horaire_fermeture_hiver,
            m.adresse_monument,
            m.importance_monument,
            tcm.ordre
        FROM tab_circuit_monument tcm
        JOIN monuments m
            ON m.id_monument = CAST(tcm.id_monument AS TEXT)
        WHERE tcm.id_circuit = %s
          AND m.latitude_monument IS NOT NULL
          AND m.longitude_monument IS NOT NULL
          AND m.latitude_monument <> ''
          AND m.longitude_monument <> ''
        ORDER BY tcm.ordre
    """
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(sql, (circuit_id,))
            cols = [desc[0] for desc in cur.description]
            rows = cur.fetchall()

    return [dict(zip(cols, row)) for row in rows]


async def _get_monuments_for_circuit_cached(
    circuit_id: str, force_refresh: bool = False
) -> list[dict]:
    """Charge les monuments d'un circuit avec cache TTL + fallback sur cache expiré."""
    now = time.monotonic()
    cached = _CIRCUIT_MONUMENTS_CACHE.get(circuit_id)

    if (
        cached is not None
        and not force_refresh
        and (now - cached[1]) <= _CIRCUIT_CACHE_TTL_SEC
    ):
        return cached[0]

    try:
        rows = await asyncio.to_thread(
            _fetch_monuments_for_circuit_sync, circuit_id
        )
        _CIRCUIT_MONUMENTS_CACHE[circuit_id] = (rows, now)
        log.info(f"[GEO] {len(rows)} monuments chargés pour circuit {circuit_id}")
        return rows
    except Exception:
        if cached is not None and (now - cached[1]) <= _CIRCUIT_CACHE_MAX_FALLBACK_SEC:
            log.warning(
                f"[GEO] Refetch échoué pour circuit {circuit_id}, "
                f"fallback sur cache expiré ({len(cached[0])} monuments)"
            )
            return cached[0]
        log.error(
            f"[GEO] Erreur DB (circuit {circuit_id}), pas de cache fallback disponible",
            exc_info=True,
        )
        raise


# ─────────────────────────────────────────────────────────────────────────────
# SERVICE PRINCIPAL
# ─────────────────────────────────────────────────────────────────────────────


class GeoService:
    """
    Service de géolocalisation terrain.

    Détecte les monuments proches de la position GPS de l'utilisateur
    et retourne leur description multilingue pour qu'Aziz puisse les présenter.
    """

    async def get_nearby_monuments(
        self,
        lat: float,
        lon: float,
        langue: str = "FR",
        rayon_override_m: Optional[int] = None,
        force_refresh: bool = False,
    ) -> list[dict]:
        """
        Retourne les monuments dans le rayon de détection autour de la position.

        Strategy :
        1. Charge tous les monuments depuis la DB (via to_thread)
        2. Calcule Haversine pour chacun
        3. Filtre par rayon, trie par distance

        Args:
            lat              : Latitude GPS de l'utilisateur
            lon              : Longitude GPS de l'utilisateur
            langue           : Code langue ("FR", "EN", "AR"...)
            rayon_override_m : Rayon custom en mètres (sinon RAYON_DEFAUT_M)

        Returns:
            Liste de dicts triés par distance croissante :
            [{
                "id": "MON-001",
                "nom": "Amphithéâtre de Carthage",
                "distance_m": 87.3,
                "description": "...",
                "duree_visite_min": 60,
                "statut": "ouvert",
                "accessibilite": "...",
                "horaires": {...},
                "adresse": "...",
                "lat": 36.856,
                "lon": 10.331,
            }]
        """
        rayon_m = min(rayon_override_m or RAYON_DEFAUT_M, RAYON_MAX_M)
        langue_key = langue.lower() if langue.lower() in ("fr", "en", "ar") else "fr"

        rows = await _get_monuments_cached(force_refresh)

        nearby = []

        for row in rows:
            lat_m = _parse_coord(row.get("latitude_monument"))
            lon_m = _parse_coord(row.get("longitude_monument"))

            if lat_m is None or lon_m is None:
                continue

            distance = haversine_m(lat, lon, lat_m, lon_m)

            if distance <= rayon_m:
                nom = row.get(f"name_{langue_key}") or row.get("name_fr") or "Monument"
                description = (
                    row.get(f"description_{langue_key}")
                    or row.get("description_fr")
                    or ""
                )

                nearby.append(
                    {
                        "id": row.get("id", ""),
                        "nom": nom,
                        "distance_m": round(distance, 1),
                        "description": description,
                        "duree_visite_min": int(row.get("visit_duration_minutes") or 0),
                        "statut": row.get("status") or "",
                        "accessibilite": row.get("accessibility") or "",
                        "importance": row.get("importance_monument") or "",
                        "horaires": {
                            "ouverture_ete": row.get("opening_time_summer") or "",
                            "fermeture_ete": row.get("closing_time_summer") or "",
                            "ouverture_hiver": row.get("opening_time_winter") or "",
                            "fermeture_hiver": row.get("closing_time_winter") or "",
                        },
                        "adresse": row.get("address") or "",
                        "lat": _parse_coord(row.get("latitude")),
                        "lon": _parse_coord(row.get("longitude")),
                    }
                )

        nearby.sort(key=lambda x: x["distance_m"])

        log.info(
            f"[GEO] Position ({lat:.4f}, {lon:.4f}) — "
            f"{len(nearby)} monument(s) dans un rayon de {rayon_m}m"
        )

        return nearby

    async def get_nearby_monuments_for_circuit(
        self,
        lat: float,
        lon: float,
        circuit_id: str,
        langue: str = "FR",
        rayon_override_m: Optional[int] = None,
        force_refresh: bool = False,
    ) -> list[dict]:
        """
        Version scopée de get_nearby_monuments : ne considère que les monuments
        appartenant au circuit actif (via tab_circuit_monument).
        """
        rayon_m = min(rayon_override_m or RAYON_DEFAUT_M, RAYON_MAX_M)
        langue_key = langue.lower() if langue.lower() in ("fr", "en", "ar") else "fr"

        rows = await _get_monuments_for_circuit_cached(circuit_id, force_refresh)

        nearby = []
        for row in rows:
            lat_m = _parse_coord(row.get("latitude_monument"))
            lon_m = _parse_coord(row.get("longitude_monument"))
            if lat_m is None or lon_m is None:
                continue

            distance = haversine_m(lat, lon, lat_m, lon_m)
            if distance <= rayon_m:
                nom = (
                    row.get(f"name_{langue_key}")
                    or row.get("name_fr")
                    or "Monument"
                )
                description = (
                    row.get(f"description_{langue_key}")
                    or row.get("description_fr")
                    or ""
                )

                nearby.append(
                    {
                        "id": row.get("id_monument", ""),
                        "nom": nom,
                        "distance_m": round(distance, 1),
                        "description": description,
                        "duree_visite_min": int(row.get("duree_visite_en_min") or 0),
                        "statut": row.get("statut_monument") or "",
                        "accessibilite": row.get("accessibilite_monument") or "",
                        "importance": row.get("importance_monument") or "",
                        "ordre": row.get("ordre"),
                        "horaires": {
                            "ouverture_ete": row.get("horaire_ouverture_ete") or "",
                            "fermeture_ete": row.get("horaire_fermeture_ete") or "",
                            "ouverture_hiver": row.get("horaire_ouverture_hiver") or "",
                            "fermeture_hiver": row.get("horaire_fermeture_hiver") or "",
                        },
                        "adresse": row.get("adresse_monument") or "",
                        "lat": lat_m,
                        "lon": lon_m,
                    }
                )

        nearby.sort(key=lambda x: x["distance_m"])
        return nearby

    def get_nearby_from_stops(
        self,
        lat: float,
        lon: float,
        stops: list[dict],
        rayon_m: int = 100,
    ) -> list[dict]:
        """
        Détection de proximité sur une liste d'étapes déjà en mémoire
        (circuit généré par le wizard, absent de tab_circuit_monument).
        Haversine pure, aucun accès DB.
        """
        rayon_m = min(rayon_m, RAYON_MAX_M)
        nearby: list[dict] = []
        for stop in stops:
            lat_raw = stop.get("latitude")
            lon_raw = stop.get("longitude")
            if lat_raw is None or lon_raw is None:
                continue
            try:
                lat_m, lon_m = float(lat_raw), float(lon_raw)
            except (TypeError, ValueError):
                continue
            distance = haversine_m(lat, lon, lat_m, lon_m)
            if distance <= rayon_m:
                nearby.append(
                    {
                        "id": str(stop.get("monument_id") or ""),
                        "nom": stop.get("name") or "Monument",
                        "distance_m": round(distance, 1),
                        "ordre": stop.get("order"),
                        "lat": lat_m,
                        "lon": lon_m,
                    }
                )
        nearby.sort(key=lambda x: x["distance_m"])
        return nearby

    async def get_monument_by_id(
        self, monument_id: str, langue: str = "FR"
    ) -> Optional[dict]:
        """
        Récupère un monument spécifique par son ID.
        Utile quand l'orchestrateur veut approfondir un monument déjà détecté.
        """
        langue_key = langue.lower() if langue.lower() in ("fr", "en", "ar") else "fr"

        try:
            row = await asyncio.to_thread(_fetch_monument_by_id_sync, monument_id)
        except Exception as e:
            log.error(f"[GEO] Erreur get_monument_by_id({monument_id}) : {e}")
            return None

        if not row:
            return None

        nom = row.get(f"name_{langue_key}") or row.get("name_fr") or "Monument"
        description = (
            row.get(f"description_{langue_key}") or row.get("description_fr") or ""
        )

        return {
            "id": row.get("id", ""),
            "nom": nom,
            "description": description,
            "duree_visite_min": int(row.get("visit_duration_minutes") or 0),
            "statut": row.get("status") or "",
            "accessibilite": row.get("accessibility") or "",
            "horaires": {
                "ouverture_ete": row.get("opening_time_summer") or "",
                "fermeture_ete": row.get("closing_time_summer") or "",
                "ouverture_hiver": row.get("opening_time_winter") or "",
                "fermeture_hiver": row.get("closing_time_winter") or "",
            },
            "adresse": row.get("address") or "",
            "lat": _parse_coord(row.get("latitude")),
            "lon": _parse_coord(row.get("longitude")),
        }


# ─────────────────────────────────────────────────────────────────────────────
# INSTANCE GLOBALE (singleton)
# ─────────────────────────────────────────────────────────────────────────────

_geo_service_instance: Optional[GeoService] = None


def get_geo_service() -> GeoService:
    """Retourne l'instance singleton du GeoService."""
    global _geo_service_instance
    if _geo_service_instance is None:
        _geo_service_instance = GeoService()
    return _geo_service_instance


# ─────────────────────────────────────────────────────────────────────────────
# TEST RAPIDE (CLI)
# ─────────────────────────────────────────────────────────────────────────────


async def _test():
    """Test rapide — position : Colline de Byrsa, Carthage."""
    service = get_geo_service()

    # Test Haversine seul
    dist = haversine_m(36.8565, 10.3310, 36.8572, 10.3314)
    print(f"\n[TEST] Haversine Byrsa → Maison de la Basilique : {dist:.1f}m")

    # Test DB
    print(f"\n[TEST] get_nearby_monuments(36.8565, 10.3310, rayon=300m) :")
    monuments = await service.get_nearby_monuments(
        lat=36.8565, lon=10.3310, langue="FR", rayon_override_m=300
    )

    if not monuments:
        print("  Aucun monument trouvé dans ce rayon.")
    else:
        for m in monuments:
            print(f"  ✓ {m['nom']} — {m['distance_m']}m")
            print(f"    Durée : {m['duree_visite_min']} min | Statut : {m['statut']}")
            if m["description"]:
                print(f"    Description : {m['description'][:120]}...")
            print()


if __name__ == "__main__":
    asyncio.run(_test())
