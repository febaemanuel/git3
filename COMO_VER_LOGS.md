# 🔍 COMO VER LOGS E DIAGNOSTICAR PROBLEMAS

## ⚠️ PROBLEMA: "Não está funcionando"

Se você clicou em "Iniciar Envio" e nada aconteceu, provavelmente:
1. **Redis não está rodando** (broker do Celery)
2. **Celery Worker não está rodando** (processa tasks)
3. **Flask não está rodando** (servidor web)

---

## 📋 PASSO 1: VERIFICAR O QUE ESTÁ RODANDO

Execute no terminal:
```bash
# Verificar processos
ps aux | grep -E "(celery|redis|python.*app.py)" | grep -v grep

# Verificar portas
netstat -tlnp | grep -E "(5001|6379)"
```

**O que você DEVE ver:**
```
redis-server  → Porta 6379 (broker)
celery worker → Processo celery
python app.py → Porta 5001 (Flask)
```

**Se NÃO aparecer nada = ESSE É O PROBLEMA!**

---

## 🚀 PASSO 2: INICIAR TUDO NA ORDEM CORRETA

Abra **3 TERMINAIS SEPARADOS**:

### **Terminal 1 - Redis** (Broker do Celery)
```bash
# Verificar se Redis está instalado
redis-cli ping
# Deve retornar: PONG

# Se não retornar, instalar Redis:
# Ubuntu/Debian:
sudo apt-get install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# Ou rodar Redis manualmente:
redis-server
```

### **Terminal 2 - Celery Worker** (OBRIGATÓRIO para envios)
```bash
cd /home/user/git3

# Iniciar Celery com logs VERBOSE
celery -A celery_app worker --loglevel=info

# DEIXE ESTE TERMINAL ABERTO E VISÍVEL!
# Você verá TODOS os logs de envio aqui
```

**O que você DEVE ver:**
```
celery@hostname ready.
[tasks]
  . tasks.enviar_campanha_consultas_task
  . tasks.enviar_campanha_task
  . tasks.follow_up_automatico_task
```

### **Terminal 3 - Flask** (Servidor Web)
```bash
cd /home/user/git3

# Iniciar Flask com logs
python app.py

# Ou se estiver usando gunicorn:
gunicorn -w 4 -b 0.0.0.0:5001 app:app --log-level=debug
```

---

## 📊 PASSO 3: VER LOGS EM TEMPO REAL

### **Logs do Celery (Terminal 2)**
```bash
# Você já está vendo!
# Quando clicar "Iniciar Envio", verá:

[2025-12-31 00:00:00,000: INFO] Received task: tasks.enviar_campanha_consultas_task[...]
[2025-12-31 00:00:01,000: INFO] Iniciando envio da campanha de consultas 1
[2025-12-31 00:00:01,000: INFO] Total de consultas para enviar: 1
[2025-12-31 00:00:02,000: INFO] Mensagem enviada para 85992231683 da consulta 1
[2025-12-31 00:00:02,000: INFO] Aguardando 15s até próximo envio
[2025-12-31 00:00:17,000: INFO] Envio concluído: 1 enviados, 0 erros
[2025-12-31 00:00:17,000: INFO] Task tasks.enviar_campanha_consultas_task[...] succeeded
```

### **Logs do Flask (Terminal 3)**
```bash
# Você verá requisições HTTP:
127.0.0.1 - - [31/Dec/2025 00:00:00] "POST /consultas/campanha/1/iniciar HTTP/1.1" 302 -
127.0.0.1 - - [31/Dec/2025 00:00:00] "GET /consultas/campanha/1 HTTP/1.1" 200 -
```

### **Logs do Navegador (Console F12)**
```bash
1. Pressione F12 no navegador
2. Vá na aba "Console"
3. Clique em "Iniciar Envio"
4. Veja erros JavaScript (se houver)
```

---

## 🔴 ERROS COMUNS E SOLUÇÕES

### **Erro 1: "Connection refused" no Celery**
```
kombu.exceptions.OperationalError: [Errno 111] Connection refused
```

**Causa:** Redis não está rodando
**Solução:**
```bash
# Iniciar Redis
sudo systemctl start redis

# OU rodar manualmente:
redis-server
```

---

### **Erro 2: "No module named 'celery_app'"**
```
ModuleNotFoundError: No module named 'celery_app'
```

**Causa:** Celery rodando em diretório errado
**Solução:**
```bash
# Verificar diretório
pwd
# Deve ser: /home/user/git3

# Se não for, mudar:
cd /home/user/git3
celery -A celery_app worker --loglevel=info
```

---

### **Erro 3: "WhatsApp não configurado" ou "WhatsApp desconectado"**
```
WhatsApp nao configurado
WhatsApp desconectado
```

**Causa:** Falta configurar Evolution API
**Solução:**
1. Vá em **Configurações** (menu superior)
2. Preencha:
   - Evolution API URL (ex: https://api.evolution.com)
   - Evolution API Key
   - Instance Name
3. Escaneie o QR Code
4. Tente novamente

---

### **Erro 4: Cliquei "Iniciar Envio" mas nada acontece**

**Causa:** Celery worker não está rodando
**Solução:**
```bash
# Terminal separado:
celery -A celery_app worker --loglevel=info

# DEIXE ABERTO e tente novamente na interface
```

---

## ✅ TESTE COMPLETO

Execute estes comandos em ordem:

```bash
# 1. Verificar Redis
redis-cli ping
# Deve retornar: PONG

# 2. Verificar Celery
ps aux | grep celery | grep -v grep
# Deve mostrar processo celery rodando

# 3. Verificar Flask
curl http://localhost:5001
# Deve retornar HTML da página

# 4. Testar conexão Redis via Python
python3 << 'EOF'
from redis import Redis
r = Redis(host='localhost', port=6379)
print(f"Redis OK: {r.ping()}")
EOF
# Deve retornar: Redis OK: True
```

---

## 📝 COMANDOS ÚTEIS

### **Ver logs antigos**
```bash
# Se você configurou logging em arquivo:
tail -f /var/log/celery/worker.log
tail -f /var/log/flask/app.log
```

### **Monitorar Redis**
```bash
# Ver comandos em tempo real
redis-cli monitor

# Ver info do Redis
redis-cli info
```

### **Limpar fila do Celery**
```bash
# Se quiser limpar tasks antigas
celery -A celery_app purge
```

### **Verificar tasks pendentes**
```bash
# Ver quantas tasks estão na fila
celery -A celery_app inspect active
celery -A celery_app inspect scheduled
celery -A celery_app inspect reserved
```

---

## 🎯 RESUMO: O QUE VOCÊ PRECISA FAZER AGORA

1. **Abrir 3 terminais**
2. **Terminal 1:** `redis-server` (ou verificar se já está rodando)
3. **Terminal 2:** `celery -A celery_app worker --loglevel=info` ← **MAIS IMPORTANTE**
4. **Terminal 3:** `python app.py`
5. **Navegador:** Ir na campanha e clicar "Iniciar Envio"
6. **Olhar Terminal 2:** Você verá os logs de envio em tempo real!

---

## 🆘 AINDA NÃO FUNCIONA?

Se seguiu TUDO acima e ainda não funciona:

1. **Copie TODA a saída do Terminal 2 (Celery)**
2. **Copie TODA a saída do Terminal 3 (Flask)**
3. **Tire print do erro no navegador (F12 → Console)**
4. **Me envie isso**

Aí eu consigo te ajudar especificamente!
