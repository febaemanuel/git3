# Correção: Envio de Mensagens no Modo Consulta

## 🐛 Problema Identificado

O sistema de **envio de mensagens no modo consulta** não estava funcionando porque:

1. ✅ A task `enviar_campanha_consultas_task` existia e estava correta
2. ✅ A rota de iniciar envio estava configurada corretamente
3. ❌ **FALTAVA**: Task automática para retomar campanhas pausadas (por horário ou meta diária)

No modo **Fila Cirúrgica**, existe a task `retomar_campanhas_automaticas` que é executada de hora em hora pelo Celery Beat e retoma automaticamente campanhas que foram pausadas por:
- Fora do horário (8h-21h)
- Meta diária atingida

Porém, essa task **só funcionava para fila cirúrgica**, não para consultas.

---

## ✅ Solução Implementada

### 1. **Criada nova task: `retomar_campanhas_consultas_automaticas`**

Arquivo: `tasks.py`

```python
@celery.task(
    base=DatabaseTask,
    name='tasks.retomar_campanhas_consultas_automaticas'
)
def retomar_campanhas_consultas_automaticas():
    """
    Retoma automaticamente campanhas de CONSULTAS pausadas
    Verifica campanhas pausadas por horário ou meta diária e retoma automaticamente
    """
    ...
```

**O que essa task faz:**
- Busca campanhas de consulta com status='pausado'
- Verifica se foram pausadas por horário ou meta diária (não por ação manual do usuário)
- Verifica se ainda tem consultas pendentes (AGUARDANDO_ENVIO)
- Verifica se está no horário correto e se pode enviar hoje
- Se tudo OK, chama `enviar_campanha_consultas_task.delay(campanha.id)` para retomar

### 2. **Adicionada ao Celery Beat Schedule**

Arquivo: `celery_app.py`

```python
'retomar-campanhas-consultas-automaticas': {
    'task': 'tasks.retomar_campanhas_consultas_automaticas',
    'schedule': crontab(minute=0, hour='8-21'),  # De hora em hora, das 8h às 21h
    'options': {'expires': 1800}  # Task expira em 30min se não executar
},
```

**Quando executa:**
- A cada hora cheia (XX:00)
- Entre 8h e 21h
- Todos os dias

---

## 🚀 Como Aplicar a Correção

### **Opção 1: Docker (Recomendado)**

```bash
# 1. Parar os containers
docker-compose down

# 2. Atualizar código
git pull origin claude/busca-ativa-consultations-UTzrg

# 3. Rebuild e restart
docker-compose up -d --build

# 4. Verificar se os containers subiram
docker ps | grep busca-ativa

# 5. Verificar logs do Celery Worker
docker logs busca-ativa-celery-worker --tail 50

# 6. Verificar logs do Celery Beat
docker logs busca-ativa-celery-beat --tail 50
```

### **Opção 2: Sem Docker**

```bash
# 1. Atualizar código
git pull origin claude/busca-ativa-consultations-UTzrg

# 2. Reiniciar Celery Worker
sudo systemctl restart celery-worker

# 3. Reiniciar Celery Beat
sudo systemctl restart celery-beat

# 4. Verificar status
sudo systemctl status celery-worker
sudo systemctl status celery-beat
```

---

## 🧪 Como Testar

### **Teste 1: Envio Manual Imediato**

1. Acesse `/consultas/dashboard`
2. Crie uma nova campanha ou use uma existente com status='pronta'
3. Clique em **"Iniciar Envio"**
4. A campanha deve mudar para status='enviando'
5. As consultas devem ser enviadas (status muda para AGUARDANDO_CONFIRMACAO)

**Verificar logs:**
```bash
# Docker
docker logs -f busca-ativa-celery-worker

# Sem Docker
tail -f /var/log/celery/worker.log
```

Você deve ver:
```
[INFO] Iniciando envio da campanha de consultas X
[INFO] Total de consultas para enviar: Y
[INFO] Mensagem enviada para 5585XXXXXXXX
```

### **Teste 2: Retomada Automática por Horário**

1. Configure uma campanha com `hora_inicio=14` e `hora_fim=18`
2. Inicie o envio às 13h (fora do horário)
3. A campanha deve pausar automaticamente com status='pausado' e msg='Fora do horário'
4. Aguarde até 14h (ou altere manualmente o horário da campanha para simular)
5. **Na próxima hora cheia** (14:00, 15:00, etc), a task automática deve retomar

**Verificar se a task automática está rodando:**
```bash
# Docker
docker logs busca-ativa-celery-beat --tail 100 | grep consulta

# Deve aparecer de hora em hora:
[INFO] Verificando campanhas de CONSULTAS pausadas para retomada automática
[INFO] Retomando campanha consulta X automaticamente
```

### **Teste 3: Retomada Automática por Meta Diária**

1. Configure uma campanha com `meta_diaria=5`
2. Inicie o envio
3. Após enviar 5 consultas, deve pausar com msg='Meta diária atingida'
4. **No dia seguinte**, na primeira hora cheia, a task automática deve retomar

---

## 🔍 Diagnóstico de Problemas

Se ainda não funcionar, use os scripts de diagnóstico:

### **Script 1: Diagnóstico Docker**

```bash
./diagnostico_consultas.sh
```

### **Script 2: Teste de Celery**

```bash
# Dentro do container Docker
docker exec -it busca-ativa-web python3 test_celery_consultas.py

# Sem Docker
python3 test_celery_consultas.py
```

Esse script verifica:
1. ✅ Importação do Celery
2. ✅ Importação das tasks
3. ✅ Registro da task no Celery
4. ✅ Conexão com Redis
5. ✅ Importação dos modelos (CampanhaConsulta, AgendamentoConsulta)
6. ✅ Sintaxe do disparo da task

### **Verificar logs em tempo real:**

```bash
# Terminal 1: Logs do Worker
docker logs -f busca-ativa-celery-worker

# Terminal 2: Logs do Beat
docker logs -f busca-ativa-celery-beat

# Terminal 3: Logs da Web
docker logs -f busca-ativa-web
```

---

## 📊 Verificações Importantes

### **1. Celery Worker está rodando?**

```bash
docker ps | grep celery-worker
# Deve estar com status "Up"
```

### **2. Celery Beat está rodando?**

```bash
docker ps | grep celery-beat
# Deve estar com status "Up"
```

### **3. Redis está respondendo?**

```bash
docker exec busca-ativa-redis redis-cli ping
# Deve retornar: PONG
```

### **4. Task está registrada?**

```bash
docker exec busca-ativa-celery-worker celery -A celery_app.celery inspect registered | grep consulta
# Deve aparecer: tasks.enviar_campanha_consultas_task
# E também: tasks.retomar_campanhas_consultas_automaticas
```

### **5. Verificar tasks ativas (em execução):**

```bash
docker exec busca-ativa-celery-worker celery -A celery_app.celery inspect active
```

### **6. Verificar tasks agendadas (scheduled):**

```bash
docker exec busca-ativa-celery-beat celery -A celery_app.celery inspect scheduled
```

---

## 🎯 Resumo da Correção

| **Antes** | **Depois** |
|-----------|-----------|
| ❌ Envio de consultas iniciava mas pausava e nunca retomava | ✅ Envio pausa e retoma automaticamente de hora em hora |
| ❌ Campanhas pausadas por horário ficavam travadas | ✅ Retomam automaticamente quando entram no horário |
| ❌ Campanhas pausadas por meta diária nunca retomavam | ✅ Retomam automaticamente no dia seguinte |
| ❌ Usuário tinha que clicar "Continuar" manualmente | ✅ Sistema retoma sozinho (como fila cirúrgica) |

---

## 📝 Arquivos Modificados

1. **`tasks.py`** - Adicionada função `retomar_campanhas_consultas_automaticas()`
2. **`celery_app.py`** - Adicionada task ao beat_schedule
3. **`diagnostico_consultas.sh`** (novo) - Script de diagnóstico
4. **`test_celery_consultas.py`** (novo) - Script de teste

---

## 🆘 Se o Problema Persistir

1. **Verifique se a task foi importada corretamente:**
   ```bash
   docker exec -it busca-ativa-web python3 -c "from tasks import enviar_campanha_consultas_task; print('OK')"
   ```

2. **Tente disparar a task manualmente:**
   ```bash
   docker exec -it busca-ativa-web python3 -c "
   from app import app, CampanhaConsulta
   from tasks import enviar_campanha_consultas_task
   with app.app_context():
       camp = CampanhaConsulta.query.first()
       if camp:
           task = enviar_campanha_consultas_task.delay(camp.id)
           print(f'Task disparada: {task.id}')
   "
   ```

3. **Verifique se há erros no worker:**
   ```bash
   docker logs busca-ativa-celery-worker 2>&1 | grep -i error
   ```

4. **Reinicie tudo:**
   ```bash
   docker-compose restart
   ```

---

## ✅ Pronto!

Agora o envio de mensagens no **modo consulta** deve funcionar exatamente como no **modo fila cirúrgica**:
- ✅ Envio manual via botão "Iniciar"
- ✅ Retomada automática de hora em hora (se pausado por horário/meta)
- ✅ Respeita horário de funcionamento (8h-21h)
- ✅ Respeita meta diária

🎉 **Sistema completamente funcional!**
