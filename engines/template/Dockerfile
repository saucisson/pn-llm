# Template of an engine image. Copy this directory to engines/<name>/ and fill the placeholders.
# Build from the repository root:
#   docker build -f engines/<name>/Dockerfile -t pn-llm-verif/<name>:<tool version> .
# Rules (docs/engine-integration-checklist.md): pinned tool version, non-root user, nothing to
# download at run time (the container has no network), nothing written outside /work/output and /tmp.

# ---- Stage 1: build or fetch the tool, at a pinned version -----------------------------------
# Pin the base image by tag (or digest) and the tool by release tag or commit hash.
FROM debian:12.7-slim AS build
ARG TOOL_VERSION=REPLACE_WITH_A_RELEASE_TAG_OR_COMMIT
ARG TOOL_URL=REPLACE_WITH_THE_SOURCE_OR_BINARY_URL
ARG TOOL_SHA256=REPLACE_WITH_THE_CHECKSUM_OF_THE_DOWNLOAD
# Replace by the real build. Fail the build if the checksum does not match.
RUN mkdir -p /opt/tool \
 && echo "download ${TOOL_URL} at ${TOOL_VERSION}, check ${TOOL_SHA256}, build into /opt/tool"

# ---- Stage 2: the runtime image --------------------------------------------------------------
FROM python:3.12-slim AS runtime
ARG TOOL_VERSION=REPLACE_WITH_A_RELEASE_TAG_OR_COMMIT
LABEL org.opencontainers.image.title="pn-llm-verif engine REPLACE_NAME" \
      org.opencontainers.image.version="${TOOL_VERSION}"

RUN useradd --system --uid 10001 --no-create-home runner \
 && pip install --no-cache-dir "pydantic>=2.6"

COPY --from=build /opt/tool /opt/tool
# The adapter kit and the models of the contract: the only code shared with the platform.
COPY api/app/__init__.py /opt/pnverif/app/__init__.py
COPY api/app/domain /opt/pnverif/app/domain
COPY engines/common/pnverif_engine /opt/pnverif/pnverif_engine
COPY engines/REPLACE_NAME/adapter.py /opt/adapter/adapter.py

ENV PYTHONPATH=/opt/pnverif PYTHONDONTWRITEBYTECODE=1 TOOL_VERSION=${TOOL_VERSION}
USER 10001
ENTRYPOINT ["python", "/opt/adapter/adapter.py"]
