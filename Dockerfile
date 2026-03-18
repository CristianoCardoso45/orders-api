# Multi-stage build para imagem leve.
# python:3.12-slim é a base mínima com suporte a compilação de extensões C
# (necessário para asyncpg e alguns pacotes OpenTelemetry).

FROM python:3.12-slim AS base

WORKDIR /app

# Variáveis de ambiente para otimizar Python em container
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

# Instalar dependências do sistema necessárias para asyncpg
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev && \
    rm -rf /var/lib/apt/lists/*

# Instalar ferramentas base primeiro (incluindo pip atualizado)
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# Copiar apenas os gerenciadores primeiro
COPY pyproject.toml ./

# Fazer a instalacao local
RUN pip install --no-cache-dir .

# Copiar restante do codigo da aplicacao
COPY app/ ./app/
COPY alembic/ ./alembic/
COPY alembic.ini ./
COPY mocks/ ./mocks/

# ── Entrypoint padrão: API ──
# O docker-compose sobrescreve o command para o worker
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
