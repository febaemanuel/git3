#!/usr/bin/env python3
"""
Script de teste para verificar se o Celery consegue processar tasks de consultas
"""

import sys
import os

# Adicionar diretório atual ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

print("=" * 60)
print("TESTE DE CELERY - MODO CONSULTA")
print("=" * 60)
print()

# 1. Testar importação do Celery
print("1. Testando importação do Celery...")
try:
    from celery_app import celery
    print("   ✓ celery_app importado com sucesso")
except ImportError as e:
    print(f"   ✗ ERRO ao importar celery_app: {e}")
    sys.exit(1)

# 2. Testar importação das tasks
print("\n2. Testando importação das tasks...")
try:
    from tasks import enviar_campanha_consultas_task
    print("   ✓ enviar_campanha_consultas_task importada com sucesso")
except ImportError as e:
    print(f"   ✗ ERRO ao importar task: {e}")
    sys.exit(1)

# 3. Verificar se a task está registrada no Celery
print("\n3. Verificando registro da task no Celery...")
try:
    registered_tasks = list(celery.tasks.keys())
    consulta_tasks = [t for t in registered_tasks if 'consulta' in t.lower()]

    if consulta_tasks:
        print(f"   ✓ Tasks de consulta encontradas: {consulta_tasks}")
    else:
        print("   ⚠ Nenhuma task de consulta encontrada")
        print(f"   Tasks registradas: {registered_tasks[:10]}...")
except Exception as e:
    print(f"   ✗ ERRO ao verificar tasks: {e}")

# 4. Testar conexão com Redis
print("\n4. Testando conexão com Redis...")
try:
    from celery_app import REDIS_URL
    import redis

    r = redis.from_url(REDIS_URL)
    r.ping()
    print(f"   ✓ Redis conectado em {REDIS_URL}")
except Exception as e:
    print(f"   ✗ ERRO ao conectar com Redis: {e}")

# 5. Verificar se consegue importar modelos necessários
print("\n5. Testando importação dos modelos...")
try:
    from app import app, db, CampanhaConsulta, AgendamentoConsulta
    print("   ✓ Modelos importados com sucesso")

    with app.app_context():
        # Verificar se tem campanhas
        total_campanhas = CampanhaConsulta.query.count()
        total_consultas = AgendamentoConsulta.query.count()
        print(f"   ℹ Total de campanhas: {total_campanhas}")
        print(f"   ℹ Total de consultas: {total_consultas}")

        # Verificar se há consultas aguardando envio
        aguardando = AgendamentoConsulta.query.filter_by(
            status='AGUARDANDO_ENVIO'
        ).count()
        print(f"   ℹ Consultas aguardando envio: {aguardando}")

except Exception as e:
    print(f"   ✗ ERRO ao importar modelos ou consultar DB: {e}")
    import traceback
    traceback.print_exc()

# 6. Testar disparo manual da task (sem executar)
print("\n6. Testando disparo da task (modo teste)...")
try:
    # Buscar uma campanha para teste
    from app import app, CampanhaConsulta
    with app.app_context():
        campanha = CampanhaConsulta.query.first()

        if campanha:
            print(f"   ℹ Campanha encontrada: ID={campanha.id}, Nome={campanha.nome}")
            print(f"   ℹ Status: {campanha.status}")

            # NÃO vamos disparar de verdade, apenas verificar a sintaxe
            # task = enviar_campanha_consultas_task.delay(campanha.id)
            print(f"   ✓ Sintaxe OK para disparar: enviar_campanha_consultas_task.delay({campanha.id})")
        else:
            print("   ⚠ Nenhuma campanha encontrada para teste")

except Exception as e:
    print(f"   ✗ ERRO: {e}")
    import traceback
    traceback.print_exc()

print("\n" + "=" * 60)
print("FIM DO DIAGNÓSTICO")
print("=" * 60)
