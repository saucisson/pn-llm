# Build from the repository root:  docker build -f engines/dummy/Dockerfile -t pn-llm-verif/dummy:latest .
# The structure follows engines/template/Dockerfile; this engine has no tool to build.
FROM python:3.12-slim

RUN useradd --system --uid 10001 --no-create-home runner \
 && pip install --no-cache-dir "pydantic>=2.6"

# The adapter kit and the models of the contract: the only code shared with the platform.
COPY api/app/__init__.py /opt/pnverif/app/__init__.py
COPY api/app/domain /opt/pnverif/app/domain
COPY engines/common/pnverif_engine /opt/pnverif/pnverif_engine
COPY engines/dummy/entrypoint.py /opt/adapter/entrypoint.py

# The root file system is read-only at run time: no bytecode files.
ENV PYTHONPATH=/opt/pnverif PYTHONDONTWRITEBYTECODE=1
USER 10001
ENTRYPOINT ["python", "/opt/adapter/entrypoint.py"]
