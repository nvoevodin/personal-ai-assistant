FROM python:3.12-slim

# Prevent Python from writing bytecode and enable unbuffered output
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies if required
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install application dependencies
COPY pyproject.toml README.md ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy application source code
COPY agent/ ./agent/
COPY bot/ ./bot/
COPY connectors/ ./connectors/
COPY core/ ./core/

# Create a non-privileged user and switch to it
RUN useradd -u 1000 -m appuser && chown -R appuser:appuser /app
USER appuser

# Healthcheck or default command
CMD ["python", "-m", "bot.main"]
