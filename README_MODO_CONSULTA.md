# 📋 MODO CONSULTA - Sistema de Agendamento de Consultas

## ✅ Implementação Concluída

O sistema de **Agendamento de Consultas** foi implementado com sucesso! Este sistema funciona **paralelamente** à Fila Cirúrgica (BUSCA_ATIVA), sem alterar nada do sistema existente.

---

## 🚀 Como Usar

### 1. Executar Migration no Banco de Dados

**IMPORTANTE:** Execute a migration SQL antes de rodar o sistema:

```bash
# Se estiver usando Docker
docker exec -i busca-ativa-db psql -U buscaativa -d buscaativa_db < migration_modo_consulta.sql

# Ou se tiver PostgreSQL local
psql -U postgres -d buscaativa_db -f migration_modo_consulta.sql
```

### 2. Configurar Usuário para Modo Consulta

1. Faça login como administrador no sistema
2. Vá em **Configurações** > **Usuários**
3. Edite o usuário desejado
4. No campo **Tipo de Sistema**, selecione: `AGENDAMENTO_CONSULTA`
5. Salve as alterações

**Nota:** Usuários com `BUSCA_ATIVA` continuam vendo o sistema de Fila Cirúrgica normalmente.

### 3. Importar Planilha de Consultas

1. Acesse o dashboard (já deve mostrar "Agendamento de Consultas")
2. Clique em **Importar Planilha**
3. Preencha:
   - Nome da campanha
   - Descrição (opcional)
   - Configurações de envio (meta diária, horário, intervalo)
4. Faça upload do arquivo Excel (.xlsx ou .xls)

### 4. Iniciar Envio Automático

1. Acesse a campanha criada
2. Clique em **Iniciar Envio**
3. O sistema enviará a **MSG 1** (confirmação inicial) automaticamente
4. Aguarde as respostas dos pacientes

---

## 📊 Estrutura da Planilha

### Colunas Obrigatórias:

```
PACIENTE                    - Nome do paciente
TIPO                        - RETORNO ou INTERCONSULTA
TELEFONE CADASTRO           - Telefone 1
TELEFONE REGISTRO           - Telefone 2 (opcional)
DATA AGHU                   - Data da consulta
MEDICO_SOLICITANTE          - Nome do médico
ESPECIALIDADE               - Especialidade médica
```

### Colunas Opcionais:

```
POSICAO
COD MASTER
CODIGO AGHU
DATA DO REGISTRO
PROCEDÊNCIA
OBSERVAÇÕES
EXAMES
SUB-ESPECIALIDADE
GRADE_AGHU
PRIORIDADE
INDICACAO DATA
DATA REQUISIÇÃO
DATA EXATA OU DIAS
ESTIMATIVA AGENDAMENTO
PACIENTE_VOLTAR_POSTO_SMS   - SIM ou NÃO (apenas para INTERCONSULTA)
```

---

## 🔄 Fluxo de Mensagens

### MSG 1 - Confirmação Inicial (AUTOMÁTICA via Celery)

```
Bom dia!
Falamos do HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO.
Estamos informando que a CONSULTA do paciente {PACIENTE}, foi MARCADA para o dia {DATA_AGHU}, com {MEDICO_SOLICITANTE}, com especialidade em {ESPECIALIDADE}.

Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?
```

**Status:** `AGUARDANDO_ENVIO` → `AGUARDANDO_CONFIRMACAO`

---

### Resposta do Paciente

#### Opção 1: Paciente Confirma (SIM / OK / CONFIRMO)
- Status muda: `AGUARDANDO_CONFIRMACAO` → `AGUARDANDO_COMPROVANTE`
- Sistema aguarda usuário enviar comprovante manualmente

#### Opção 2: Paciente Rejeita (NÃO / CANCELO)
- Sistema pergunta: **"Qual o motivo?"** (MSG 3A)
- Status muda: `AGUARDANDO_CONFIRMACAO` → `AGUARDANDO_MOTIVO_REJEICAO`
- Aguarda resposta do paciente
- Armazena motivo no campo `motivo_rejeicao`
- Status muda: `AGUARDANDO_MOTIVO_REJEICAO` → `REJEITADO`
- **SE INTERCONSULTA E `PACIENTE_VOLTAR_POSTO_SMS` = SIM:**
  - Envia MSG 3B (voltar ao posto)

---

### MSG 2 - Envio de Comprovante (MANUAL)

1. Usuário acessa detalhes da consulta
2. Faz upload do comprovante (PDF/JPG/PNG)
3. Clica **"Enviar Comprovante para Paciente"**
4. Sistema envia mensagem + arquivo

```
O Hospital Walter Cantídio agradece seu contato. CONSULTA CONFIRMADA!

Responda a pesquisa de satisfação: https://forms.gle/feteZxSNBRd5xfDUA

O hospital entra em contato através do: (85) 992081534 / (85)996700783 / (85)991565903 / (85) 992614237 / (85) 992726080. É importante que atenda as ligações e responda as mensagens desses números. Por tanto, salve-os!

Confira seu comprovante: data, horário e nome do(a) médico(a).

Não fazemos marcação de exames, apenas consultas.

Caso falte, procurar o ambulatório para ser colocado novamente no pré-agendamento.

Você sabia que pode verificar sua consulta no app HU Digital? https://play.google.com/store/apps/details?id=br.gov.ebserh.hudigital&pcampaignid=web_share . Após 5 horas dessa mensagem, verifique sua consulta agendada no app.

Reagendamentos estarão presentes no app HU Digital. Verifique sempre o app HU Digital.
```

**Status:** `AGUARDANDO_COMPROVANTE` → `CONFIRMADO`

---

### MSG 3A - Perguntar Motivo (AUTOMÁTICA)

```
Qual o motivo?
```

**Status:** `AGUARDANDO_CONFIRMACAO` → `AGUARDANDO_MOTIVO_REJEICAO`

---

### MSG 3B - Voltar ao Posto (AUTOMÁTICA)

**Enviada apenas para:** INTERCONSULTA com `PACIENTE_VOLTAR_POSTO_SMS` = SIM

```
HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com {PACIENTE}? Sua consulta para o serviço de {ESPECIALIDADE} foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!
```

**Status:** `AGUARDANDO_MOTIVO_REJEICAO` → `REJEITADO`

---

## 📂 Arquivos Criados/Modificados

### Novos Arquivos:
- `migration_modo_consulta.sql` - Migration do banco de dados
- `consultas_routes.py` - Rotas Flask do modo consulta
- `templates/consultas_dashboard.html` - Dashboard de consultas
- `templates/campanha_consultas_detalhe.html` - Detalhes da campanha
- `templates/consulta_detalhe.html` - Detalhes individual com upload
- `templates/consultas_importar.html` - Formulário de importação
- `README_MODO_CONSULTA.md` - Este arquivo

### Arquivos Modificados:
- `app.py` - Adicionado:
  - Campo `tipo_sistema` no modelo `Usuario`
  - Modelos: `CampanhaConsulta`, `AgendamentoConsulta`, `TelefoneConsulta`, `LogMsgConsulta`
  - Funções de formatação de mensagens
  - Processamento de respostas no webhook
  - Importação das rotas de consultas

- `tasks.py` - Adicionado:
  - Task `enviar_campanha_consultas_task()` para envio automático

---

## 🗄️ Banco de Dados

### Novas Tabelas:

1. **campanhas_consultas** - Campanhas de agendamento
2. **agendamentos_consultas** - Consultas individuais (com todos os dados da planilha)
3. **telefones_consultas** - Telefones de cada consulta
4. **logs_msgs_consultas** - Log de mensagens enviadas/recebidas

### Campo Adicionado:

- **usuarios.tipo_sistema** - Define se usuário usa `BUSCA_ATIVA` ou `AGENDAMENTO_CONSULTA`

---

## ✅ Checklist de Teste

### Teste RETORNO (paciente confirma):
- [x] Importar planilha RETORNO
- [x] Iniciar envio
- [x] Paciente responde "SIM"
- [x] Status muda para AGUARDANDO_COMPROVANTE
- [x] Enviar comprovante manualmente
- [x] Status muda para CONFIRMADO

### Teste INTERCONSULTA (paciente rejeita com voltar ao posto):
- [x] Importar planilha INTERCONSULTA com `PACIENTE_VOLTAR_POSTO_SMS` = SIM
- [x] Iniciar envio
- [x] Paciente responde "NÃO"
- [x] Sistema pergunta "Qual o motivo?"
- [x] Paciente responde motivo
- [x] Sistema armazena motivo
- [x] Sistema envia MSG 3B (voltar ao posto)
- [x] Status muda para REJEITADO

### Teste RETORNO (paciente rejeita simples):
- [x] Importar planilha RETORNO
- [x] Paciente responde "NÃO"
- [x] Sistema pergunta motivo
- [x] Paciente responde motivo
- [x] Status muda para REJEITADO
- [x] NÃO envia MSG 3B (porque é RETORNO)

---

## 🔧 Manutenção

### Ver Logs:

```bash
# Logs do aplicativo
tail -f busca_ativa.log

# Logs do Celery
docker logs -f busca-ativa-celery-worker
```

### Pausar/Retomar Campanha:

- **Pausar:** Clique em "Pausar" na campanha
- **Retomar:** Clique em "Iniciar Envio" novamente

### Verificar Status:

- Dashboard mostra estatísticas em tempo real
- Clique em "Ver" na campanha para ver detalhes

---

## ⚠️ Importante

1. ✅ **Fila Cirúrgica NÃO foi alterada** - Continua funcionando normalmente
2. ✅ **Usuários são independentes** - Cada um vê apenas seu sistema
3. ✅ **Webhook trata ambos** - Respostas são processadas corretamente
4. ✅ **Celery processa ambos** - Tasks separadas para cada sistema

---

## 📞 Suporte

Para dúvidas ou problemas:
1. Verifique os logs
2. Confirme que a migration foi executada
3. Verifique se o usuário tem `tipo_sistema = AGENDAMENTO_CONSULTA`
4. Certifique-se que o Celery está rodando

---

## 🎯 Resumo Rápido

```
1. Executar migration SQL ✅
2. Configurar usuário (tipo_sistema = AGENDAMENTO_CONSULTA) ✅
3. Importar planilha Excel ✅
4. Iniciar envio (automático) ✅
5. Aguardar respostas (webhook processa) ✅
6. Enviar comprovante manualmente para quem confirmou ✅
7. Sistema trata rejeições automaticamente ✅
```

**Pronto! O sistema está funcionando! 🚀**
