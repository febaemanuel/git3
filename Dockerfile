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
