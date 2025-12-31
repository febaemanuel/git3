# Como Ver Logs e Aplicar Migrations

Este documento explica como diagnosticar erros no sistema e aplicar migrations do banco de dados.

---

## 📋 Problema: Internal Server Error no Dashboard

Se você está recebendo **Internal Server Error** ao acessar `/consultas/dashboard`, provavelmente as tabelas do modo consulta não foram criadas no banco de dados.

---

## 🔍 Como Ver os Logs

### 1. **Logs da Aplicação Flask**

O sistema grava logs em `busca_ativa.log` no diretório da aplicação:

```bash
# Ver últimas 100 linhas do log
tail -100 busca_ativa.log

# Acompanhar o log em tempo real
tail -f busca_ativa.log

# Buscar por erros
grep -i "error\|exception" busca_ativa.log | tail -50
```

### 2. **Logs do Servidor Web (Gunicorn/uWSGI)**

Se estiver rodando com Gunicorn:

```bash
# Logs do systemd (se configurado como serviço)
sudo journalctl -u busca-ativa -n 100 -f

# Logs do Gunicorn (geralmente em /var/log/)
sudo tail -f /var/log/gunicorn/error.log
sudo tail -f /var/log/gunicorn/access.log
```

### 3. **Logs do PostgreSQL**

```bash
# Ubuntu/Debian
sudo tail -f /var/log/postgresql/postgresql-*.log

# Logs do Docker (se usando Docker)
docker logs nome-do-container-postgres
```

### 4. **Verificar Status do Serviço**

```bash
# Status do serviço
sudo systemctl status busca-ativa

# Verificar processos Python rodando
ps aux | grep python
```

---

## 🗄️ Verificar e Aplicar Migrations

### **Método 1: Script Python Automático (RECOMENDADO)**

Use o script `migrate_modo_consulta.py` para verificar e aplicar automaticamente:

```bash
# 1. Verificar se as tabelas existem
python migrate_modo_consulta.py --check

# 2. Se houver migrations pendentes, aplicar:
python migrate_modo_consulta.py --apply
```

### **Método 2: SQL Direto no PostgreSQL**

Se preferir executar manualmente:

```bash
# 1. Conectar ao PostgreSQL
psql -U postgres -d busca_ativa

# Ou se estiver usando variável de ambiente:
psql $DATABASE_URL

# 2. Verificar se as tabelas existem
\dt campanhas_consultas

# 3. Se não existir, executar a migration:
\i migration_modo_consulta.sql

# 4. Aplicar correções (se necessário):
\i migration_modo_consulta_fix.sql

# 5. Verificar criação
\dt *consultas*
```

### **Método 3: Usando setup.py**

Recriar todas as tabelas (CUIDADO: apenas em desenvolvimento!):

```bash
# APENAS DESENVOLVIMENTO - NÃO USE EM PRODUÇÃO!
python setup.py --init-db
```

---

## ✅ Verificar se o Problema Foi Resolvido

Após aplicar as migrations, verifique:

### 1. **Verificar Tabelas no Banco**

```bash
psql $DATABASE_URL -c "\dt *consultas*"
```

Deve listar:
- `campanhas_consultas`
- `agendamentos_consultas`
- `telefones_consultas`
- `logs_msgs_consultas`

### 2. **Testar o Dashboard**

Acesse no navegador:
```
https://chsistemas.cloud/consultas/dashboard
```

Deve carregar sem erro (pode aparecer vazio se não houver campanhas).

### 3. **Verificar Logs**

```bash
# Ver se há erros após a correção
tail -50 busca_ativa.log
```

---

## 🐛 Diagnóstico de Outros Erros Comuns

### Erro: "relation 'campanhas_consultas' does not exist"
**Causa:** Tabelas do modo consulta não foram criadas
**Solução:** Executar `python3 migrate_modo_consulta.py --apply`

### Erro: "column 'tipo_sistema' does not exist"
**Causa:** Campo tipo_sistema não foi adicionado em usuarios
**Solução:** Executar `python3 migrate_modo_consulta.py --apply`

### Erro: "column 'celery_task_id' does not exist"
**Causa:** Coluna celery_task_id faltando em campanhas_consultas
**Solução:** Executar `python3 fix_celery_task_id.py`

### Erro: "column 'posicao' does not exist" (ou outras colunas)
**Causa:** Colunas faltando em agendamentos_consultas
**Solução:** Executar `python3 fix_agendamentos_consultas_schema.py`

### Erro: "could not connect to server"
**Causa:** Banco de dados PostgreSQL offline
**Solução:**
```bash
sudo systemctl status postgresql
sudo systemctl start postgresql
```

### Erro: "relation 'usuarios' does not exist"
**Causa:** Banco de dados vazio, nunca foi inicializado
**Solução:**
```bash
python setup.py --init-db
python migrate_modo_consulta.py --apply
```

---

## 📊 Monitoramento em Produção

### **Logs em Tempo Real**

```bash
# Terminal 1: Logs da aplicação
tail -f busca_ativa.log

# Terminal 2: Logs do servidor web
sudo journalctl -u busca-ativa -f

# Terminal 3: Top dos processos
htop
```

### **Verificar Conexões com o Banco**

```bash
# Conectar ao PostgreSQL e ver conexões ativas
psql $DATABASE_URL -c "SELECT pid, usename, application_name, client_addr, state FROM pg_stat_activity WHERE datname = 'busca_ativa';"
```

---

## 🔧 Comandos Úteis

```bash
# Reiniciar aplicação (se configurado como serviço)
sudo systemctl restart busca-ativa

# Ver variáveis de ambiente
env | grep DATABASE

# Testar conexão com o banco
python -c "from app import app, db; from sqlalchemy import text; app.app_context().push(); print(db.engine.execute(text('SELECT version()')).scalar())"

# Backup do banco antes de migrations
pg_dump $DATABASE_URL > backup_antes_migration_$(date +%Y%m%d_%H%M%S).sql
```

---

## 📞 Suporte

Se o problema persistir:

1. **Copie os últimos erros do log:**
   ```bash
   tail -100 busca_ativa.log > erro.txt
   ```

2. **Verifique as tabelas:**
   ```bash
   psql $DATABASE_URL -c "\dt" > tabelas.txt
   ```

3. **Envie os arquivos erro.txt e tabelas.txt para análise**

---

## ✨ Resumo Rápido

### **Para Instalações em Docker (Recomendado)**

```bash
# 1. Atualizar código
cd ~/busca
git pull origin claude/fix-dashboard-server-error-J4664

# 2. Rebuild e restart
docker-compose down
docker-compose up -d --build

# 3. Aplicar TODOS os fixes (dentro do container)
docker exec -it busca-ativa-web python3 fix_celery_task_id.py
docker exec -it busca-ativa-web python3 fix_agendamentos_consultas_schema.py

# 4. Reiniciar
docker restart busca-ativa-web

# 5. Verificar logs
docker logs -f busca-ativa-web
```

### **Para Instalações Tradicionais (sem Docker)**

```bash
# 1. Ver o erro
tail -50 busca_ativa.log

# 2. Verificar migrations
python3 migrate_modo_consulta.py --check

# 3. Aplicar se necessário
python3 migrate_modo_consulta.py --apply

# 4. Aplicar fixes adicionais
python3 fix_celery_task_id.py
python3 fix_agendamentos_consultas_schema.py

# 5. Reiniciar a aplicação
sudo systemctl restart busca-ativa

# 6. Testar
curl -I https://chsistemas.cloud/consultas/dashboard
```

**Pronto! 🎉**
