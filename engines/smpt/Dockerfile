# SMPT, an SMT-based reachability checker (Nicolas Amat, ONERA). Build from the repository root:
#   docker build -f engines/smpt/Dockerfile -t pn-llm-verif/smpt:5.0-82206dd .
# Licences: SMPT is GPL-3.0-or-later (https://github.com/nicolasAmat/SMPT). The Tina toolbox it
# calls (ndrio, reduce, walk, struct) is distributed in binary by LAAS-CNRS under its own licence
# (free for non-commercial use): the image is built locally and not redistributed by this project.
# z3 is MIT. Not included: LattE, Octant and MiniZinc (the polyhedral reduction runs without them,
# and the colored front end needs the mcc unfolder): see docs/engines.md.

# ---- Stage 1: fetch SMPT at a pinned commit and Tina at a pinned checksum --------------------
FROM python:3.14-slim-bookworm AS fetch
ARG TOOL_COMMIT=82206ddcca45ecc497f8ed8eebc169a7c69d3641
ARG TINA_URL=https://projects.laas.fr/tina/binaries/tina-4.0.0-amd64-linux.tgz
ARG TINA_SHA256=5e1cbd7c2e043419037a3d265914042fde795563094f38ddd88b42444d4afa8c
# Debian package versions rotate with security fixes; the base image is what is pinned, by tag.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends git ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*
RUN git init /src \
 && git -C /src remote add origin https://github.com/nicolasAmat/SMPT.git \
 && git -C /src fetch --depth 1 origin "${TOOL_COMMIT}" \
 && git -C /src checkout --detach FETCH_HEAD \
 && rm -rf /src/.git
RUN curl -fsSL -o /tmp/tina.tgz "${TINA_URL}" \
 && printf '%s  /tmp/tina.tgz\n' "${TINA_SHA256}" > /tmp/tina.sha256 \
 && sha256sum -c /tmp/tina.sha256 \
 && mkdir -p /opt/tina \
 && tar xzf /tmp/tina.tgz -C /opt/tina --strip-components=1 --exclude='*/doc' --exclude='*/nets' --exclude='*/extras'

# ---- Stage 2: the runtime image --------------------------------------------------------------
FROM python:3.14-slim-bookworm AS runtime
ARG TOOL_VERSION=5.0-82206dd
LABEL org.opencontainers.image.title="pn-llm-verif engine smpt" \
      org.opencontainers.image.version="${TOOL_VERSION}" \
      org.opencontainers.image.licenses="GPL-3.0-or-later" \
      org.opencontainers.image.source="https://github.com/nicolasAmat/SMPT"

COPY engines/common/requirements.txt /tmp/requirements.txt
COPY engines/smpt/requirements.txt /tmp/smpt-requirements.txt
# z3 is the SMT solver SMPT talks to; its Debian version follows the base image.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends z3 \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home runner \
 && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt -r /tmp/smpt-requirements.txt \
 && rm /tmp/requirements.txt /tmp/smpt-requirements.txt

COPY --from=fetch /src /opt/SMPT
COPY --from=fetch /opt/tina /opt/tina
# The adapter kit and the models of the contract: the only code shared with the platform.
COPY api/app/__init__.py /opt/pnverif/app/__init__.py
COPY api/app/domain /opt/pnverif/app/domain
COPY engines/common/pnverif_engine /opt/pnverif/pnverif_engine
COPY engines/smpt/adapter.py /opt/adapter/adapter.py

ENV PYTHONPATH=/opt/pnverif PYTHONDONTWRITEBYTECODE=1 TOOL_VERSION=${TOOL_VERSION}
USER 10001
ENTRYPOINT ["python", "/opt/adapter/adapter.py"]
