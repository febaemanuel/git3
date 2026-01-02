FROM python:3.11-slim

WORKDIR /app

# Dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    postgresql-client \
    # OCR - tesseract e poppler para pdf2image
    tesseract-ocr \
    tesseract-ocr-por \
    poppler-utils \
    && rm -rf /var/lib/apt/lists/*

# Copiar requirements primeiro (melhora cache build)
COPY requirements.txt .

# Instalar libs Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar a aplicação TODA
COPY . .

# Copiar e configurar entrypoint
COPY docker-entrypoint.sh /usr/local/bin/
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# Criar diretórios necessários
RUN mkdir -p /app/uploads /app/uploads/temp

# Expor porta usada pelo gunicorn
EXPOSE 5000

# Configurar timezone
ENV TZ=America/Fortaleza
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH=/app

# Entry point que cria pastas antes de executar o comando
ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]

# Comando padrão de produção
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "--log-level", "info", "app:app"]
