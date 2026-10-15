FROM python:3.14-slim
WORKDIR /srv
COPY pyproject.toml ./
COPY app ./app
# Installs the dependencies declared in pyproject.toml (single source of truth).
RUN pip install --no-cache-dir .
ENV PNVERIF_DATABASE_PATH=/data/pnverif.sqlite
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s CMD \
  python -c "import urllib.request as u; u.urlopen('http://localhost:8000/v1/engines')" || exit 1
# Runs as root on purpose for local development: the API needs the Docker socket to start
# engines (see docs/adr/0004). Do not deploy this way; see the security review issue.
CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
