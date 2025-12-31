# ✅ CHECKLIST DE TESTES - SISTEMA DE CONSULTAS

## 📋 PRÉ-REQUISITOS

### 1. Aplicar Migrações do Banco
```bash
# Adicionar campo status_msg se não existir
docker exec -i busca-ativa-db psql -U busca -d busca < migrate_consultas.sql

# Corrigir números de telefone (adicionar código 55)
docker exec -i busca-ativa-db psql -U busca -d busca < fix_telefone_consultas.sql
```

### 2. Rebuild e Restart
```bash
cd /root/busca
docker-compose down
docker-compose up -d --build
```

### 3. Verificar Logs
```bash
# Web
docker logs busca-ativa-web --tail 50

# Celery Worker
docker logs busca-ativa-celery-worker --tail 50
```

---

## 🧪 TESTES FUNCIONAIS

### TESTE 1: Login e Navegação ✅
- [ ] Login com usuário de consultas
- [ ] Clique em "Busca Ativa - HUWC" → Deve ir para `/consultas/dashboard`
- [ ] Verificar se menu está correto

### TESTE 2: Importar Planilha ✅
- [ ] Clique em "Importar Planilha"
- [ ] Upload de arquivo Excel
- [ ] Verificar se consultas foram importadas
- [ ] Verificar contadores (Total, Enviados, etc.)

### TESTE 3: Iniciar Envio ✅
- [ ] Clique em "Iniciar Envio"
- [ ] Verificar se status muda para "enviando"
- [ ] Verificar logs do Celery:
  ```bash
  docker logs busca-ativa-celery-worker -f
  ```
- [ ] Mensagens devem ser enviadas com código 55: `5585XXXXXXXXX`
- [ ] Verificar se contadores aumentam

### TESTE 4: Chat e Histórico 💬
- [ ] Clique no ícone 💬 (chat) ao lado de uma consulta
- [ ] Modal deve abrir com histórico
- [ ] Verificar mensagens enviadas e recebidas
- [ ] Digite uma mensagem e clique "Enviar"
- [ ] Verificar se mensagem foi enviada
- [ ] Histórico deve atualizar

### TESTE 5: Ações Manuais ⚡
- [ ] Clique em ✓ (confirmar) em consulta aguardando confirmação
- [ ] Status deve mudar para "CONFIRMADO"
- [ ] Clique em ✗ (cancelar)
- [ ] Digite motivo do cancelamento
- [ ] Status deve mudar para "REJEITADO"

### TESTE 6: Detalhes da Consulta 📄
- [ ] Clique no ícone ℹ️ (info)
- [ ] Página de detalhes deve abrir
- [ ] Verificar todos os dados da consulta

### TESTE 7: Webhook (Resposta do Paciente) 📲
- [ ] Envie "SIM" do WhatsApp do paciente
- [ ] Status deve mudar para "AGUARDANDO_COMPROVANTE"
- [ ] Envie "NÃO"
- [ ] Sistema deve pedir motivo
- [ ] Digite motivo
- [ ] Status deve mudar para "REJEITADO"

### TESTE 8: Pausar e Continuar ⏯️
- [ ] Durante envio, clique em "Pausar"
- [ ] Status deve mudar para "pausado"
- [ ] Clique em "Continuar"
- [ ] Envios devem retomar

---

## 🔍 VERIFICAÇÕES TÉCNICAS

### Banco de Dados
```sql
-- Verificar se status_msg existe
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name='campanhas_consultas' AND column_name='status_msg';

-- Verificar números com código 55
SELECT COUNT(*) as total,
       SUM(CASE WHEN numero LIKE '55%' THEN 1 ELSE 0 END) as com_55
FROM telefones_consultas;

-- Verificar logs de mensagens
SELECT direcao, status, COUNT(*)
FROM logs_msgs_consultas
GROUP BY direcao, status;
```

### Endpoints (API)
```bash
# Teste de detalhes (substitua ID)
curl -X GET http://localhost:5000/api/consulta/1/detalhes \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json"

# Teste de enviar mensagem (substitua ID)
curl -X POST http://localhost:5000/api/consulta/1/enviar_mensagem \
  -H "Cookie: session=..." \
  -H "Content-Type: application/json" \
  -d '{"mensagem": "Teste de mensagem manual"}'
```

---

## ⚠️ PROBLEMAS CONHECIDOS E SOLUÇÕES

### Problema: "get_dashboard_route is undefined"
**Solução:** Context processor já foi adicionado em `app.py:2021-2024`

### Problema: Números sem código 55
**Solução:** Rode `fix_telefone_consultas.sql` no banco

### Problema: Erro "data_criacao does not exist"
**Solução:** JÁ CORRIGIDO! Agora usa `log.data` ao invés de `log.data_criacao`

### Problema: WhatsApp desconectado
**Solução:**
1. Vá em Configurações → WhatsApp
2. Conecte o WhatsApp
3. Escaneie o QR Code

---

## 📊 MÉTRICAS DE SUCESSO

Após todos os testes, você deve ter:
- ✅ Campanhas criadas com sucesso
- ✅ Mensagens enviadas (total_enviados > 0)
- ✅ Alguns confirmados ou rejeitados
- ✅ Logs de mensagens registrados
- ✅ Chat funcionando perfeitamente
- ✅ Ações manuais operacionais

---

## 🆘 COMANDOS ÚTEIS DE DEBUG

```bash
# Ver erros do web
docker logs busca-ativa-web --tail 100 | grep ERROR

# Ver erros do celery
docker logs busca-ativa-celery-worker --tail 100 | grep ERROR

# Conectar no banco
docker exec -it busca-ativa-db psql -U busca -d busca

# Ver tasks do Celery
docker exec -it busca-ativa-celery-worker celery -A tasks inspect active

# Restart só do web (sem rebuild)
docker restart busca-ativa-web

# Ver uso de memória
docker stats --no-stream
```

---

## ✅ CHECKLIST FINAL

- [ ] Todas as migrações aplicadas
- [ ] Sistema reiniciado com sucesso
- [ ] Logs sem erros críticos
- [ ] WhatsApp conectado
- [ ] Teste 1-8 passaram
- [ ] Métricas de sucesso atingidas

**SE TUDO PASSOU: SISTEMA 100% FUNCIONAL! 🎉**

**SE ALGO FALHOU:** Verifique os logs e a seção "Problemas Conhecidos"
