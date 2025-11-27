# 🚀 Instruções de Migração do Banco de Dados

## ⚠️ PROBLEMA ATUAL
O código foi atualizado, mas o banco de dados ainda não tem as colunas necessárias:
- `config_whatsapp.usuario_id` - NÃO EXISTE
- `respostas_automaticas.criador_id` - NÃO EXISTE
- `config_global` - TABELA NÃO EXISTE

## ✅ SOLUÇÃO: Executar Migration SQL

### **PASSO 1: Copiar arquivo migration.sql para o VPS**

No seu computador local (onde está o Git):
```bash
scp migration.sql root@srv1148148:~/busca/
```

OU, se estiver no VPS, crie o arquivo manualmente:
```bash
cd ~/busca
nano migration.sql
# Cole o conteúdo do arquivo migration.sql
# Ctrl+X, Y, Enter para salvar
```

### **PASSO 2: Executar migration dentro do container PostgreSQL**

```bash
cd ~/busca

# Copiar migration.sql para dentro do container
docker cp migration.sql busca-ativa-db:/tmp/migration.sql

# Executar a migração
docker exec -it busca-ativa-db psql -U buscaativa -d busca_ativa_db -f /tmp/migration.sql
```

### **PASSO 3: Verificar se funcionou**

```bash
# Verificar se tabela config_global foi criada
docker exec -it busca-ativa-db psql -U buscaativa -d busca_ativa_db -c "\d config_global"

# Verificar se coluna usuario_id foi adicionada
docker exec -it busca-ativa-db psql -U buscaativa -d busca_ativa_db -c "\d config_whatsapp"

# Verificar se colunas FAQ foram adicionadas
docker exec -it busca-ativa-db psql -U buscaativa -d busca_ativa_db -c "\d respostas_automaticas"
```

### **PASSO 4: Reiniciar aplicação**

```bash
docker compose restart busca-ativa-web
docker compose logs -f --tail=50 busca-ativa-web
```

### **PASSO 5: Testar aplicação**

Acesse no navegador e verifique se o erro sumiu.

---

## 🔧 ALTERNATIVA: Executar SQL direto (Comando único)

Se preferir executar tudo de uma vez:

```bash
cd ~/busca

cat > migration.sql << 'EOF'
-- [COLE AQUI TODO O CONTEÚDO DO ARQUIVO migration.sql]
EOF

docker cp migration.sql busca-ativa-db:/tmp/migration.sql
docker exec -it busca-ativa-db psql -U buscaativa -d busca_ativa_db -f /tmp/migration.sql
docker compose restart busca-ativa-web
```

---

## ✅ RESULTADO ESPERADO

Após executar, você deve ver:
```
CREATE TABLE
INSERT 0 1
ALTER TABLE
ALTER TABLE
CREATE TABLE
CREATE INDEX
...
MIGRAÇÃO CONCLUÍDA
```

E a aplicação deve funcionar sem erros!
