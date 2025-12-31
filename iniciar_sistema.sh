#!/bin/bash

###############################################################################
# SCRIPT DE INICIALIZAÇÃO DO SISTEMA DE BUSCA ATIVA
###############################################################################
# Este script verifica e inicia todos os componentes necessários
###############################################################################

set -e  # Parar em caso de erro

echo "═══════════════════════════════════════════════════════════════"
echo "  INICIANDO SISTEMA DE BUSCA ATIVA - HUWC"
echo "═══════════════════════════════════════════════════════════════"
echo ""

# Cores para output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Função para verificar se comando existe
command_exists() {
    command -v "$1" >/dev/null 2>&1
}

# Função para verificar se processo está rodando
is_running() {
    pgrep -f "$1" > /dev/null 2>&1
}

# Ir para diretório do projeto
cd "$(dirname "$0")"
PROJECT_DIR=$(pwd)
echo -e "${GREEN}✓${NC} Diretório do projeto: $PROJECT_DIR"
echo ""

###############################################################################
# 1. VERIFICAR REDIS
###############################################################################
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [1/3] Verificando Redis (Broker do Celery)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command_exists redis-cli; then
    echo -e "${RED}✗${NC} Redis não está instalado!"
    echo ""
    echo "Instalando Redis..."
    if command_exists apt-get; then
        sudo apt-get update
        sudo apt-get install -y redis-server
    elif command_exists yum; then
        sudo yum install -y redis
    else
        echo -e "${RED}ERROR:${NC} Não foi possível instalar Redis automaticamente"
        echo "Instale manualmente: https://redis.io/download"
        exit 1
    fi
fi

# Verificar se Redis está rodando
if ! is_running "redis-server"; then
    echo -e "${YELLOW}⚠${NC} Redis não está rodando. Iniciando..."

    # Tentar iniciar via systemd
    if command_exists systemctl; then
        sudo systemctl start redis
        sudo systemctl enable redis
        echo -e "${GREEN}✓${NC} Redis iniciado via systemctl"
    else
        # Iniciar manualmente em background
        redis-server --daemonize yes
        echo -e "${GREEN}✓${NC} Redis iniciado manualmente"
    fi

    sleep 2
fi

# Testar conexão
if redis-cli ping | grep -q PONG; then
    echo -e "${GREEN}✓${NC} Redis está rodando e respondendo!"
else
    echo -e "${RED}✗${NC} Redis não está respondendo!"
    echo "Tente iniciar manualmente: redis-server"
    exit 1
fi

echo ""

###############################################################################
# 2. VERIFICAR E INICIAR CELERY WORKER
###############################################################################
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [2/3] Verificando Celery Worker"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if ! command_exists celery; then
    echo -e "${RED}✗${NC} Celery não está instalado!"
    echo "Instalando..."
    pip install celery redis
fi

# Verificar se worker já está rodando
if is_running "celery.*worker"; then
    echo -e "${YELLOW}⚠${NC} Celery Worker já está rodando"
    echo "PID: $(pgrep -f 'celery.*worker')"

    read -p "Deseja reiniciar? (s/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        echo "Parando worker antigo..."
        pkill -f "celery.*worker"
        sleep 2
    else
        echo -e "${GREEN}✓${NC} Usando worker existente"
        CELERY_RUNNING=true
    fi
fi

if [ -z "$CELERY_RUNNING" ]; then
    echo "Iniciando Celery Worker em background..."

    # Criar diretório de logs
    mkdir -p logs

    # Iniciar Celery em background
    nohup celery -A celery_app worker --loglevel=info \
        > logs/celery_worker.log 2>&1 &

    CELERY_PID=$!
    echo -e "${GREEN}✓${NC} Celery Worker iniciado! PID: $CELERY_PID"
    echo "   Logs: $PROJECT_DIR/logs/celery_worker.log"

    # Aguardar worker iniciar
    echo -n "Aguardando worker inicializar"
    for i in {1..10}; do
        if is_running "celery.*worker"; then
            echo " OK!"
            break
        fi
        echo -n "."
        sleep 1
    done
fi

echo ""

###############################################################################
# 3. VERIFICAR E INICIAR FLASK
###############################################################################
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  [3/3] Verificando Flask (Servidor Web)"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

if is_running "python.*app.py"; then
    echo -e "${YELLOW}⚠${NC} Flask já está rodando"
    echo "PID: $(pgrep -f 'python.*app.py')"

    read -p "Deseja reiniciar? (s/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Ss]$ ]]; then
        echo "Parando Flask antigo..."
        pkill -f "python.*app.py"
        sleep 2
    else
        echo -e "${GREEN}✓${NC} Usando Flask existente"
        FLASK_RUNNING=true
    fi
fi

if [ -z "$FLASK_RUNNING" ]; then
    echo "Iniciando Flask em background..."

    # Criar diretório de logs
    mkdir -p logs

    # Iniciar Flask em background
    nohup python app.py > logs/flask.log 2>&1 &

    FLASK_PID=$!
    echo -e "${GREEN}✓${NC} Flask iniciado! PID: $FLASK_PID"
    echo "   Logs: $PROJECT_DIR/logs/flask.log"
    echo "   URL: http://localhost:5001"

    # Aguardar Flask iniciar
    echo -n "Aguardando Flask inicializar"
    for i in {1..15}; do
        if curl -s http://localhost:5001 > /dev/null 2>&1; then
            echo " OK!"
            break
        fi
        echo -n "."
        sleep 1
    done
fi

echo ""

###############################################################################
# RESUMO
###############################################################################
echo "═══════════════════════════════════════════════════════════════"
echo "  ✅ SISTEMA INICIADO COM SUCESSO!"
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo "Componentes rodando:"
echo "  • Redis       → Porta 6379"
echo "  • Celery      → PID $(pgrep -f 'celery.*worker' || echo 'N/A')"
echo "  • Flask       → http://localhost:5001"
echo ""
echo "Logs:"
echo "  • Celery      → tail -f logs/celery_worker.log"
echo "  • Flask       → tail -f logs/flask.log"
echo ""
echo "Comandos úteis:"
echo "  • Ver logs Celery em tempo real:"
echo "    tail -f logs/celery_worker.log"
echo ""
echo "  • Ver processos rodando:"
echo "    ps aux | grep -E '(celery|redis|flask)' | grep -v grep"
echo ""
echo "  • Parar tudo:"
echo "    pkill -f 'celery.*worker'; pkill -f 'python.*app.py'"
echo ""
echo "═══════════════════════════════════════════════════════════════"
echo ""
echo -e "${GREEN}Agora acesse http://localhost:5001 e teste!${NC}"
echo ""
