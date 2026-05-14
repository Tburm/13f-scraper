FROM ghcr.io/astral-sh/uv:python3.11-bookworm-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock* README.md ./
COPY src ./src
RUN uv sync --locked --no-dev

VOLUME ["/app/state"]
CMD ["uv", "run", "--locked", "--no-dev", "salp-13f-monitor"]
