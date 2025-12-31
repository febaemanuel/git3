#!/bin/bash

echo "=========================================="
echo "DIAGNÓSTICO - MODO CONSULTA"
echo "=========================================="
echo ""

echo "1. Verificando containers em execução..."
docker ps --format "table {{.Names}}\t{{.Status}}" | grep busca-ativa

echo ""
echo "2. Verificando se Celery Worker está rodando..."
docker ps | grep -q celery-worker && echo "✓ Celery Worker está rodando" || echo "✗ Celery Worker NÃO está rodando"

echo ""
echo "3. Verificando logs do Celery Worker (últimas 30 linhas)..."
docker logs busca-ativa-celery-worker --tail 30

echo ""
echo "4. Verificando se a task de consultas foi registrada..."
docker exec busca-ativa-celery-worker celery -A celery_app.celery inspect registered 2>&1 | grep -i consulta

echo ""
echo "5. Verificando logs da aplicação web (últimas 20 linhas)..."
docker logs busca-ativa-web --tail 20

echo ""
echo "6. Testando conexão com Redis..."
docker exec busca-ativa-redis redis-cli ping

echo ""
echo "7. Verificando tasks pendentes no Celery..."
docker exec busca-ativa-celery-worker celery -A celery_app.celery inspect active 2>&1 | head -20

echo ""
echo "=========================================="
echo "DIAGNÓSTICO COMPLETO"
echo "=========================================="
