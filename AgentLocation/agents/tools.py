from __future__ import annotations
import asyncio, hashlib, json, logging, os, random, re, secrets, string, unicodedata
from datetime import date as _date, datetime, timedelta
from typing import Any, Optional
import httpx
from core.config import settings
from core.infra import get_pool, record_to_dict, _NULL_STRINGS, cb_scraping, with_retry
from core.types import ClientProfile, ReservationRequest

log = logging.getLogger("dourbia.tools")
try:
    from bs4 import BeautifulSoup as _BS

    SCRAPING_AVAILABLE = True
except ImportError:
    BeautifulSoup = None
    SCRAPING_AVAILABLE = False


CATEGORIE_MAP = {"desert":"Désert/Sahari","sahari":"Désert/Sahari","4x4":"Désert/Sahari",
    "electrique":"Électrique","ecolo":"Électrique","economique":"Économique","pas cher":"Économique",
    "confort":"Confort","affaires":"Confort","familiale":"Familiale","famille":"Familiale",
    "luxe":"Luxe","premium":"Luxe","utilitaire":"Utilitaire"}

def _norm(s):
    return unicodedata.normalize("NFD",s.lower()).encode("ascii","ignore").decode("ascii") if s else ""

# Alias : quartiers/banlieues → ville du dataset la plus proche
_VILLE_ALIAS = {
    "la goulette": "Tunis",
    "goulette": "Tunis",
    "carthage": "Tunis",
    "sidi bou said": "Tunis",
    "la marsa": "Tunis",
    "le kram": "Tunis",
    "el aouina": "Tunis",
    "ariana": "Tunis",
    "la soukra": "Tunis",
    "manouba": "Tunis",
    "ben arous": "Tunis",
    "hammam lif": "Tunis",
    "rades": "Tunis",
}

def _resoudre_ville(ville: str) -> str:
    """Résout un quartier/banlieue vers la ville du dataset."""
    if not ville:
        return ville
    norm = _norm(ville).strip()
    return _VILLE_ALIAS.get(norm, ville)

def generer_id():
    return f"RES-{''.join(random.choices(string.ascii_uppercase+string.digits,k=6))}"

def _parse_date(s):
    if isinstance(s,_date): return s
    val = str(s).strip()
    if re.match(r"^\d{1,2}[-/.]\d{1,2}$", val):
        sep = "-" if "-" in val else ("/" if "/" in val else ".")
        val = f"{val}{sep}{_date.today().year}"
        
    for fmt in ("%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d"):
        try: return datetime.strptime(val,fmt).date()
        except: continue
    raise ValueError(f"Format de date non supporté: {s}")

async def est_disponible(pool, voiture_id, date_debut, date_fin):
    row = await pool.fetchrow("SELECT id FROM reservations WHERE voiture_id=$1 AND statut IN ('EN_ATTENTE','CONFIRMEE') AND date_debut<$2 AND date_fin>$3",
                               voiture_id, _parse_date(date_fin), _parse_date(date_debut))
    return row is None

async def _scorer(pool, v, prix_max=None, date_debut=None, date_fin=None):
    score=0.0; prix=float(v.get("prix_jour") or 0)
    if prix_max and prix>0:
        r=prix/prix_max; score+=30*min(r/0.85,1.0) if r<=1.0 else 0
    elif prix>0: score+=30*max(0,1-prix/200)
    score+=25*(float(v.get("note_client") or 0)/5.0)
    if date_debut and date_fin:
        score+=20 if await est_disponible(pool,v["id"],date_debut,date_fin) else 0
    else: score+=10
    if v.get("climatisation"): score+=10
    score+=10*(min(int(v.get("nb_reservations") or 0),50)/50)
    if v.get("electrique"): score+=5
    return round(score,2)

async def _signal_rarete(pool, v, date_debut=None, date_fin=None):
    s=[]; nb=int(v.get("nb_reservations") or 0); note=float(v.get("note_client") or 0)
    if nb>20: s.append(f"Bestseller — {nb} locations !")
    elif nb>10: s.append(f"Très populaire ({nb} locations).")
    if note>=4.8: s.append("Note parfaite ⭐.")
    elif note>=4.5: s.append(f"Note {note}/5.")
    return " ".join(s)

async def rechercher_voitures(categorie=None, prix_max=None, places_min=None, date_debut=None,
                               date_fin=None, electrique=None, ville=None, transmission=None,
                               climatisation=None, marque=None, couleur=None, annee_min=None,
                               kilometrage_max=None, carburant=None, portes_min=None, caution_max=None):
    pool=await get_pool(); clauses=[]; params=[]; i=1
    def add(clause,val):
        nonlocal i; clauses.append(clause.replace("?",f"${i}")); params.append(val); i+=1
    
    if date_debut and date_fin:
        clauses.append(f"""(disponible=TRUE OR id IN (
            SELECT voiture_id FROM reservations 
            WHERE statut='CONFIRMEE' AND date_debut <= CURRENT_DATE AND date_fin >= CURRENT_DATE
        ))""")
        clauses.append(f"""id NOT IN (
            SELECT voiture_id FROM reservations
            WHERE statut IN ('EN_ATTENTE', 'CONFIRMEE')
              AND date_debut < ${i+1} AND date_fin > ${i}
        )""")
        params.append(_parse_date(date_debut))
        params.append(_parse_date(date_fin))
        i += 2
    else:
        clauses.append("disponible=TRUE")

    if categorie:
        cat_norm = _norm(categorie)
        if "electrique" in cat_norm or "electri" in cat_norm:
            clauses.append(f"(electrique=TRUE OR categorie ILIKE ${i} OR carburant ILIKE ${i})")
            params.append(f"%{categorie}%"); i+=1
            electrique = None
        else:
            clauses.append(f"(categorie ILIKE ${i} OR carburant ILIKE ${i})")
            params.append(f"%{categorie}%"); i+=1
    if marque: add("LOWER(marque) LIKE LOWER(?)",f"%{_norm(marque)}%")
    if prix_max: add("prix_jour<=?",prix_max)
    if places_min: add("places>=?",places_min)
    if electrique is not None: add("electrique=?",electrique)
    if ville: add("LOWER(ville) LIKE ?",f"%{_norm(ville)}%")
    if transmission: add("LOWER(transmission)=LOWER(?)",transmission)
    if climatisation is not None: add("climatisation=?",climatisation)
    if couleur: add("LOWER(couleur)=LOWER(?)",couleur)
    if annee_min: add("annee>=?",annee_min)
    if kilometrage_max: add("kilometrage<=?",kilometrage_max)
    if carburant: add("LOWER(carburant)=LOWER(?)",carburant)
    if portes_min: add("portes>=?",portes_min)
    if caution_max: add("caution<=?",caution_max)
    sql=f"SELECT * FROM voitures WHERE {' AND '.join(clauses)} ORDER BY note_client DESC LIMIT 15"
    nb_jours=None
    if date_debut and date_fin:
        try: nb_jours=(datetime.strptime(date_fin,"%Y-%m-%d")-datetime.strptime(date_debut,"%Y-%m-%d")).days
        except: pass
    rows=await pool.fetch(sql,*params)
    async def enrich(row):
        v=record_to_dict(row)
        v["score_composite"]=await _scorer(pool,v,prix_max=prix_max,date_debut=date_debut,date_fin=date_fin)
        v["prix_total_sejour"]=round(nb_jours*float(v["prix_jour"]),2) if nb_jours and v.get("prix_jour") else None
        v["signal_rarete"]=await _signal_rarete(pool,v,date_debut,date_fin)
        return v
    cands=await asyncio.gather(*[enrich(r) for r in rows])
    cands.sort(key=lambda x:x["score_composite"],reverse=True)
    return {"succes":True,"nombre":len(cands[:3]),"nb_jours":nb_jours,"voitures":cands[:3]}

async def reserver_voiture_fn(voiture_id,client_nom,client_tel,client_email,date_debut,date_fin):
    try:
        req=ReservationRequest(voiture_id=voiture_id,client_nom=client_nom,client_tel=client_tel,
                               client_email=client_email,date_debut=date_debut,date_fin=date_fin)
    except Exception as e: return {"succes":False,"erreur":str(e)}
    pool=await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            v=record_to_dict(await conn.fetchrow("SELECT * FROM voitures WHERE id=$1 FOR UPDATE",req.voiture_id))
            if not v: return {"succes":False,"erreur":f"Voiture {req.voiture_id} introuvable."}
            if not v.get("disponible"): return {"succes":False,"erreur":"Voiture non disponible."}
            if await conn.fetchrow("SELECT id FROM reservations WHERE voiture_id=$1 AND statut IN ('EN_ATTENTE','CONFIRMEE') AND date_debut<$2 AND date_fin>$3",
                                    req.voiture_id,_parse_date(req.date_fin),_parse_date(req.date_debut)):
                return {"succes":False,"erreur":f"Voiture déjà réservée du {req.date_debut} au {req.date_fin}."}
            nb=(datetime.strptime(req.date_fin,"%Y-%m-%d")-datetime.strptime(req.date_debut,"%Y-%m-%d")).days
            if nb<=0: return {"succes":False,"erreur":"Date de fin doit être après date de début."}
            rid=generer_id(); token=secrets.token_urlsafe(32)
            prix_total=round(nb*float(v["prix_jour"]),2)
            expires=datetime.utcnow()+timedelta(hours=settings.token_expiry_hours)
            resa={"id":rid,"client_nom":req.client_nom,"client_tel":req.client_tel,
                  "client_email":req.client_email,"voiture_id":req.voiture_id,
                  "voiture_details":f"{v['marque']} {v['modele']} ({v.get('annee','')})",
                  "voiture_categorie":v.get("categorie",""),"voiture_immat":v.get("immatriculation",""),
                  "voiture_agence":v.get("agence",""),"voiture_ville":v.get("ville",""),
                  "voiture_extras":v.get("extras",""),"voiture_electrique":bool(v.get("electrique",False)),
                  "date_debut":req.date_debut,"date_fin":req.date_fin,"nb_jours":nb,
                  "prix_jour":float(v["prix_jour"]),"caution":float(v.get("caution") or 0),
                  "prix_total":prix_total,"statut":"EN_ATTENTE"}
            await conn.execute("""INSERT INTO reservations
                (id,type,client_nom,client_tel,client_email,voiture_id,voiture_details,
                voiture_categorie,voiture_immat,voiture_agence,voiture_ville,voiture_extras,
                voiture_electrique,date_debut,date_fin,nb_jours,prix_jour,caution,prix_total,statut)
                VALUES ($1,'voiture',$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15,$16,$17,$18,$19)""",
                rid,req.client_nom,req.client_tel,req.client_email,req.voiture_id,
                resa["voiture_details"],resa["voiture_categorie"],resa["voiture_immat"],
                resa["voiture_agence"],resa["voiture_ville"],resa["voiture_extras"],
                resa["voiture_electrique"],_parse_date(req.date_debut),_parse_date(req.date_fin),
                nb,float(v["prix_jour"]),float(v.get("caution") or 0),prix_total,"EN_ATTENTE")
            await conn.execute("INSERT INTO tokens_confirmation (token,reservation_id,expires_at) VALUES ($1,$2,$3)",
                               token,rid,expires)
    try:
        from email_service import envoyer_email_proprietaire_attente
        envoyer_email_proprietaire_attente(resa,token)
    except Exception as e: log.warning(f"[EMAIL] proprietaire : {e}")
    log.info(f"[RESA] {rid} créée — {req.client_nom}")
    return {"succes":True,"message":"Demande EN_ATTENTE — email envoyé au propriétaire.",
            "reservation_id":rid,"statut":"EN_ATTENTE","prix_total":prix_total,"nb_jours":nb}

async def annuler_reservation_client(reservation_id, client_nom=None):
    pool=await get_pool()
    async with pool.acquire() as conn:
        async with conn.transaction():
            r=record_to_dict(await conn.fetchrow("SELECT * FROM reservations WHERE id=$1 FOR UPDATE",reservation_id))
            if not r: return {"succes":False,"erreur":f"Réservation {reservation_id} introuvable."}
            if r["statut"] in ("ANNULEE","REFUSEE"): return {"succes":False,"erreur":f"Déjà {r['statut'].lower()}."}
            if client_nom and _norm(client_nom) not in _norm(r.get("client_nom","")): return {"succes":False,"erreur":"Nom incorrect."}
            await conn.execute("UPDATE reservations SET statut='ANNULEE',updated_at=NOW() WHERE id=$1",reservation_id)
            await conn.execute("""
                UPDATE voitures SET disponible = TRUE, updated_at = NOW()
                WHERE id = $1 AND disponible = FALSE AND NOT EXISTS (
                    SELECT 1 FROM reservations
                    WHERE voiture_id = $1 AND statut = 'CONFIRMEE' AND id != $2
                      AND date_debut <= CURRENT_DATE AND date_fin >= CURRENT_DATE
                )
            """, r["voiture_id"], r["id"])
            await conn.execute("DELETE FROM tokens_confirmation WHERE reservation_id=$1",reservation_id)
            await conn.execute("DELETE FROM tokens_annulation WHERE reservation_id=$1",reservation_id)
    try:
        from email_service import envoyer_email_annulation_client
        envoyer_email_annulation_client(r,source="client")
    except Exception as e: log.warning(f"[EMAIL] annulation : {e}")
    return {"succes":True,"message":f"Réservation {reservation_id} annulée."}

async def consulter_reservations(client_nom=None):
    pool=await get_pool()
    if client_nom:
        rows=await pool.fetch("SELECT * FROM reservations WHERE LOWER(client_nom) LIKE LOWER($1) ORDER BY date_reservation DESC",f"%{client_nom}%")
    else:
        rows=await pool.fetch("SELECT * FROM reservations ORDER BY date_reservation DESC LIMIT 100")
    return {"succes":True,"nombre":len(rows),"reservations":[record_to_dict(r) for r in rows]}

async def get_voiture_details(voiture_id):
    pool=await get_pool()
    row=await pool.fetchrow("SELECT * FROM voitures WHERE id=$1",voiture_id)
    return {"succes":True,"voiture":record_to_dict(row)} if row else {"succes":False,"erreur":f"Voiture {voiture_id} introuvable."}

async def statistiques_flotte():
    pool=await get_pool(); today=_date.today()
    total=await pool.fetchval("SELECT COUNT(*) FROM voitures")
    occ=await pool.fetchval("SELECT COUNT(DISTINCT voiture_id) FROM reservations WHERE statut IN ('EN_ATTENTE','CONFIRMEE') AND date_debut<=$1 AND date_fin>$1",today)
    par_cat={row["categorie"] or "Autre":row["n"] for row in await pool.fetch("SELECT categorie,COUNT(*) as n FROM voitures GROUP BY categorie")}
    prix=await pool.fetchrow("SELECT MIN(prix_jour) mn,MAX(prix_jour) mx FROM voitures")
    villes=[r["ville"] for r in await pool.fetch("SELECT DISTINCT ville FROM voitures WHERE ville!='' ORDER BY ville")]
    return {"succes":True,"total_vehicules":total,"disponibles":total-(occ or 0),
            "par_categorie":par_cat,"prix_min_jour":float(prix["mn"]) if prix and prix["mn"] else 0,
            "prix_max_jour":float(prix["mx"]) if prix and prix["mx"] else 0,"villes":villes}

async def demander_meteo_agent(question):
    try:
        async with httpx.AsyncClient(timeout=8) as c:
            r=await c.post(settings.weather_agent_url,json={"message":question})
            return {"succes":True,"reponse":r.json().get("reply","")} if r.status_code==200 else {"succes":False,"erreur":f"Agent météo indisponible ({r.status_code})"}
    except: return {"succes":False,"erreur":"Agent météo inaccessible."}

SCRAPE_HEADERS={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0","Accept-Language":"fr-FR,fr;q=0.9"}
MARQUES=["volkswagen","renault","peugeot","citroen","ford","toyota","hyundai","kia","seat","skoda","opel","dacia","fiat","mercedes","bmw","audi","nissan","honda","mitsubishi","suzuki","mazda","jeep","tesla"]

def _extraire_marque(t):
    tl=t.lower()
    for m in MARQUES:
        if m in tl: return m.capitalize()
    return t.split()[0].capitalize() if t else "Inconnu"

def _prix_depuis_texte(texte):
    for p in [r"(\d{2,4}(?:[.,]\d+)?)\s*TND\s*(?:TTC\s*)?/?\s*(?:Jour|jour)",r"(\d{2,4})\s*TND\s*TTC",r"Dès\s+(\d{2,4})\s*TND"]:
        m=re.search(p,texte,re.IGNORECASE)
        if m:
            try:
                v=float(m.group(1).replace(",",".")); return v if 30<=v<=800 else None
            except: continue
    return None

async def _scraper_url(url):
    async def _fetch():
        async with httpx.AsyncClient(headers=SCRAPE_HEADERS,timeout=10,follow_redirects=True) as c:
            r=await c.get(url); r.raise_for_status(); return r.text
    try: return await cb_scraping.call(_fetch())
    except Exception as e: log.warning(f"[SCRAPING] {url}: {e}"); return None

async def scraper_mamicar(ville):
    if not SCRAPING_AVAILABLE or BeautifulSoup is None:
        return []
    html = await _scraper_url("https://www.mamicar.com/voitures.html")
    if not html:
        return [{"marque":"Voir catalogue","modele":"Mamicar","prix_jour":None,"ville":ville,
                 "agence":"Mamicar","url_source":"https://www.mamicar.com/voitures.html",
                 "source_label":"mamicar.com","disponible_scraping":True,"note":None}]
    from bs4 import BeautifulSoup as BS
    soup = BS(html, "html.parser"); out = []; seen = set()
    for h2 in soup.find_all("h2"):
        nom = h2.get_text(strip=True)
        if not nom or len(nom) < 4 or nom in seen: continue
        seen.add(nom); prix = None
        car_link = h2.find("a") or h2.find_next("a")
        href = car_link.get("href","") if car_link else ""
        if href.startswith("http"): direct_url = href
        elif href.startswith("/"): direct_url = f"https://www.mamicar.com{href}"
        else: direct_url = "https://www.mamicar.com/voitures.html"
        for sib in h2.find_next_siblings():
            prix = _prix_depuis_texte(sib.get_text(separator=" ", strip=True))
            if prix: break
        out.append({"marque":_extraire_marque(nom),"modele":nom[:60],"prix_jour":prix,
                    "ville":ville or "Tunisie","agence":"Mamicar",
                    "url_source": direct_url,
                    "source_label":"mamicar.com","disponible_scraping":True,"note":None})
    return sorted(out, key=lambda x: x["prix_jour"] or 9999)[:6]

async def scraper_citygo(ville):
    
    if not SCRAPING_AVAILABLE or BeautifulSoup is None:
        return []
    html = await _scraper_url("https://www.citygo.tn/")
    if not html:
        return [{"marque":"Voir catalogue","modele":"CityGo","prix_jour":None,"ville":ville,
                 "agence":"CityGo Tunisie","url_source":"https://www.citygo.tn/",
                 "source_label":"citygo.tn","disponible_scraping":True,"note":None}]
    from bs4 import BeautifulSoup as BS
    soup = BS(html, "html.parser"); out=[]; seen=set()
    for el in soup.select("h3 a[href*='location-voiture-tunisie'], a[href*='/voiture/'], a[href*='/car/']"):
        nom=el.get_text(strip=True)
        if not nom or nom in seen: continue
        seen.add(nom); href=el.get("href","")
        if href.startswith("http"): url=href
        elif href.startswith("/"): url=f"https://www.citygo.tn{href}"
        else: url="https://www.citygo.tn/"
        prix=None; bloc=el.find_parent()
        for _ in range(5):
            if not bloc: break
            prix=_prix_depuis_texte(bloc.get_text(separator=" ",strip=True))
            if prix: break
            bloc=bloc.find_parent()
        out.append({"marque":_extraire_marque(nom),"modele":nom[:60],"prix_jour":prix,
                    "ville":ville or "Tunisie","agence":"CityGo Tunisie",
                    "url_source":url,"source_label":"citygo.tn","disponible_scraping":True,"note":None})
    return sorted(out, key=lambda x: x["prix_jour"] or 9999)[:6]

async def rechercher_avec_fallback_scraping(ville="", categorie="", prix_max=None, places_min=None,
    date_debut="", date_fin="", electrique=None, transmission="", climatisation=None, marque="",
    couleur="", annee_min=None, kilometrage_max=None, carburant="", portes_min=None, caution_max=None):

    if not ville and not date_debut and not date_fin and not categorie and not marque:
        return {
            "succes": False,
            "source": "slot_manquant",
            "reservable": False,
            "message_source": "Infos insuffisantes pour chercher. Demander : ville et dates de location.",
        }
    if ville and not date_debut:
        return {
            "succes": False,
            "source": "slot_manquant",
            "reservable": False,
            "message_source": "Ville reçue. Il manque encore la date de début (et idéalement la date de fin) avant de lancer la recherche.",
        }

    ville_normalisee = _norm(ville).strip() if ville else ""

    try:
        res = await rechercher_voitures(
            categorie=categorie or None,
            prix_max=prix_max,
            places_min=places_min,
            date_debut=date_debut or None,
            date_fin=date_fin or None,
            electrique=electrique,
            ville=ville_normalisee or None,
            transmission=transmission or None,
            climatisation=climatisation,
            marque=marque or None,
            couleur=couleur or None,
            annee_min=annee_min,
            kilometrage_max=kilometrage_max,
            carburant=carburant or None,
            portes_min=portes_min,
            caution_max=caution_max
        )

        voitures = []
        source = "database"
        nb_jours = res.get("nb_jours")

        if res.get("succes") and res.get("voitures"):
            voitures = list(res["voitures"])
            for v in voitures:
                v["reservable"] = True

        # 1b. Si moins de 3 résultats, on relâche les filtres secondaires (on garde ville et dates)
        if len(voitures) < 3:
            ids_existants = {v["id"] for v in voitures}
            res_relax = await rechercher_voitures(
                ville=ville_normalisee or None,
                date_debut=date_debut or None,
                date_fin=date_fin or None
            )
            if res_relax.get("succes"):
                for v in res_relax.get("voitures", []):
                    if v["id"] not in ids_existants:
                        v["reservable"] = True
                        v["note_elargie"] = "Trouvé en relâchant certains filtres"
                        voitures.append(v)
                        ids_existants.add(v["id"])
                        if len(voitures) >= 3:
                            break

        # 2. Si toujours moins de 3 voitures dans la ville demandée, on complète
        # avec les partenaires, mais pas avec des voitures réservables d'autres villes.
        note = None
        if len(voitures) < 3:
            log.info(f"[SEARCH FALLBACK] Compléter la recherche (<3 voitures), lancement scraping...")
            mami_task = asyncio.create_task(scraper_mamicar(ville))
            city_task  = asyncio.create_task(scraper_citygo(ville))
            mami_res, city_res = await asyncio.gather(mami_task, city_task, return_exceptions=True)

            scraped_cars = []
            if isinstance(mami_res, list): scraped_cars.extend(mami_res)
            if isinstance(city_res, list): scraped_cars.extend(city_res)

            if prix_max is not None:
                try:
                    p_max = float(prix_max)
                    scraped_cars = [c for c in scraped_cars if c.get("prix_jour") is None or float(c["prix_jour"]) <= p_max]
                except Exception as e:
                    log.warning(f"[SEARCH FALLBACK] Erreur filtrage prix_max scraping: {e}")

            for c in scraped_cars:
                c["prix_jour"] = None
                c["reservable"] = False

                # Pré-formater le lien Markdown
                marque_c = c.get("marque", "")
                modele_c = c.get("modele", "")
                url_c    = c.get("url_source", "")
                label_c  = f"{marque_c} {modele_c}".strip() or "Voir la fiche"
                if url_c and url_c.startswith("https://"):
                    c["lien_affiche"] = f"[{label_c} — Voir la fiche]({url_c})"
                else:
                    c["lien_affiche"] = label_c

            scraped_cars.sort(key=lambda x: x.get("marque",""))

            # Si on cherche électrique, on filtre le scraping
            if electrique or (categorie and "electri" in _norm(categorie)):
                pass
            else:
                for c in scraped_cars:
                    if len(voitures) < 3:
                        voitures.append(c)
                    else:
                        break

            if len(voitures) == 0:
                if electrique or (categorie and "electri" in _norm(categorie)):
                    note = "Aucun véhicule électrique disponible dans notre flotte pour cette ville. Les partenaires externes ne proposent pas de filtre électrique fiable."
                else:
                    note = "Aucune voiture trouvée en flotte locale ni chez nos partenaires externes."
            elif not any(v.get("reservable") for v in voitures):
                source = "scraping_web"

        # S'assurer qu'on retourne au maximum 3 voitures
        voitures = voitures[:3]

        return {
            "succes": True,
            "source": source,
            "reservable": any(v.get("reservable") for v in voitures),
            "nb_jours": nb_jours,
            "voitures": voitures,
            "note": note
        }
    except Exception as e:
        log.error(f"[SEARCH FALLBACK] Erreur globale: {e}")
        return {"succes": False, "erreur": str(e)}

async def get_client_profile(pool,session_id):
    row=await pool.fetchrow("SELECT * FROM client_profiles WHERE session_id=$1",session_id)
    return record_to_dict(row) if row else {}

async def update_client_profile(pool,session_id,profil):
    data=profil.model_dump(exclude_none=True)
    if not data: return
    ex=await get_client_profile(pool,session_id)
    if not ex:
        await pool.execute("INSERT INTO client_profiles (session_id,client_nom,client_tel,client_email,ville_preferee,budget_max,categorie_pref,nb_places_min,transmission,climatisation,nb_conversations) VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,1) ON CONFLICT (session_id) DO NOTHING",
            session_id,data.get("client_nom"),data.get("client_tel"),data.get("client_email"),data.get("ville_preferee"),data.get("budget_max"),data.get("categorie_pref"),data.get("nb_places_min"),data.get("transmission"),data.get("climatisation"))
    else:
        sets=[]; vals=[]; idx=1
        for f in ["client_nom","client_tel","client_email","ville_preferee","budget_max","categorie_pref","nb_places_min","transmission","climatisation"]:
            if f in data: sets.append(f"{f}=${idx}"); vals.append(data[f]); idx+=1
        sets+=["nb_conversations=nb_conversations+1","updated_at=NOW()"]; vals.append(session_id)
        if sets: await pool.execute(f"UPDATE client_profiles SET {','.join(sets)} WHERE session_id=${idx}",*vals)

def profil_vers_contexte(profil):
    if not profil: return ""
    lines=["[MÉMOIRE CLIENT — ne jamais redemander ces infos]"]
    for k,label in [("client_nom","Nom"),("client_tel","Téléphone"),("client_email","Email"),
                    ("ville_preferee","Ville"),("budget_max","Budget (TND/j)"),
                    ("categorie_pref","Catégorie"),("nb_places_min","Places min"),("transmission","Transmission")]:
        if profil.get(k): lines.append(f"  • {label} : {profil[k]}")
    if profil.get("climatisation") is not None: lines.append(f"  • Climatisation : {'Oui' if profil['climatisation'] else 'Non'}")
    return "\n".join(lines)

TOOLS_DEFINITION=[
    {"type":"function","function":{"name":"rechercher_avec_fallback_scraping",
     "description":"Recherche voitures disponibles. DB locale d'abord (réservable), puis scraping si vide. TOUJOURS appeler avant de proposer une voiture.",
     "parameters":{"type":"object","properties":{
         "ville":{"type":"string"},"categorie":{"type":"string"},
         "prix_max":{"anyOf":[{"type":"string"},{"type":"number"}]},"places_min":{"anyOf":[{"type":"string"},{"type":"integer"}]},
         "date_debut":{"type":"string"},"date_fin":{"type":"string"},"electrique":{"anyOf":[{"type":"string"},{"type":"boolean"}]},
         "transmission":{"type":"string"},"climatisation":{"type":"string"},"marque":{"type":"string"},
         "couleur":{"type":"string"},"annee_min":{"anyOf":[{"type":"string"},{"type":"integer"}]},
         "kilometrage_max":{"anyOf":[{"type":"string"},{"type":"integer"}]},"carburant":{"type":"string"},
         "portes_min":{"anyOf":[{"type":"string"},{"type":"integer"}]},"caution_max":{"anyOf":[{"type":"string"},{"type":"number"}]}
     },"required":[]}}},
    {"type":"function","function":{"name":"reserver_voiture",
     "description":"Réserve une voiture. Appeler UNIQUEMENT si nom+téléphone+email+date_debut+date_fin sont tous confirmés.",
     "parameters":{"type":"object","properties":{"voiture_id":{"type":"string"},"client_nom":{"type":"string"},
         "client_tel":{"type":"string"},"client_email":{"type":"string"},"date_debut":{"type":"string"},"date_fin":{"type":"string"}},
         "required":["voiture_id","client_nom","client_tel","client_email","date_debut","date_fin"]}}},
    {"type":"function","function":{"name":"annuler_reservation_client","description":"Annule une réservation client.",
     "parameters":{"type":"object","properties":{"reservation_id":{"type":"string"},"client_nom":{"type":"string"}},"required":["reservation_id"]}}},
    {"type":"function","function":{"name":"consulter_reservations","description":"Consulte les réservations d'un client.",
     "parameters":{"type":"object","properties":{"client_nom":{"type":"string"}},"required":[]}}},
    {"type":"function","function":{"name":"get_voiture_details","description":"Détails d'une voiture par ID.",
     "parameters":{"type":"object","properties":{"voiture_id":{"type":"string"}},"required":["voiture_id"]}}},
    {"type":"function","function":{"name":"statistiques_flotte","description":"Stats globales de la flotte.",
     "parameters":{"type":"object","properties":{},"required":[]}}},
    {"type":"function","function":{"name":"demander_meteo_agent","description":"Question météo à l'agent météo.",
     "parameters":{"type":"object","properties":{"question":{"type":"string"}},"required":["question"]}}},
]

TOOLS_MAP:dict[str,Any]={
    "rechercher_avec_fallback_scraping":rechercher_avec_fallback_scraping,
    "reserver_voiture":reserver_voiture_fn,
    "annuler_reservation_client":annuler_reservation_client,
    "consulter_reservations":consulter_reservations,
    "get_voiture_details":get_voiture_details,
    "statistiques_flotte":statistiques_flotte,
    "demander_meteo_agent":demander_meteo_agent,
}

def _coerce_tool_input(name,inp):
    inp={k:v for k,v in inp.items() if v is not None and str(v).lower().strip() not in _NULL_STRINGS}
    for champ in ("date_debut","date_fin"):
        if champ in inp:
            val=str(inp[champ]).strip()
            # Si le format est DD-MM ou DD/MM ou DD.MM (sans année)
            if re.match(r"^\d{1,2}[-/.]\d{1,2}$", val):
                sep = "-" if "-" in val else ("/" if "/" in val else ".")
                val = f"{val}{sep}{_date.today().year}"
            
            parsed = False
            for fmt in ("%d/%m/%Y","%d-%m-%Y","%d.%m.%Y","%Y-%m-%d"):
                try:
                    inp[champ]=datetime.strptime(val,fmt).strftime("%Y-%m-%d")
                    parsed = True
                    break
                except: continue
            if not parsed:
                # Si la date n'est pas valide, on la retire pour ne pas faire planter la recherche
                inp.pop(champ, None)
    result={}
    for k,v in inp.items():
        if k=="places_min":
            try: result[k]=int(float(str(v)))
            except: pass
        elif k=="prix_max":
            try: result[k]=float(str(v))
            except: pass
        elif k in ("annee_min", "portes_min", "kilometrage_max"):
            try: result[k]=int(float(str(v)))
            except: pass
        elif k=="caution_max":
            try: result[k]=float(str(v))
            except: pass
        elif k in ("electrique","climatisation"):
            result[k]=v if isinstance(v,bool) else v.lower() in ("true","oui","yes","1")
        elif k=="categorie" and isinstance(v,str):
            n=_norm(v)
            mapped = next((c for key,c in CATEGORIE_MAP.items() if key in n), v)
            result[k] = mapped
            if _norm(mapped) == "electrique":
                result["electrique"] = True
        else: result[k]=v
    return result
