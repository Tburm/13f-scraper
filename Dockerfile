FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1
COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --no-cache-dir .
VOLUME ["/app/state"]
CMD ["salp-13f-monitor"]
