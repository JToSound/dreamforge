# DreamForge offline sandbox — deterministic core + verified-export tooling.
FROM python:3.12-slim AS base

WORKDIR /app

# Layer: pinned dependencies first for cache friendliness.
COPY constraints.txt pyproject.toml README.md LICENSE ./
COPY src ./src

RUN python -m pip install --no-cache-dir -c constraints.txt .

# Test stage: full suite inside the container (container smoke).
FROM base AS test
COPY tests ./tests
COPY examples ./examples
COPY scripts ./scripts
COPY docs ./docs
RUN python -m pip install --no-cache-dir -c constraints.txt pytest hypothesis
CMD ["python", "-m", "pytest", "-q"]

FROM base AS final
# Offline demo entrypoint; no network egress at runtime.
CMD ["python", "-m", "dreamforge.demo"]
