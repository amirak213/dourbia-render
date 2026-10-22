"""
Weather Tools — Enregistrement via @registry.register
Chaque tool est une fonction pure, testable indépendamment.
"""

from __future__ import annotations

import threading
import httpx
from datetime import datetime

from tools.registry import ToolRegistry

# Instance globale du registre
registry = ToolRegistry()

# ──────────────────────────────────────────────────────────────
# CONSTANTES
# ──────────────────────────────────────────────────────────────

OPEN_METEO_URL = "https://api.open-meteo.com/v1/forecast"
GEO_URL        = "https://geocoding-api.open-meteo.com/v1/search"
HTTP_TIMEOUT   = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)

WMO_CODES = {
    0: "Ciel dégagé", 1: "Principalement dégagé", 2: "Partiellement nuageux",
    3: "Couvert", 45: "Brouillard", 48: "Brouillard givrant",
    51: "Bruine légère", 53: "Bruine modérée", 55: "Bruine dense",
    61: "Pluie légère", 63: "Pluie modérée", 65: "Pluie forte",
    71: "Neige légère", 73: "Neige modérée", 75: "Neige forte",
    80: "Averses légères", 81: "Averses modérées", 82: "Averses violentes",
    95: "Orage", 96: "Orage avec grêle", 99: "Orage avec grêle forte",
}

# Cache géocodage thread-safe
_geocode_cache: dict[str, dict] = {}
_cache_lock = threading.Lock()

# Lieux tunisiens ambigus (évite Carthage MO, etc.)
_LIEUX_TUNISIE_CONNUS: dict[str, dict] = {
    "carthage": {"lat": 36.8528, "lon": 10.3233, "display": "Carthage, Ariana, Tunisie"},
    "cathage": {"lat": 36.8528, "lon": 10.3233, "display": "Carthage, Ariana, Tunisie"},
    "tunis": {"lat": 36.81897, "lon": 10.16579, "display": "Tunis, Tunisie"},
    "sidi bou said": {"lat": 36.8707, "lon": 10.3414, "display": "Sidi Bou Saïd, Tunisie"},
    "sidi bou saïd": {"lat": 36.8707, "lon": 10.3414, "display": "Sidi Bou Saïd, Tunisie"},
    "la marsa": {"lat": 36.8781, "lon": 10.3247, "display": "La Marsa, Tunisie"},
    "sousse": {"lat": 35.8256, "lon": 10.63699, "display": "Sousse, Tunisie"},
    "sfax": {"lat": 34.7406, "lon": 10.7603, "display": "Sfax, Tunisie"},
    "djerba": {"lat": 33.8076, "lon": 10.8451, "display": "Djerba, Tunisie"},
    "kairouan": {"lat": 35.6781, "lon": 10.0963, "display": "Kairouan, Tunisie"},
    "monastir": {"lat": 35.7643, "lon": 10.8113, "display": "Monastir, Tunisie"},
    "mahdia": {"lat": 35.5047, "lon": 11.0622, "display": "Mahdia, Tunisie"},
    "hammamet": {"lat": 36.4, "lon": 10.6167, "display": "Hammamet, Tunisie"},
    "nabeul": {"lat": 36.4561, "lon": 10.7376, "display": "Nabeul, Tunisie"},
    "bizerte": {"lat": 37.2744, "lon": 9.8739, "display": "Bizerte, Tunisie"},
    "tozeur": {"lat": 33.9197, "lon": 8.1335, "display": "Tozeur, Tunisie"},
    "douz": {"lat": 33.4657, "lon": 9.0203, "display": "Douz, Tunisie"},
    "el jem": {"lat": 35.2964, "lon": 10.7069, "display": "El Jem, Tunisie"},
    "dougga": {"lat": 36.4225, "lon": 9.2264, "display": "Dougga, Tunisie"},
    "tabarka": {"lat": 36.9544, "lon": 8.7585, "display": "Tabarka, Tunisie"},
}

_ORTHOGRAPHIE_LIEUX = {
    "cathage": "carthage",
    "cartage": "carthage",
    "sidibousaid": "sidi bou said",
    "sidi bousaid": "sidi bou said",
    "medina": "tunis",
    "médina": "tunis",
}


def _normaliser_lieu(place: str) -> str:
    """Corrige les typos courantes et normalise le nom du lieu."""
    key = place.lower().strip()
    key = key.replace("'", "'").replace("  ", " ")
    return _ORTHOGRAPHIE_LIEUX.get(key, key)


# ──────────────────────────────────────────────────────────────
# GÉOCODAGE — avec erreur explicite (plus de fallback silencieux)
# ──────────────────────────────────────────────────────────────

def geocode(place: str) -> dict:
    """
    Géocode une ville tunisienne.
    LÈVE une exception explicite si introuvable — jamais de fallback hors Tunisie.
    """
    normalise = _normaliser_lieu(place)
    key = normalise.lower().strip()
    with _cache_lock:
        if key in _geocode_cache:
            return _geocode_cache[key]

    if key in _LIEUX_TUNISIE_CONNUS:
        result = dict(_LIEUX_TUNISIE_CONNUS[key])
        with _cache_lock:
            _geocode_cache[key] = result
        return result

    search_name = place.strip()
    if "tunis" not in search_name.lower() and "tunisia" not in search_name.lower():
        search_name = f"{place.strip()}, Tunisia"

    try:
        with httpx.Client(timeout=HTTP_TIMEOUT) as c:
            r = c.get(GEO_URL, params={
                "name": search_name, "count": 10,
                "language": "fr", "format": "json",
            })
            r.raise_for_status()
            results = r.json().get("results", [])
    except httpx.TimeoutException:
        raise TimeoutError(f"Géocodage timeout pour '{place}' — réessaie dans un moment.")
    except httpx.HTTPError as e:
        raise ConnectionError(f"Erreur réseau géocodage : {e}")

    if not results:
        raise ValueError(
            f"Ville introuvable en Tunisie : '{place}'. "
            "Vérifie l'orthographe ou essaie une ville voisine."
        )

    tn = [x for x in results if x.get("country_code", "").strip().upper() == "TN"]

    if not tn:
        raise ValueError(
            f"Lieu '{place}' introuvable en Tunisie. "
            "Précisez la ville tunisienne (ex: Carthage, Tunis, Sousse)."
        )

    best = tn[0]

    parts = [best.get("name", place)]
    if best.get("admin1"):
        parts.append(best["admin1"])
    if best.get("country"):
        parts.append(best["country"])

    result = {
        "lat": best["latitude"],
        "lon": best["longitude"],
        "display": ", ".join(parts),
    }
    with _cache_lock:
        _geocode_cache[key] = result
    return result


# ──────────────────────────────────────────────────────────────
# ALERTES
# ──────────────────────────────────────────────────────────────

def compute_alert(temp_max: float, rain_pct: float, wind_kmh: float, description: str) -> dict:
    rouge = []
    if temp_max >= 38:    rouge.append(f"canicule ({temp_max:.0f}°C)")
    if rain_pct >= 80:    rouge.append(f"fortes précipitations ({rain_pct:.0f}%)")
    if wind_kmh >= 60:    rouge.append(f"vent violent ({wind_kmh:.0f} km/h)")
    if any(w in description.lower() for w in ["orage","grêle","violentes"]):
        rouge.append(f"conditions dangereuses ({description})")

    if rouge:
        return {"level": "ROUGE", "outdoor_ok": False,
                "reason": "Conditions dangereuses : " + ", ".join(rouge),
                "advice": [
                    "Évitez toute sortie non essentielle.",
                    "Restez dans un lieu climatisé ou abrité.",
                    "Consultez les alertes météo officielles (météo.tn).",
                ]}

    orange = []
    if temp_max >= 32:    orange.append(f"chaleur élevée ({temp_max:.0f}°C)")
    if rain_pct >= 40:    orange.append(f"risque de pluie ({rain_pct:.0f}%)")
    if wind_kmh >= 35:    orange.append(f"vent fort ({wind_kmh:.0f} km/h)")

    if orange:
        return {"level": "ORANGE", "outdoor_ok": True,
                "reason": "Conditions difficiles : " + ", ".join(orange),
                "advice": [
                    "Sortez tôt le matin ou en fin d'après-midi.",
                    "Évitez l'exposition directe au soleil entre 12h et 16h.",
                    "Hydratez-vous davantage.",
                ]}

    return {"level": "VERT", "outdoor_ok": True,
            "reason": "Conditions favorables.",
            "advice": ["Bonne journée pour les activités en plein air."]}


def wmo(code: int) -> str:
    return WMO_CODES.get(code, f"Code météo {code}")


# ──────────────────────────────────────────────────────────────
# TOOLS ENREGISTRÉS
# ──────────────────────────────────────────────────────────────

@registry.register(
    name="get_weather",
    description=(
        "Météo actuelle UNIQUEMENT pour 'maintenant', 'en ce moment', 'aujourd'hui'. "
        "Retourne température, vent, humidité et alerte VERT/ORANGE/ROUGE."
    ),
    parameters={
        "type": "object",
        "properties": {
            "city_name": {
                "type": "string",
                "description": "Nom du lieu. Ex: Carthage, Djerba, Sidi Bou Said."
            }
        },
        "required": ["city_name"],
    },
)
def get_weather(city_name: str) -> dict:
    coords = geocode(city_name)

    with httpx.Client(timeout=HTTP_TIMEOUT) as c:
        r = c.get(OPEN_METEO_URL, params={
            "latitude":  coords["lat"],
            "longitude": coords["lon"],
            "current":   (
                "temperature_2m,apparent_temperature,relative_humidity_2m,"
                "wind_speed_10m,wind_direction_10m,weather_code,"
                "surface_pressure,cloud_cover,precipitation"
            ),
            "daily":         "sunrise,sunset,temperature_2m_max,precipitation_probability_max",
            "timezone":      "Africa/Tunis",
            "forecast_days": 1,
            "models":        "ecmwf_ifs025",
        })
        r.raise_for_status()
        data = r.json()

    cd        = data["current"]
    daily     = data.get("daily", {})
    temp_max  = daily.get("temperature_2m_max", [cd["temperature_2m"]])[0]
    rain_max  = daily.get("precipitation_probability_max", [0])[0] or 0
    sunrise   = (daily.get("sunrise", ["N/A"])[0] or "").split("T")[-1] or "N/A"
    sunset    = (daily.get("sunset",  ["N/A"])[0] or "").split("T")[-1] or "N/A"

    alert = compute_alert(
        temp_max    = temp_max,
        rain_pct    = float(rain_max),
        wind_kmh    = cd["wind_speed_10m"],
        description = wmo(cd["weather_code"]),
    )

    return {
        "lieu":              coords["display"],
        "temperature_c":     cd["temperature_2m"],
        "ressenti_c":        cd["apparent_temperature"],
        "humidite_pct":      cd["relative_humidity_2m"],
        "vent_kmh":          cd["wind_speed_10m"],
        "direction_deg":     cd["wind_direction_10m"],
        "description":       wmo(cd["weather_code"]),
        "nuages_pct":        cd["cloud_cover"],
        "precipitation_mm":  cd["precipitation"],
        "pression_hpa":      cd["surface_pressure"],
        "lever_soleil":      sunrise,
        "coucher_soleil":    sunset,
        "alerte":            alert,
        "source":            "ECMWF IFS 0.25°",
    }


@registry.register(
    name="get_forecast",
    description=(
        "Prévisions météo pour tout moment FUTUR : demain, après-demain, ce week-end, "
        "cette semaine, lundi, samedi... Inclut alerte VERT/ORANGE/ROUGE par jour."
    ),
    parameters={
        "type": "object",
        "properties": {
            "city_name":  {"type": "string"},
            "days":       {"type": "integer", "default": 3, "minimum": 1, "maximum": 7},
            "target_day": {
                "type": ["string", "null"],
                "description": "Jour précis : 'demain', 'après-demain', 'samedi'... Null si plage.",
            },
        },
        "required": ["city_name"],
    },
)
def get_forecast(city_name: str, days: int = 3, target_day: str | None = None) -> dict:
    # Nettoyage défensif
    if target_day and str(target_day).lower().strip() in ("", "null", "none"):
        target_day = None
    try:
        days = max(1, min(int(days or 3), 7))
    except (TypeError, ValueError):
        days = 3

    coords = geocode(city_name)

    with httpx.Client(timeout=HTTP_TIMEOUT) as c:
        r = c.get(OPEN_METEO_URL, params={
            "latitude":  coords["lat"],
            "longitude": coords["lon"],
            "daily": (
                "weather_code,temperature_2m_max,temperature_2m_min,"
                "apparent_temperature_max,apparent_temperature_min,"
                "precipitation_sum,wind_speed_10m_max,"
                "wind_direction_10m_dominant,sunrise,sunset,"
                "precipitation_probability_max"
            ),
            "hourly":        "precipitation_probability,temperature_2m",
            "timezone":      "Africa/Tunis",
            "forecast_days": min(days + 1, 8),
            "models":        "ecmwf_ifs025",
        })
        r.raise_for_status()
        data  = r.json()
        daily = data["daily"]

    hourly_prob = data["hourly"]["precipitation_probability"]
    hourly_temp = data["hourly"]["temperature_2m"]
    hourly_time = data["hourly"]["time"]

    # Index par date pour accès O(1)
    prob_by: dict[str, dict[int, int]]   = {}
    temp_by: dict[str, dict[int, float]] = {}
    for t, p, tmp in zip(hourly_time, hourly_prob, hourly_temp):
        dk = t[:10]; h = int(t[11:13])
        if p   is not None: prob_by.setdefault(dk, {})[h] = p
        if tmp is not None: temp_by.setdefault(dk, {})[h] = tmp

    def mean_prob(date_str: str) -> int:
        vals = list(prob_by.get(date_str, {}).values())
        return round(sum(vals) / len(vals)) if vals else 0

    def best_window(date_str: str) -> tuple[str, str]:
        probs = prob_by.get(date_str, {})
        temps = temp_by.get(date_str, {})
        best_score, best_start = float("inf"), 8
        for start in range(6, 20):
            window     = [start, start+1, start+2]
            rain_score = sum(probs.get(h, 50) for h in window)
            avg_temp   = sum(temps.get(h, 22) for h in window) / 3
            penalty    = max(0, avg_temp - 35) * 5 + max(0, 10 - avg_temp) * 5
            score      = rain_score + penalty
            if score < best_score:
                best_score, best_start = score, start
        label    = f"{best_start:02d}h–{best_start+3:02d}h"
        avg_rain = sum(probs.get(h, 50) for h in [best_start, best_start+1, best_start+2]) / 3
        conseil  = (
            f"Privilégiez {label} : ciel clément." if avg_rain < 20
            else f"Sortez de préférence {label}, créneau le moins pluvieux." if avg_rain < 50
            else f"Météo difficile toute la journée ; tentez {label} si nécessaire."
        )
        return label, conseil

    DAY_FR = {0:"Lundi",1:"Mardi",2:"Mercredi",3:"Jeudi",4:"Vendredi",5:"Samedi",6:"Dimanche"}
    TARGET_MAP = {
        "lundi":0,"mardi":1,"mercredi":2,"jeudi":3,
        "vendredi":4,"samedi":5,"dimanche":6,
    }

    td_lower  = (target_day or "").lower().strip()
    is_demain = td_lower == "demain"
    is_apres  = td_lower == "après-demain"
    target_wd = TARGET_MAP.get(td_lower) if not is_demain and not is_apres else None

    forecast = []
    for i in range(1, len(daily["time"])):
        d     = datetime.strptime(daily["time"][i], "%Y-%m-%d")
        label = "Demain" if i==1 else ("Après-demain" if i==2 else DAY_FR[d.weekday()])

        if is_demain    and i != 1:                     continue
        if is_apres     and i != 2:                     continue
        if target_wd is not None and d.weekday() != target_wd: continue

        dk      = daily["time"][i]
        rain    = mean_prob(dk)
        wl, wc  = best_window(dk)
        tmax    = daily["temperature_2m_max"][i]
        vmax    = daily["wind_speed_10m_max"][i]
        pmax    = daily.get("precipitation_probability_max", [0]*10)[i] or rain

        alert = compute_alert(
            temp_max=tmax, rain_pct=float(pmax),
            wind_kmh=vmax, description=wmo(daily["weather_code"][i]),
        )

        forecast.append({
            "jour":               label,
            "date":               d.strftime("%d/%m/%Y"),
            "description":        wmo(daily["weather_code"][i]),
            "temp_max_c":         tmax,
            "temp_min_c":         daily["temperature_2m_min"][i],
            "ressenti_max_c":     daily["apparent_temperature_max"][i],
            "ressenti_min_c":     daily["apparent_temperature_min"][i],
            "precipitation_mm":   daily["precipitation_sum"][i],
            "chance_pluie_pct":   rain,
            "vent_max_kmh":       vmax,
            "lever_soleil":       daily["sunrise"][i].split("T")[1],
            "coucher_soleil":     daily["sunset"][i].split("T")[1],
            "meilleur_creneau":   wl,
            "conseil":            wc,
            "alerte":             alert,
        })

    return {
        "lieu":    coords["display"],
        "previsions": forecast,
        "filtre":  target_day or f"{days} prochains jours",
        "source":  "ECMWF IFS 0.25°",
    }


@registry.register(
    name="compare_cities",
    description="Compare la météo actuelle entre deux villes tunisiennes avec niveaux d'alerte.",
    parameters={
        "type": "object",
        "properties": {
            "city1": {"type": "string"},
            "city2": {"type": "string"},
        },
        "required": ["city1", "city2"],
    },
)
def compare_cities(city1: str, city2: str) -> dict:
    results = {}
    for city in [city1, city2]:
        coords = geocode(city)
        with httpx.Client(timeout=HTTP_TIMEOUT) as c:
            r = c.get(OPEN_METEO_URL, params={
                "latitude":  coords["lat"],
                "longitude": coords["lon"],
                "current":   (
                    "temperature_2m,apparent_temperature,weather_code,"
                    "wind_speed_10m,relative_humidity_2m,cloud_cover,precipitation"
                ),
                "daily":         "temperature_2m_max,precipitation_probability_max",
                "timezone":      "Africa/Tunis",
                "forecast_days": 1,
                "models":        "ecmwf_ifs025",
            })
            r.raise_for_status()
            data  = r.json()
            cd    = data["current"]
            daily = data.get("daily", {})

        tmax  = daily.get("temperature_2m_max", [cd["temperature_2m"]])[0]
        pmax  = daily.get("precipitation_probability_max", [0])[0] or 0
        alert = compute_alert(
            temp_max=float(tmax), rain_pct=float(pmax),
            wind_kmh=cd["wind_speed_10m"], description=wmo(cd["weather_code"]),
        )
        results[coords["display"]] = {
            "temperature_c":    cd["temperature_2m"],
            "ressenti_c":       cd["apparent_temperature"],
            "description":      wmo(cd["weather_code"]),
            "vent_kmh":         cd["wind_speed_10m"],
            "humidite_pct":     cd["relative_humidity_2m"],
            "nuages_pct":       cd["cloud_cover"],
            "precipitation_mm": cd["precipitation"],
            "alerte":           alert,
        }
    return results
