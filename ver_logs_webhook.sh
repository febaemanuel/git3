#!/bin/bash

echo "=========================================="
echo "LOGS EM TEMPO REAL - MODO CONSULTA"
echo "=========================================="
echo ""

echo "Verificando últimas mensagens do webhook..."
echo ""

echo "--- LOGS DO WEB (últimas 100 linhas) ---"
docker logs busca-ativa-web --tail 100 | grep -i "webhook\|consulta" | tail -30

echo ""
echo "--- LOGS DO CELERY WORKER (últimas 50 linhas) ---"
docker logs busca-ativa-celery-worker --tail 50

echo ""
echo "=========================================="
echo "Para acompanhar em tempo real:"
echo "docker logs -f busca-ativa-web"
echo "=========================================="
