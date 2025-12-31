# 🧪 GUIA DE TESTE - MODO CONSULTA

## ⚠️ IMPORTANTE: Execute a Correção Primeiro

No servidor, execute:

```bash
cd ~/busca
docker exec -i busca-ativa-db psql -U buscaativa -d buscaativa_db < migration_modo_consulta_fix.sql
```

**Resultado esperado:**
```
ALTER TABLE
COMMENT
ALTER TABLE
UPDATE 1
              status
----------------------------------
 Correção aplicada com sucesso!
(1 row)

 total_usuarios | tipo_sistema
----------------+---------------
              1 | BUSCA_ATIVA
(1 row)
```

---

## 📝 PASSO A PASSO PARA TESTAR

### 1. Acessar o Sistema

```
URL: http://SEU_SERVIDOR:5000
Login: admin@huwc.com
Senha: admin123
```

### 2. Configurar Usuário para Modo Consulta

**Opção A: Via SQL (mais rápido)**
```bash
docker exec -it busca-ativa-db psql -U buscaativa -d buscaativa_db -c "UPDATE usuarios SET tipo_sistema = 'AGENDAMENTO_CONSULTA' WHERE email = 'admin@huwc.com';"
```

**Opção B: Via Interface (se houver tela de edição de usuário)**
1. Configurações → Usuários
2. Editar usuário admin
3. Tipo de Sistema: `AGENDAMENTO_CONSULTA`
4. Salvar

### 3. Fazer Logout e Login Novamente

- Clicar em "Sair" no menu superior direito
- Fazer login novamente
- **O menu agora deve mostrar "Consultas" em vez de "Dashboard"**

---

## 📊 CRIAR PLANILHA DE TESTE

Crie um arquivo Excel (.xlsx) com estas colunas:

### Exemplo 1: RETORNO (paciente vai confirmar)

| PACIENTE | TIPO | TELEFONE CADASTRO | DATA AGHU | MEDICO_SOLICITANTE | ESPECIALIDADE |
|----------|------|-------------------|-----------|-------------------|---------------|
| João Silva | RETORNO | 5585988887777 | 15/02/2025 | Dr. Carlos Santos | CARDIOLOGIA |

### Exemplo 2: INTERCONSULTA (paciente vai rejeitar e voltar ao posto)

| PACIENTE | TIPO | TELEFONE CADASTRO | DATA AGHU | MEDICO_SOLICITANTE | ESPECIALIDADE | PACIENTE_VOLTAR_POSTO_SMS |
|----------|------|-------------------|-----------|-------------------|---------------|---------------------------|
| Maria Oliveira | INTERCONSULTA | 5585977776666 | 20/02/2025 | Dra. Ana Paula | ORTOPEDIA | SIM |

**⚠️ IMPORTANTE:**
- Use seu próprio número de WhatsApp para testar!
- Formato do telefone: DDI + DDD + Número (exemplo: 5585988887777)
- Não coloque espaços, hífens ou parênteses

---

## 🚀 TESTE 1: RETORNO - Paciente Confirma

### Passo 1: Importar Planilha
1. Clicar em **"Importar Planilha"**
2. Preencher:
   - Nome: "Teste RETORNO - Confirmação"
   - Meta Diária: 10
   - Hora Início: 8
   - Hora Fim: 23
   - Tempo entre envios: 5 segundos
3. Upload do Excel
4. Clicar "Importar"

**Resultado esperado:**
- ✅ "Campanha criada com sucesso! 1 consultas importadas."
- ✅ Redirecionado para detalhes da campanha

### Passo 2: Iniciar Envio
1. Clicar em **"Iniciar Envio"**
2. Aguardar 5-10 segundos

**Resultado esperado:**
- ✅ Você recebe no WhatsApp:
```
Bom dia!
Falamos do HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO.
Estamos informando que a CONSULTA do paciente João Silva, foi MARCADA para o dia 15/02/2025, com Dr. Carlos Santos, com especialidade em CARDIOLOGIA.

Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?
```

### Passo 3: Responder "SIM"
1. No WhatsApp, responder: **SIM**
2. Atualizar a página da campanha (F5)

**Resultado esperado:**
- ✅ Recebe: "✅ Consulta confirmada! Aguarde o envio do comprovante."
- ✅ Status na tela: **AGUARDANDO COMPROVANTE** (badge amarelo)

### Passo 4: Enviar Comprovante
1. Clicar no "👁️" da consulta
2. Ver detalhes
3. Fazer upload de um PDF ou JPG qualquer
4. Clicar **"Enviar Comprovante para Paciente"**

**Resultado esperado:**
- ✅ Recebe no WhatsApp:
  - Mensagem longa com instruções
  - Arquivo PDF/JPG anexado
- ✅ Status na tela: **CONFIRMADO** ✅ (badge verde)

---

## 🚀 TESTE 2: INTERCONSULTA - Paciente Rejeita

### Passo 1: Importar Planilha
1. Clicar em "Importar Planilha"
2. Nome: "Teste INTERCONSULTA - Rejeição"
3. Upload do Excel (INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = SIM)
4. Importar

### Passo 2: Iniciar Envio
1. Clicar "Iniciar Envio"
2. Aguardar mensagem no WhatsApp

**Resultado esperado:**
- ✅ Recebe MSG 1 (confirmação inicial)

### Passo 3: Responder "NÃO"
1. No WhatsApp, responder: **NÃO**

**Resultado esperado:**
- ✅ Recebe imediatamente: **"Qual o motivo?"**
- ✅ Status na tela: **AGUARDANDO MOTIVO REJEIÇÃO**

### Passo 4: Responder Motivo
1. No WhatsApp, responder: **"Não posso ir porque trabalho nesse dia"**

**Resultado esperado:**
- ✅ Recebe automaticamente MSG 3B:
```
HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com Maria Oliveira? Sua consulta para o serviço de ORTOPEDIA foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!
```
- ✅ Status na tela: **REJEITADO** ❌ (badge vermelho)
- ✅ Motivo aparece na tela: "Não posso ir porque trabalho nesse dia"

---

## 🚀 TESTE 3: RETORNO - Paciente Rejeita (SEM MSG 3B)

### Repetir Teste 2, mas com planilha RETORNO

**Diferença esperada:**
- ✅ Recebe "Qual o motivo?" após responder NÃO
- ✅ Responde o motivo
- ✅ Status: REJEITADO
- ❌ **NÃO recebe MSG 3B** (porque é RETORNO, não INTERCONSULTA)

---

## 🔍 VERIFICAÇÕES IMPORTANTES

### 1. Menu Dinâmico
- ✅ Com `tipo_sistema = AGENDAMENTO_CONSULTA`: Menu mostra "Consultas"
- ✅ Com `tipo_sistema = BUSCA_ATIVA`: Menu mostra "Dashboard", "Relatórios", etc.

### 2. Estatísticas em Tempo Real
- ✅ Dashboard atualiza contadores automaticamente
- ✅ Total, Enviados, Confirmados, Rejeitados

### 3. Logs de Mensagens
- ✅ Todas as mensagens enviadas/recebidas são registradas
- ✅ Ver logs em detalhes da campanha (se implementado)

### 4. Celery Funcionando
```bash
# Ver logs do Celery
docker logs -f busca-ativa-celery-worker

# Deve mostrar:
# [INFO/MainProcess] Task tasks.enviar_campanha_consultas_task...
# [INFO/MainProcess] Iniciando envio da campanha de consultas...
```

---

## 🐛 TROUBLESHOOTING

### Problema: Menu não mudou após configurar usuário
**Solução:** Fazer logout e login novamente

### Problema: Não recebe mensagens no WhatsApp
**Verificar:**
1. WhatsApp está conectado? (Configurações → WhatsApp)
2. Número está correto? (DDI + DDD + Número)
3. Celery está rodando? `docker ps | grep celery`

### Problema: Erro ao importar planilha
**Verificar:**
1. Arquivo é .xlsx ou .xls?
2. Tem as colunas obrigatórias? (PACIENTE, TIPO, etc.)
3. TIPO é "RETORNO" ou "INTERCONSULTA"? (maiúsculas)

### Problema: Status não atualiza
**Solução:** Atualizar página (F5) ou verificar logs:
```bash
docker logs busca-ativa-web | grep "Webhook Consulta"
```

---

## ✅ CHECKLIST DE SUCESSO

- [ ] Migration executada sem erros
- [ ] Usuário configurado com AGENDAMENTO_CONSULTA
- [ ] Menu mostra "Consultas" após login
- [ ] Importação de planilha funciona
- [ ] MSG 1 é recebida no WhatsApp
- [ ] Resposta "SIM" → Status: AGUARDANDO_COMPROVANTE
- [ ] Upload de comprovante funciona
- [ ] MSG 2 é recebida com arquivo anexo
- [ ] Resposta "NÃO" → MSG 3A "Qual o motivo?"
- [ ] Motivo é armazenado
- [ ] MSG 3B é enviada para INTERCONSULTA com voltar posto = SIM
- [ ] MSG 3B NÃO é enviada para RETORNO

---

## 📞 Se Algo Der Errado

### Ver logs em tempo real:
```bash
# Aplicação
docker logs -f busca-ativa-web

# Celery
docker logs -f busca-ativa-celery-worker

# Banco de dados
docker exec -it busca-ativa-db psql -U buscaativa -d buscaativa_db
```

### Resetar tudo:
```bash
# Apenas se quiser recomeçar
docker-compose down -v
docker-compose up -d --build
# Executar migrations novamente
```

---

## 🎉 TUDO FUNCIONANDO?

**Parabéns!** O sistema de Agendamento de Consultas está operacional!

Agora você pode:
- ✅ Importar planilhas reais de pacientes
- ✅ Enviar mensagens automaticamente
- ✅ Acompanhar confirmações/rejeições
- ✅ Enviar comprovantes para quem confirmou
- ✅ Sistema trata rejeições automaticamente

**Boa sorte! 🚀**
