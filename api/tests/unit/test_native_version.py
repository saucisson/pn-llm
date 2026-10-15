"""Results are cached by the native engine's version: a change to what it computes bumps it."""

import importlib.util
from pathlib import Path

from app.infrastructure.engine_registry import DEFAULT_ENGINES

ROOT = Path(__file__).resolve().parents[3]


def load_digest_script():
    spec = importlib.util.spec_from_file_location(
        "native_digest", ROOT / "scripts" / "native_digest.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_sources_of_the_native_engine_match_the_digest_its_version_was_released_with():
    script = load_digest_script()
    recorded = (ROOT / "engines" / "native" / "DIGEST").read_text().strip()
    assert script.digest() == recorded, (
        "The analyses changed. Bump the version of the native engine in "
        "api/app/infrastructure/engine_registry.py, engines/native/Dockerfile, docker-compose.yml "
        "and docs/engines.md, then run: python3 scripts/native_digest.py --write"
    )


def test_the_version_in_the_dockerfile_is_the_one_in_the_registry():
    dockerfile = (ROOT / "engines" / "native" / "Dockerfile").read_text()
    version = DEFAULT_ENGINES["native"].version
    assert f"ARG TOOL_VERSION={version}\n" in dockerfile
    assert DEFAULT_ENGINES["native"].image == f"pn-llm-verif/native:{version}"
