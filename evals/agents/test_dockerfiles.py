# uvx --with pytest python -m pytest agents/test_dockerfiles.py
"""The eval images are the sandbox the agents are compared in, so they must differ only in the agent's CLI.

Every image is built from pinned inputs (the base images by digest, the CLI by version, every Python package by exact
version from requirements-evals.lock) and carries the same toolchain lines. Only the Debian packages come from apt.
The Gemini image is the exception for the CLI: the agy installer serves only the latest build, so its Dockerfile
fails the build when the version is not AGY_VERSION instead of pinning the download."""

import re
from pathlib import Path

import pytest

HERE = Path(__file__).parent
AGENTS = ["claude", "codex", "gemini", "opencode", "qoder"]
CLI = {"claude": "ARG CLAUDE_VERSION=", "codex": "ARG CODEX_VERSION=", "gemini": "ARG AGY_VERSION=",
       "opencode": "ARG OPENCODE_VERSION=", "qoder": "ARG QODER_VERSION="}
SHARED = [
    "FROM python:3.12-slim-bookworm@sha256:34386ef0cb081344d7ec1c103ba398e6e9f64e9ab3a1509accc92a4e24a07258",
    "COPY --from=ghcr.io/astral-sh/uv:0.8.24@sha256:1d31be550ff927957472b2a491dc3de1ea9b5c2d319a9cea5b6a48021e2990a6 /uv /uvx /usr/local/bin/",
    "    tesseract-ocr tesseract-ocr-eng tesseract-ocr-jpn libglib2.0-0 \\",
    "COPY evals/agents/requirements-evals.lock /tmp/requirements-evals.lock",
    "RUN uv venv /opt/venv && VIRTUAL_ENV=/opt/venv uv pip install --no-cache --no-deps -r /tmp/requirements-evals.lock \\",
    "RUN echo 'export PATH=/opt/venv/bin:$PATH' > /etc/profile.d/venv.sh",
    "RUN python -c \"import cv2, skimage, pypdfium2, pyproj\" && tesseract --list-langs",
]


def dockerfile(agent):
    return (HERE / f"Dockerfile.evals.{agent}").read_text()


@pytest.mark.parametrize("agent", AGENTS)
def test_the_image_is_built_from_pinned_inputs_and_the_shared_toolchain(agent):
    d = dockerfile(agent)
    lines = d.splitlines()
    froms = [l for l in lines if l.startswith(("FROM", "COPY --from"))]
    assert froms and all("@sha256:" in l for l in froms), froms
    assert re.search(re.escape(CLI[agent]) + r"\d+\.\d+\.\d+", d), CLI[agent]
    for s in SHARED:
        assert s in lines, (agent, s)
    assert ">=" not in d and "pip install --no-cache \\" not in d


@pytest.mark.parametrize("agent", AGENTS)
def test_each_image_names_its_own_runner(agent):
    d = dockerfile(agent)
    assert f"docker build -f evals/agents/Dockerfile.evals.{agent} -t geo-ref-skills-evals-{agent} ." in d
    assert f"evals/agents/run_{agent}_docker.sh" in d
    assert (HERE / f"run_{agent}_docker.sh").exists()


def test_the_lock_names_exact_versions():
    lock = [l for l in (HERE / "requirements-evals.lock").read_text().splitlines() if l.strip() and not l.startswith("#")]
    assert lock and all(re.fullmatch(r"[A-Za-z0-9_.-]+==[A-Za-z0-9_.+-]+", l) for l in lock), lock
    names = {l.split("==")[0] for l in lock}
    assert {"numpy", "scipy", "opencv-python-headless", "scikit-image", "pyproj", "pypdfium2", "shapely", "cairosvg",
            "pillow", "requests", "pyyaml", "pytest"} <= names
    assert "pypdfium2==5.14.0" in lock
