# Build from the repository root:  docker build -f api/Dockerfile -t pn-llm-verif/api .

# ---- Stage 1: the UI (Node is needed to build it, not to run the API) ------------------------
FROM node:24-slim AS ui
WORKDIR /ui
COPY ui/package.json ui/package-lock.json ./
RUN npm ci
COPY ui ./
RUN npm run build

# ---- Stage 2: the API, serving the built UI under /ui ----------------------------------------
FROM python:3.14-slim
WORKDIR /srv
COPY api/pyproject.toml api/requirements.txt ./
COPY api/app ./app
# The locked, hashed dependencies first (make lock), then the application itself.
RUN pip install --no-cache-dir --require-hashes -r requirements.txt \
 && pip install --no-cache-dir --no-deps .
COPY --from=ui /ui/dist ./ui
ENV PNVERIF_DATABASE_PATH=/data/pnverif.sqlite PNVERIF_UI_DIR=/srv/ui
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD \
  ["python", "-c", "import urllib.request as u; u.urlopen('http://localhost:8000/v1/engines')"]
# Runs as root on purpose for local development: the API needs the Docker socket to start
# engines (see docs/adr/0004). Do not deploy this way; see docs/security-container-launching.md.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
