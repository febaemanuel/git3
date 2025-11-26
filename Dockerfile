<<<<<<< HEAD
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

ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Entry point de produção
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "--log-level", "info", "app:app"]
=======
# Imagem base Python 3.11
FROM python:3.11-slim

# Define diretório de trabalho
WORKDIR /app

# Instalar dependências do sistema
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copiar arquivos de requisitos
COPY requirements.txt .

# Instalar dependências Python
RUN pip install --no-cache-dir -r requirements.txt

# Copiar todo o código da aplicação
COPY . .

# Criar diretório para uploads
RUN mkdir -p uploads

# Expor porta 5000
EXPOSE 5000

# Variáveis de ambiente padrão
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Comando para iniciar a aplicação
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "4", "--timeout", "120", "app:app"]
>>>>>>> b601f6d8b0dd917c92b7d95feaf1375f7763c6c3
