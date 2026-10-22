from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ScrapeSource:
    """One trusted, scrapable page or listing to ingest into document_chunks.

    Kept intentionally simple for a manual/batch run: one entry = one URL.
    Sources requiring JS rendering, paywall bypass, or API access are NOT
    listed here on purpose (out of scope for today's batch — Louvre, British
    Museum, Cambridge Core, ScienceDirect, Oxford Academic).
    """

    id: str  # stable slug, used for logging/dedup, not the DB source_id
    name: str
    url: str
    language: str  # "fr" | "en" — matches DocumentChunk.language
    reliability: int  # 1-5, from the sourcing table
    priority: int  # 1 = highest
    topics: tuple[str, ...]  # free-text tags, stored in metadata_json
    # CSS selector(s) for the main content area. Kept generic; extract.py
    # falls back to a readability-style heuristic if the selector matches
    # nothing (site markup can change without notice).
    content_selector: str | None = None
    # "html" (default): fetch + parse HTML via RespectfulFetcher/extract.py.
    # "wikipedia_api": fetch structured plain-text extract via Wikipedia's
    # official REST/action API instead of scraping HTML. Bypasses Wikimedia's
    # 2026 bot-traffic crackdown (T400119) which 403s generic HTML scraping
    # even with a compliant User-Agent.
    source_kind: str = "html"
    # For source_kind="wikipedia_api": the exact article title as it appears
    # in the URL (e.g. "Hannibal", "Punic_Wars"). Ignored for source_kind="html".
    wikipedia_title: str | None = None
    exclude_selectors: tuple[str, ...] = field(
        default_factory=lambda: (
            "nav",
            "footer",
            "header",
            "script",
            "style",
            "form",
            ".cookie-banner",
            ".navbar",
            ".breadcrumb",
        )
    )
    notes: str = ""


# NOTE: only Priority 1/2, open-access, static-HTML sources from the
# sourcing table. Ajoute une nouvelle source = ajoute une entrée ici,
# rien d'autre à changer dans le pipeline.
#
# Historique des ajustements post premier run réel (02/07/2026):
#   - unesco_multimedia_carthage_kerkouane: RETIRÉE. 200 OK mais le contenu
#     extrait est le menu de navigation du portail vidéo UNESCO, pas un
#     article — la page ne correspond pas à ce que décrivait la table de
#     sourcing initiale.
#   - commune_tunis_carthage_museum: RETIRÉE. URL morte (302 puis 404), site
#     legacy visiblement disparu. Priority 3 de toute façon, pas une grosse
#     perte.
#   - inp_museums_overview: URL corrigée (l'ancienne renvoyait 404, le site a
#     été restructuré).
#   - patrimoine_tunisie_carthage_museum, britannica_carthage: GARDÉES dans
#     la table pour traçabilité (bonne fiabilité, bon contenu) mais EXCLUES
#     du run automatique — voir NOT_AUTO_SCRAPED_IDS. La première est
#     bloquée par son robots.txt (à respecter), la seconde renvoie un 403
#     systématique (protection anti-bot). Contenu à recopier manuellement si
#     besoin plutôt que de forcer le fetch.
TRUSTED_SOURCES: tuple[ScrapeSource, ...] = (
    ScrapeSource(
        id="unesco_whc_carthage_listing",
        name="UNESCO World Heritage Centre — Archaeological Site of Carthage",
        url="https://whc.unesco.org/en/list/37/",
        language="en",
        reliability=5,
        priority=1,
        topics=(
            "foundation_of_carthage",
            "punic_civilization",
            "roman_carthage",
            "destruction_of_carthage",
            "archaeological_sites",
        ),
        content_selector="#content",
        notes=(
            "Core description of Carthage's history from Phoenician foundation "
            "to Roman refoundation. 403 lors du 1er run (02/07/2026) — headers "
            "navigateur ajoutés à fetch.py, à re-tester."
        ),
    ),
    ScrapeSource(
        id="unesco_whc_carthage_documents",
        name="UNESCO WHC — Carthage documents & gallery",
        url="https://whc.unesco.org/en/documents/130238",
        language="en",
        reliability=5,
        priority=1,
        topics=(
            "byrsa_hill",
            "antonine_baths",
            "punic_ports",
            "tophet",
            "amphitheatre",
            "theatre",
            "aqueduct",
            "la_malga_cisterns",
            "basilica_damous_el_karita",
        ),
        content_selector="#content",
        notes=(
            "Management reports, conservation state, descriptions of individual "
            "site components. 403 lors du 1er run (02/07/2026) — headers "
            "navigateur ajoutés à fetch.py, à re-tester."
        ),
    ),
    ScrapeSource(
        id="inp_home",
        name="Institut National du Patrimoine (INP) — Home & activities",
        url="https://www.inp2020.tn/en/",
        language="en",
        reliability=5,
        priority=1,
        topics=("tunisian_heritage", "archaeology", "site_management"),
        content_selector="main, #content, .content",
        notes="Institutional mission; gateway page. Fonctionne (200, contenu propre).",
    ),
    ScrapeSource(
        id="inp_museums_overview",
        name="INP — Présentation des musées tunisiens",
        url="https://www.inp2020.tn/inp_tunisie/musees/_musees_tunisiens/",
        language="fr",
        reliability=4,
        priority=2,
        topics=("museums", "national_museum_of_carthage", "bardo_museum"),
        content_selector="main, #content, .content, article",
        notes=(
            "URL corrigée le 02/07/2026 — l'ancienne URL /en/... de la table de "
            "sourcing initiale renvoyait un 404 (site restructuré). Contient "
            "directement une section sur le musée de Carthage."
        ),
    ),
    ScrapeSource(
        id="patrimoine_tunisie_carthage_museum",
        name="Patrimoine de Tunisie — The Carthage Museum",
        url="https://www.patrimoinedetunisie.com.tn/en/museums/the-carthage-museum/overview/",
        language="en",
        reliability=5,
        priority=1,
        topics=(
            "national_museum_of_carthage",
            "phoenician_punic_period",
            "roman_african_period",
            "arab_islamic_period",
        ),
        content_selector="main, article, .content",
        notes=(
            "EXCLUE du run automatique (02/07/2026): robots.txt interdit "
            "explicitement ce chemin. Voir NOT_AUTO_SCRAPED_IDS."
        ),
    ),
    ScrapeSource(
        id="britannica_carthage",
        name="Encyclopaedia Britannica — Carthage",
        url="https://www.britannica.com/place/Carthage-ancient-city-Tunisia",
        language="en",
        reliability=5,
        priority=1,
        topics=(
            "punic_civilization",
            "trade_maritime_empire",
            "government",
            "military_navy",
            "hannibal",
            "hamilcar",
            "hasdrubal",
            "scipio_africanus",
            "cato_the_elder",
            "punic_wars",
        ),
        content_selector="article, .topic-content",
        notes=(
            "EXCLUE du run automatique (02/07/2026): 403 systématique "
            "(protection anti-bot). Voir NOT_AUTO_SCRAPED_IDS."
        ),
    ),
    ScrapeSource(
        id="wikipedia_carthage_en",
        name="Wikipedia — Carthage",
        url="https://en.wikipedia.org/wiki/Carthage",
        language="en",
        reliability=3,
        priority=1,
        topics=(
            "foundation_of_carthage",
            "punic_civilization",
            "roman_carthage",
            "destruction_of_carthage",
            "trade_maritime_empire",
        ),
        source_kind="wikipedia_api",
        wikipedia_title="Carthage",
        notes="Overview article, general-audience, stable structure. Fetched via API, not HTML scrape (T400119 blocks the latter).",
    ),
    ScrapeSource(
        id="wikipedia_punic_wars_en",
        name="Wikipedia — Punic Wars",
        url="https://en.wikipedia.org/wiki/Punic_Wars",
        language="en",
        reliability=3,
        priority=1,
        topics=(
            "punic_wars",
            "hannibal",
            "hamilcar",
            "scipio_africanus",
            "rome_vs_carthage",
        ),
        source_kind="wikipedia_api",
        wikipedia_title="Punic_Wars",
        notes="Covers all three Punic Wars in one article. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_hannibal_en",
        name="Wikipedia — Hannibal",
        url="https://en.wikipedia.org/wiki/Hannibal",
        language="en",
        reliability=3,
        priority=1,
        topics=("hannibal", "punic_wars", "military_navy", "hamilcar"),
        source_kind="wikipedia_api",
        wikipedia_title="Hannibal",
        notes="Long, well-maintained biographical article. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_battle_of_zama_en",
        name="Wikipedia — Battle of Zama",
        url="https://en.wikipedia.org/wiki/Battle_of_Zama",
        language="en",
        reliability=3,
        priority=2,
        topics=("punic_wars", "hannibal", "scipio_africanus", "battle_of_zama"),
        source_kind="wikipedia_api",
        wikipedia_title="Battle_of_Zama",
        notes="End of the Second Punic War, decisive battle. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_scipio_africanus_en",
        name="Wikipedia — Scipio Africanus",
        url="https://en.wikipedia.org/wiki/Scipio_Africanus",
        language="en",
        reliability=3,
        priority=2,
        topics=("scipio_africanus", "punic_wars", "battle_of_zama"),
        source_kind="wikipedia_api",
        wikipedia_title="Scipio_Africanus",
        notes="Roman general, opposite figure to Hannibal. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_hamilcar_barca_en",
        name="Wikipedia — Hamilcar Barca",
        url="https://en.wikipedia.org/wiki/Hamilcar_Barca",
        language="en",
        reliability=3,
        priority=2,
        topics=("hamilcar", "punic_wars", "hannibal"),
        source_kind="wikipedia_api",
        wikipedia_title="Hamilcar_Barca",
        notes="Hannibal's father, First Punic War general. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_hasdrubal_barca_en",
        name="Wikipedia — Hasdrubal Barca",
        url="https://en.wikipedia.org/wiki/Hasdrubal_Barca",
        language="en",
        reliability=3,
        priority=2,
        topics=("hasdrubal", "punic_wars", "hannibal"),
        source_kind="wikipedia_api",
        wikipedia_title="Hasdrubal_Barca",
        notes="Hannibal's brother, Second Punic War general. Fetched via API.",
    ),
    ScrapeSource(
        id="wikipedia_carthage_fr",
        name="Wikipédia — Carthage (FR)",
        url="https://fr.wikipedia.org/wiki/Carthage",
        language="fr",
        reliability=3,
        priority=2,
        topics=(
            "foundation_of_carthage",
            "punic_civilization",
            "roman_carthage",
            "destruction_of_carthage",
        ),
        source_kind="wikipedia_api",
        wikipedia_title="Carthage",
        notes="Complements INP French-language institutional content. Fetched via API.",
    ),
)

# Sources gardées dans TRUSTED_SOURCES pour traçabilité mais à exclure de
# tout run automatique — bloquées par robots.txt ou par une protection
# anti-bot que ce scraper ne doit pas contourner. select_sources() dans
# scripts/scrape_sources.py filtre sur cette liste par défaut.
NOT_AUTO_SCRAPED_IDS: tuple[str, ...] = (
    "patrimoine_tunisie_carthage_museum",
    "britannica_carthage",
    "unesco_whc_carthage_listing",
    "unesco_whc_carthage_documents",
)


def get_source_by_id(source_id: str) -> ScrapeSource | None:
    for source in TRUSTED_SOURCES:
        if source.id == source_id:
            return source
    return None


def sources_by_priority(
    max_priority: int = 3, *, include_blocked: bool = False
) -> tuple[ScrapeSource, ...]:
    return tuple(
        s
        for s in TRUSTED_SOURCES
        if s.priority <= max_priority
        and (include_blocked or s.id not in NOT_AUTO_SCRAPED_IDS)
    )
