# Déploiement Render — Dourbia (périmètre Carthage)

Plan retenu : **backend Docker**, **Postgres 16**, **Redis**, **frontend statique**. Pas d’AgentLocation ni AgentMeteo sur ce blueprint.

## Ordre global

1. Rotation des secrets (Groq, Langfuse, et aussi ADMIN_API_KEY et le mot de passe d'application Gmail d'AgentLocation, exposés dans l'historique GitHub) — ne pas réutiliser d’anciennes valeurs exposées sur GitHub.
2. `git push` contenant `render.yaml`, `Dockerfile`, `.dockerignore`, `.gitignore`, `scripts/start.sh`, `scripts/render_bootstrap_pg_env.py` et `scripts/smoke_render.ps1`.
3. Dashboard Render → **New Blueprint** → repo `amirak213/PrincipalAgents`, branche `main`.
4. Saisir les variables `sync: false` lors de la création.
5. Attendre le premier déploiement backend (démarrage ~140–170 s ; health check `/health` jusqu’à 15 min).
6. Restaurer les données (section ci-dessous) via l’**URL externe** Postgres. Si la connexion externe est refusée, ajouter votre IP dans Networking de la base (dashboard), puis refermer l'accès après la restauration.
7. Mettre à jour `FRONTEND_ORIGINS` = URL du site statique (ex. `https://dourbia-frontend.onrender.com`) (sans slash final).
8. Redéployer le backend si CORS bloque le navigateur.
9. `scripts/smoke_render.ps1 -BaseUrl https://dourbia-backend.onrender.com -Origin https://dourbia-frontend.onrender.com` : la section 9 (AgentLocation) et le test 6 (location de voiture) sont attendus en échec, l'agent n'étant pas déployé.
## Données à restaurer (UTF-8, pas l’ancien `dourbia.dump` pour les circuits)

Base cible : **`dourbia`** sur l’instance `dourbia-db`.

Ordre recommandé (fichiers sous `C:\Users\Hp23\dourbia_dumps\utf8` ou `E:\dourbia_dumps`) :

1. Extensions (une fois, en superuser Render si besoin) : `vector`, `pgcrypto`, `uuid-ossp`.
2. `00_pack_categorie.sql` (enum packs) — depuis `E:\dourbia_dumps\`.
3. `circuits_fixed.sql` — schéma + monuments + distances (noms UTF-8 réparés CP850→UTF-8).
4. `hist.dump` ou `chunks.sql` — table `historical_chunks`.
5. `packs.dump` — packs et `tab_circuit_monument` si le wizard packs est requis.
6. `guide_descriptions.sql` — descriptions Excel pour les **8** monuments alignés exactement (généré par `scripts/build_guide_descriptions.py`).

Ne pas restaurer `dourbia.dump` complet sur prod si vous voulez éviter les `?` dans `agent_traces` / scraped ; l’audit local a compté 39 `?` dans ce dump.

Script d’aide (adapter `$ExternalUrl`) :

```powershell
.\scripts\restore_production_utf8.ps1 -ExternalDatabaseUrl "postgresql://..."
```

## Variables à ajuster après le 1er déploiement

| Variable | Valeur |
|----------|--------|
| `FRONTEND_ORIGINS` | URL HTTPS du frontend Render |
| `VITE_API_URL` | Normalement injecté via `RENDER_EXTERNAL_URL` du backend ; vérifier le build frontend |

`PG_HOST` / `DOURBIA_PG_*` : **non** à saisir — dérivés au démarrage par `scripts/render_bootstrap_pg_env.py` depuis `CIRCUIT_DATABASE_URL`.

## Limites connues (test sur place)

- `WEB_SEARCH_ENABLED=false` : monuments sans description ni chunk approuvé → message « information vérifiée indisponible ».
- Seulement **8/60** monuments ont des descriptions Excel alignées ; dix étapes de circuits Carthage restent sans texte local.
- `/api/chat` renvoie encore `sources: []` (dette existante).
- RAG : 79 chunks, seuil 0,65 — pas de filtre par `monument_id`.

## Coût mensuel estimé (Frankfurt, Hobby workspace)

| Service | Plan |
|---------|------|
| dourbia-backend | 2c-4g (~85 $) |
| dourbia-db | 0.5c-1g + 1 Go (~19 $) |
| dourbia-redis | starter (~10 $) |
| dourbia-frontend | gratuit |
| **Total** | **~114 $/mois** (compute au prorata) |

## Rollback

- Render : redeploy commit précédent.
- Données : snapshot Render Postgres ou re-restaurer les dumps sur une base jetable avant prod.
