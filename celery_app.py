"""
=============================================================================
CELERY CONFIGURATION
=============================================================================
Configuração centralizada do Celery para tarefas assíncronas
"""

from celery import Celery
from celery.schedules import crontab
import os

# Configuração do broker (Redis)
REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')

# Criar instância Celery
celery = Celery(
    'busca_ativa',
    broker=REDIS_URL,
    backend=REDIS_URL,
    include=['tasks']  # Importar tasks automaticamente
)

# Configurações otimizadas para produção
celery.conf.update(
    # Serialização
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='America/Fortaleza',
    enable_utc=True,

    # Resultados
    result_expires=3600,  # 1 hora (limpa automaticamente)
    result_extended=True,  # Armazena info adicional sobre tasks

    # Retry e confiabilidade
    task_acks_late=True,  # Acknowledge task após completar (permite retry em falha)
    task_reject_on_worker_lost=True,  # Reprocessa se worker cair

    # Performance
    worker_prefetch_multiplier=1,  # Pega 1 task por vez (melhor para tasks longas)
    worker_max_tasks_per_child=100,  # Reinicia worker após 100 tasks (previne memory leak)

    # Segurança e estabilidade
    broker_connection_retry_on_startup=True,  # Retry ao conectar no broker
    worker_cancel_long_running_tasks_on_connection_loss=False,  # Não cancela tasks em andamento

    # Logging
    worker_log_format='[%(asctime)s: %(levelname)s/%(processName)s] %(message)s',
    worker_task_log_format='[%(asctime)s: %(levelname)s/%(processName)s][%(task_name)s(%(task_id)s)] %(message)s',
)

# Tarefas periódicas (Celery Beat)
celery.conf.beat_schedule = {
    # Follow-up automático todo dia às 9h
    'follow-up-automatico-diario': {
        'task': 'tasks.follow_up_automatico_task',
        'schedule': crontab(hour=9, minute=0),  # 9:00 AM todos os dias
        'options': {'expires': 3600}  # Task expira em 1h se não executar
    },

    # Retomar campanhas pausadas a cada hora (durante horário comercial)
    'retomar-campanhas-automaticas': {
        'task': 'tasks.retomar_campanhas_automaticas',
        'schedule': crontab(minute=0, hour='8-21'),  # De hora em hora, das 8h às 21h
        'options': {'expires': 1800}  # Task expira em 30min se não executar
    },

    # Retomar campanhas de CONSULTAS pausadas a cada hora (durante horário comercial)
    'retomar-campanhas-consultas-automaticas': {
        'task': 'tasks.retomar_campanhas_consultas_automaticas',
        'schedule': crontab(minute=0, hour='8-21'),  # De hora em hora, das 8h às 21h
        'options': {'expires': 1800}  # Task expira em 30min se não executar
    },

    # Limpar tasks antigas a cada 6 horas
    'limpar-tasks-antigas': {
        'task': 'tasks.limpar_tasks_antigas',
        'schedule': crontab(minute=0, hour='*/6'),  # A cada 6 horas
    },
}

if __name__ == '__main__':
    celery.start()
