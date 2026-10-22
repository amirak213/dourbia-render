# Lancer PostgreSQL
Start-Service -Name "postgresql-x64-16" -ErrorAction SilentlyContinue

# Lancer Redis
docker start redis

# Lancer serveur dourbia (routes confirmation/refus)
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd E:\claude\AgentLocation; python -m uvicorn api.routes:app --host 0.0.0.0 --port 5000"

# Lancer le chatbot master
python E:\claude\AgentPrincipal\chat.py