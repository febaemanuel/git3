FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primeiro (melhora cache build)
COPY requirements.txt .

# Instalar libs Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar a aplicação TODA
COPY . .

# Criar diretório pra uploads (se não existir)
RUN mkdir -p /app/uploads

# Expor porta usada pelo gunicorn
EXPOSE 5000

# Configurar timezone
ENV TZ=America/Fortaleza
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Entry point de produção
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "--log-level", "info", "app:app"]
