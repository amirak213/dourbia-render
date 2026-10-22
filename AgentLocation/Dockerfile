# Utilise une image de base Python légère
FROM python:3.12-slim

# Empêche Python d'écrire des fichiers .pyc et de mettre en mémoire tampon stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV HF_HOME=/opt/hf

# Définit le répertoire de travail dans le conteneur
WORKDIR /app

# Installe les dépendances système requises
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libpq-dev \
    git \
    && rm -rf /var/lib/apt/lists/*

# Copie les fichiers de dépendances et les installe
COPY requirements.txt /app/
RUN pip install --no-cache-dir torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu
RUN pip install --no-cache-dir -r requirements.txt

# Télécharge le modèle d'embeddings au moment du build (évite les erreurs réseau au runtime)
RUN python -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2')"
ENV HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1

# Copie le reste de l'application
COPY . /app/

# Expose le port par défaut
EXPOSE 10000

RUN useradd -m -u 10001 dourbia && chown -R dourbia:dourbia /app
USER dourbia

# Commande pour démarrer l'application
CMD ["python", "main.py"]
