# Lotus companion server: tuning UI, presets, proxy to the Pico.
#   docker build -t lotus-server .
#   docker run -p 8000:8000 -e LOTUS_URL=http://10.0.0.22 -v lotus-data:/data lotus-server
FROM python:3.12-slim
COPY --from=ghcr.io/astral-sh/uv:latest /uv /bin/uv
WORKDIR /app
ENV UV_LINK_MODE=copy UV_COMPILE_BYTECODE=1
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --group server
# Firmware modules (imported through the desktop stubs for validation/simulation) + server.
COPY led.py patterns.py ./
COPY stubs ./stubs
COPY server ./server
ENV LOTUS_URL=http://10.0.0.22 LOTUS_DATA=/data
VOLUME /data
EXPOSE 8000
CMD ["uv", "run", "--no-sync", "uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "8000"]
