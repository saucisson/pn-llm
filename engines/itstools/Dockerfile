# ITS-Tools, from the contest wrapper's distribution. Build from the repository root:
#   docker build -f engines/itstools/Dockerfile -t pn-llm-verif/itstools:1.0.0.202609112134 .
# Licence: GPL-3.0 (https://github.com/lip6/ITSTools). The image is built locally and not
# redistributed by this project; anyone who publishes it must offer the source.
# The authors publish the product only as "the latest build" at a fixed URL, so the version is
# pinned by the SHA-256 of the archive and the build fails when upstream publishes a new one:
# a maintainer then reads the changes and updates the checksum and the version together.

# ---- Stage 1: fetch the product and check it -------------------------------------------------
FROM python:3.14-slim AS build
ARG TOOL_URL=https://lip6.github.io/ITSTools/fr.lip6.move.gal.itscl.product-linux.gtk.x86_64.zip
ARG TOOL_SHA256=faef344a641ca190e34eedee71a5cc44ac7051003841a431da4edfdf0bb7ae5f
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl unzip ca-certificates gcc libc6-dev \
 && rm -rf /var/lib/apt/lists/*
RUN curl -fsSL "${TOOL_URL}" -o /tmp/product.zip \
 && printf '%s  /tmp/product.zip\n' "${TOOL_SHA256}" > /tmp/product.sha256 \
 && sha256sum -c /tmp/product.sha256 \
 && mkdir -p /opt/tool \
 && unzip -q /tmp/product.zip -d /opt/tool \
 && find /opt/tool/plugins -path '*/bin/*' -type f -exec chmod a+rx {} +
# The tool tries to make its bundled binaries executable when it runs, which a read-only root
# refuses: they are made executable here, and a small shim lets the tool's own attempt succeed.
COPY engines/itstools/keepmode.c /tmp/keepmode.c
RUN mkdir -p /opt/shim && gcc -shared -fPIC -O2 -o /opt/shim/keepmode.so /tmp/keepmode.c -ldl

# ---- Stage 2: the runtime image --------------------------------------------------------------
FROM python:3.14-slim AS runtime
ARG TOOL_VERSION=1.0.0.202609112134
LABEL org.opencontainers.image.title="pn-llm-verif engine itstools" \
      org.opencontainers.image.version="${TOOL_VERSION}" \
      org.opencontainers.image.licenses="GPL-3.0-only" \
      org.opencontainers.image.source="https://github.com/lip6/ITSTools"

COPY engines/common/requirements.txt /tmp/requirements.txt
# The product runs on a JVM and its bundled solvers need a few system libraries.
# hadolint ignore=DL3008
RUN apt-get update \
 && apt-get install -y --no-install-recommends openjdk-21-jre-headless libpopt0 libltdl7 libgmp10 psmisc \
 && rm -rf /var/lib/apt/lists/* \
 && useradd --system --uid 10001 --no-create-home runner \
 && pip install --no-cache-dir --require-hashes -r /tmp/requirements.txt \
 && rm /tmp/requirements.txt

COPY --from=build /opt/tool /opt/tool
COPY --from=build /opt/shim /opt/shim
# The adapter kit and the models of the contract: the only code shared with the platform.
COPY api/app/__init__.py /opt/pnverif/app/__init__.py
COPY api/app/domain /opt/pnverif/app/domain
COPY engines/common/pnverif_engine /opt/pnverif/pnverif_engine
COPY engines/itstools/adapter.py /opt/adapter/adapter.py

ENV PYTHONPATH=/opt/pnverif PYTHONDONTWRITEBYTECODE=1 TOOL_VERSION=${TOOL_VERSION}
USER 10001
ENTRYPOINT ["python", "/opt/adapter/adapter.py"]
