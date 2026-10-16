# The platform's own analyses and transformations. Build from the repository root:
#   docker build -f engines/native/Dockerfile -t pn-llm-verif/native:1.7 .
# Nothing to fetch: the algorithms are in api/app/domain/analyses. The tool version is bumped
# with every change of an algorithm (results are cached by tool version).
FROM python:3.14-slim
ARG TOOL_VERSION=1.7
LABEL org.opencontainers.image.title="pn-llm-verif engine native" \
      org.opencontainers.image.version="${TOOL_VERSION}"

COPY engines/common/requirements.txt /tmp/requirements.txt
RUN useradd --system --uid 10001 --no-create-home runner \
 && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

# The adapter kit and the platform's domain: the algorithms and the models of the contract.
COPY api/app/__init__.py /opt/pnverif/app/__init__.py
COPY api/app/domain /opt/pnverif/app/domain
COPY engines/common/pnverif_engine /opt/pnverif/pnverif_engine
COPY engines/native/adapter.py /opt/adapter/adapter.py

ENV PYTHONPATH=/opt/pnverif PYTHONDONTWRITEBYTECODE=1 TOOL_VERSION=${TOOL_VERSION}
USER 10001
ENTRYPOINT ["python", "/opt/adapter/adapter.py"]
