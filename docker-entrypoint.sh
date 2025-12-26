#!/bin/bash
set -e

# Criar diretórios necessários (importante para volumes bind mount)
mkdir -p /app/uploads/temp

echo "✓ Diretórios criados: /app/uploads/temp"

# Executar comando passado como argumento
exec "$@"
