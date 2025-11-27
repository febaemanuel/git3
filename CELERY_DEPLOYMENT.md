# Deployment com Celery - Busca Ativa

## Visão Geral

O sistema foi migrado de threads Python para **Celery** para processamento assíncrono de tarefas em background. Esta migração traz benefícios de:

- **Persistência**: Tarefas sobrevivem a reinicializações do servidor
- **Retry Automático**: Falhas são automaticamente retentadas com backoff exponencial
- **Monitoramento**: Status de tarefas em tempo real
- **Escalabilidade**: Capacidade de adicionar múltiplos workers
- **Agendamento**: Tarefas periódicas executadas automaticamente

## Arquitetura

```
┌─────────────┐     ┌──────────┐     ┌────────────────┐
│   Flask     │────▶│  Redis   │◀────│ Celery Worker  │
│   Web App   │     │  Broker  │     │  (4 workers)   │
└─────────────┘     └──────────┘     └────────────────┘
                          │
                          ▼
                    ┌────────────┐
                    │ Celery Beat│
                    │ (Scheduler)│
                    └────────────┘
```

## Componentes

### 1. Redis
- **Função**: Message broker e backend de resultados
- **Porta**: 6379
- **Container**: `busca-ativa-redis`

### 2. Celery Worker
- **Função**: Processa tarefas assíncronas
- **Workers**: 4 concurrent workers
- **Container**: `busca-ativa-celery-worker`
- **Tasks**:
  - `validar_campanha_task`: Validação de números WhatsApp
  - `enviar_campanha_task`: Envio de campanhas
  - `follow_up_automatico_task`: Follow-up diário
  - `limpar_tasks_antigas`: Limpeza de tasks antigas

### 3. Celery Beat
- **Função**: Agendador de tarefas periódicas
- **Container**: `busca-ativa-celery-beat`
- **Agendamentos**:
  - Follow-up automático: Diariamente às 9h
  - Limpeza de tasks: A cada 6 horas

## Deployment com Docker

### Iniciar todos os serviços

```bash
docker-compose up -d
```

Isso inicia:
- PostgreSQL (db)
- Redis (redis)
- Flask Web App (web)
- Celery Worker (celery_worker)
- Celery Beat (celery_beat)

### Ver logs

```bash
# Ver logs de todos os serviços
docker-compose logs -f

# Ver logs específicos
docker-compose logs -f celery_worker
docker-compose logs -f celery_beat
docker-compose logs -f redis
```

### Reiniciar serviços

```bash
# Reiniciar Celery worker
docker-compose restart celery_worker

# Reiniciar Celery beat
docker-compose restart celery_beat

# Reiniciar todos
docker-compose restart
```

### Parar serviços

```bash
docker-compose down
```

## Deployment Manual (sem Docker)

### 1. Instalar dependências

```bash
pip install -r requirements.txt
```

### 2. Iniciar Redis

```bash
# Ubuntu/Debian
sudo apt-get install redis-server
sudo systemctl start redis

# macOS
brew install redis
brew services start redis

# Ou via Docker
docker run -d -p 6379:6379 redis:7-alpine
```

### 3. Iniciar Celery Worker

```bash
# Terminal 1: Celery Worker
celery -A celery_app.celery worker --loglevel=info --concurrency=4
```

### 4. Iniciar Celery Beat (opcional, para tarefas periódicas)

```bash
# Terminal 2: Celery Beat
celery -A celery_app.celery beat --loglevel=info
```

### 5. Iniciar Flask App

```bash
# Terminal 3: Flask
flask run
# OU
gunicorn --bind 0.0.0.0:5000 app:app
```

## Configuração de Ambiente

Adicione ao arquivo `.env`:

```bash
# Redis URL
REDIS_URL=redis://localhost:6379/0
```

No Docker, use:
```bash
REDIS_URL=redis://redis:6379/0
```

## Monitoramento de Tasks

### Via API

```bash
# Verificar status de uma task
curl http://localhost:5000/api/task/{task_id}/status

# Cancelar uma task
curl -X POST http://localhost:5000/api/task/{task_id}/cancel
```

### Via Interface Web

As campanhas retornam `task_id` e `status_url` que podem ser usados para monitoramento em tempo real.

Exemplo de resposta ao iniciar campanha:
```json
{
  "sucesso": true,
  "task_id": "abc123-def456-...",
  "status_url": "/api/task/abc123-def456-.../status"
}
```

### Flower (Monitoramento Avançado - Opcional)

```bash
# Instalar Flower
pip install flower

# Iniciar Flower
celery -A celery_app.celery flower --port=5555

# Acessar: http://localhost:5555
```

## Tarefas Periódicas

### Follow-up Automático
- **Quando**: Diariamente às 9h (horário de Fortaleza)
- **O que faz**: Envia mensagens de follow-up para pacientes sem resposta
- **Task**: `tasks.follow_up_automatico_task`

### Limpeza de Tasks Antigas
- **Quando**: A cada 6 horas
- **O que faz**: Remove tasks antigas do Redis
- **Task**: `tasks.limpar_tasks_antigas`

## Escalabilidade

### Aumentar Workers

```bash
# Docker: Editar docker-compose.yml
celery_worker:
  command: celery -A celery_app.celery worker --loglevel=info --concurrency=8

# Manual
celery -A celery_app.celery worker --loglevel=info --concurrency=8
```

### Múltiplas Instâncias de Workers

```bash
# Terminal 1
celery -A celery_app.celery worker --loglevel=info --concurrency=4 -n worker1@%h

# Terminal 2
celery -A celery_app.celery worker --loglevel=info --concurrency=4 -n worker2@%h
```

## Troubleshooting

### Tasks não estão sendo processadas

1. Verificar se Redis está rodando:
   ```bash
   docker-compose ps redis
   # OU
   redis-cli ping  # Deve retornar PONG
   ```

2. Verificar se Celery Worker está rodando:
   ```bash
   docker-compose ps celery_worker
   docker-compose logs celery_worker
   ```

3. Verificar conexão Redis:
   ```bash
   docker-compose exec celery_worker celery -A celery_app.celery inspect active
   ```

### Tasks ficam em estado PENDING

- Certifique-se de que o Celery Worker está rodando
- Verifique a conexão com Redis
- Verifique logs do worker para erros

### Tasks falham com erro de banco de dados

- Certifique-se de que o PostgreSQL está acessível
- Verifique as variáveis de ambiente de conexão do banco
- Verifique se o banco foi inicializado (`flask init-db`)

### Tarefas periódicas não executam

- Verifique se Celery Beat está rodando
- Verifique logs do beat: `docker-compose logs celery_beat`
- Verifique timezone em `celery_app.py` (atualmente: America/Fortaleza)

## Performance

### Configurações Atuais

- **worker_prefetch_multiplier**: 1 (pega 1 task por vez - ideal para tasks longas)
- **worker_max_tasks_per_child**: 100 (reinicia worker após 100 tasks - previne memory leak)
- **result_expires**: 3600s (1 hora - resultados expiram após 1h)
- **task_acks_late**: True (acknowledge após completar - permite retry em falha)

### Ajustar para alta carga

Se você tiver muitas tasks curtas (< 1 segundo):

```python
# celery_app.py
celery.conf.update(
    worker_prefetch_multiplier=4,  # Pega 4 tasks por vez
    worker_concurrency=8,           # 8 workers simultâneos
)
```

## Rollback (Voltar para Threads)

Se necessário reverter para threads:

1. Restaurar versão anterior de `app.py`
2. Comentar imports de Celery
3. Usar funções `*_bg` originais com `threading.Thread`

**Nota**: Não recomendado - Celery é significativamente mais robusto.

## Conclusão

A migração para Celery torna o sistema mais robusto, escalável e confiável para processamento de tarefas em background, especialmente para envio de campanhas e validação de números em larga escala.

Para mais informações:
- [Documentação Celery](https://docs.celeryq.dev/)
- [Celery Best Practices](https://docs.celeryq.dev/en/stable/userguide/tasks.html#best-practices)
