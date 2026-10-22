# Guide Historique — Chat UI

Interface React/Vite type ChatGPT avec conversations séparées.

## Prérequis

**Option A — Portable Node (recommandé, sans installation système)**

Depuis la racine du projet :

```powershell
.\.tools\install-node.ps1
```

**Option B — Node.js système**

Installez Node.js LTS : https://nodejs.org/ puis vérifiez `node -v` et `npm -v`.

## Lancer l'interface

Terminal 1 — API :

```powershell
cd backend
venv\Scripts\activate
uvicorn app.main:app --reload
```

Terminal 2 — UI (avec Node portable) :

```powershell
cd frontend\simple-chat-ui
.\run-dev.ps1
```

Ou avec Node système :

```powershell
cd frontend\simple-chat-ui
npm install
npm run dev
```

Ouvrez http://localhost:5173

## Fonctionnalités

- **Nouvelle conversation** — crée une session API distincte (`chat_…`)
- **Circuit personnalisé** — onglet **Circuit** : formulaire, carte Leaflet, timeline
- **Sidebar** — liste des chats, titre = premier message
- **Persistance locale** — historique stocké dans `localStorage`
- **Sources & mémoire** — panneau repliable sous chaque réponse
- **Proxy Vite** — `/api` → `localhost:8000` (pas de config CORS en dev)

## Circuit planner

1. Import data: `python scripts/import_circuit_datasets.py` (from `backend/`)
2. Optional: copy `.env.example` to `.env` and configure OSRM (enabled by default)
3. Open **Circuit** in the navigation
4. Fill the form and click **Créer mon circuit**
5. The map shows numbered markers and a road-following route via OSRM when available

### OSRM route tracing

| Variable | Default | Purpose |
|----------|---------|---------|
| `VITE_OSRM_ENABLED` | `true` | Set `false` to use straight-line fallback only |
| `VITE_OSRM_BASE_URL` | `https://router.project-osrm.org` | OSRM server URL |
| `VITE_OSRM_PROFILE` | `driving` | Fallback profile if walking/cycling fails |

Documentation: [docs/circuit_agent.md](../../docs/circuit_agent.md)

## Configuration

Copiez `.env.example` vers `.env` si besoin. En dev, laissez `VITE_API_URL` vide.
