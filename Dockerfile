FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/opt/hf \
    PYTHONPATH=/srv/dourbia

WORKDIR /srv/dourbia

# torch CPU d'abord : sentence-transformers le trouvera deja installe
RUN pip install torch==2.10.0 --index-url https://download.pytorch.org/whl/cpu

COPY requirements-backend.txt .
RUN pip install -r requirements-backend.txt

# Modeles telecharges PENDANT LE BUILD (rien n'est telecharge au runtime)
RUN python -c "from sentence_transformers import SentenceTransformer as S; [S(m) for m in ('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'intfloat/multilingual-e5-small')]"
ENV HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1

# Meme arborescence que E:\claude (les sys.path du code en dependent)
COPY app.py circuit_engine.py ./
COPY AgentPrincipal ./AgentPrincipal
COPY AgentHistorique ./AgentHistorique
COPY AgentLocation ./AgentLocation
COPY AgentMeteo ./AgentMeteo
COPY securite ./securite
COPY scripts/start.sh scripts/render_bootstrap_pg_env.py ./scripts/

RUN chmod +x /srv/dourbia/scripts/start.sh \
    && useradd -m -u 10001 dourbia \
    && chown -R dourbia:dourbia /srv/dourbia
USER dourbia

EXPOSE 10000
CMD ["/srv/dourbia/scripts/start.sh"]