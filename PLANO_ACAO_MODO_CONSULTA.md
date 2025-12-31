# 📋 PLANO DE AÇÃO - IMPLEMENTAÇÃO DO MODO CONSULTA

## ⚠️ AGUARDANDO APROVAÇÃO - NÃO IMPLEMENTAR SEM AUTORIZAÇÃO

---

## 📌 ENTENDIMENTO DO REQUISITO

### O QUE O USUÁRIO QUER:

1. **Sistema atual:** Fila Cirúrgica (BUSCA_ATIVA) ✅ Funcional
2. **Sistema novo:** Agendamento de Consultas (AGENDAMENTO_CONSULTA)
3. **Requisito:** NÃO alterar a estrutura da fila cirúrgica
4. **Solução:** No cadastro, usuário escolhe qual sistema usar

### TIPOS DE CONSULTA:

1. **RETORNO** - Paciente já foi atendido, volta para nova consulta
2. **INTERCONSULTA** - Paciente encaminhado de outra especialidade
   - Tem coluna adicional: `PACIENTE_VOLTAR_POSTO_SMS` (SIM ou NÃO)

---

## 🔄 FLUXO CORRETO DAS MENSAGENS

### MENSAGEM 1: Confirmação Inicial (AUTOMÁTICA via Celery)

**Enviada para:** TODOS (RETORNO e INTERCONSULTA)
**Quando:** Logo após importar planilha e iniciar envio
**Status:** AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO

```
Bom dia!
Falamos do HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO.
Estamos informando que a CONSULTA do paciente {PACIENTE}, foi MARCADA para o dia {DATA_AGHU}, com {MEDICO_SOLICITANTE}, com especialidade em {ESPECIALIDADE}.

Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?
```

**Variáveis:**
- `{PACIENTE}` - Nome do paciente (coluna PACIENTE)
- `{DATA_AGHU}` - Data da consulta (coluna DATA AGHU)
- `{MEDICO_SOLICITANTE}` - Médico (coluna MEDICO_SOLICITANTE)
- `{ESPECIALIDADE}` - Especialidade (coluna ESPECIALIDADE)

---

### RESPOSTA DO PACIENTE (via WhatsApp - processada pelo Webhook)

**Opção 1: Paciente confirma (SIM / OK / CONFIRMO)**
- Status muda: AGUARDANDO_CONFIRMACAO → AGUARDANDO_COMPROVANTE
- Sistema aguarda usuário enviar comprovante

**Opção 2: Paciente rejeita (NÃO / CANCELO)**
- Status muda: AGUARDANDO_CONFIRMACAO → REJEITADO
- **SE INTERCONSULTA E PACIENTE_VOLTAR_POSTO_SMS = SIM:**
  - Enviar MENSAGEM 3 (volta ao posto)
- **SENÃO:**
  - Apenas cancelar

---

### MENSAGEM 2: Envio de Comprovante (MANUAL pelo usuário do sistema)

**Enviada para:** Consultas com status AGUARDANDO_COMPROVANTE
**Quando:** Usuário do sistema anexa PDF/JPG do comprovante
**Como:** Interface web - Upload de arquivo
**Status:** AGUARDANDO_COMPROVANTE → CONFIRMADO

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

**Ação adicional:**
- Sistema envia o comprovante (PDF/JPG) junto com a mensagem

---

### MENSAGEM 3: Rejeitado - Voltar ao Posto (AUTOMÁTICA)

**Enviada para:** INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = SIM
**Quando:** Paciente responde NÃO na MSG 1
**Status:** REJEITADO (mantém)

```
HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com {PACIENTE}? Sua consulta para o serviço de {ESPECIALIDADE} foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!
```

**Variáveis:**
- `{PACIENTE}` - Nome do paciente
- `{ESPECIALIDADE}` - Especialidade da consulta

---

## 🗂️ ESTRUTURA DA PLANILHA DE IMPORTAÇÃO

### Colunas (baseado na imagem fornecida):

```
ID
POSICAO
COD MASTER
CODIGO AGHU
PACIENTE                    ← Nome do paciente
TELEFONE CADASTRO           ← Telefone 1
TELEFONE REGISTRO           ← Telefone 2
DATA DO REGISTRO
PROCEDÊNCIA
MEDICO_SOLICITANTE          ← Usado na MSG 1
TIPO                        ← RETORNO ou INTERCONSULTA
OBSERVAÇÕES
EXAMES
SUB-ESPECIALIDADE
ESPECIALIDADE               ← Usado nas mensagens
GRADE_AGHU
PRIORIDADE
INDICACAO DATA
DATA REQUISIÇÃO
DATA EXATA OU DIAS
ESTIMATIVA AGENDAMENTO
DATA AGHU                   ← Data da consulta (usado na MSG 1)
PACIENTE_VOLTAR_POSTO_SMS   ← SIM ou NÃO (apenas INTERCONSULTA)
```

**Exemplo:**
```
ID: 92780
PACIENTE: GUSTAVO DA COSTA PEREIRA
TELEFONE CADASTRO: 85992231683
TELEFONE REGISTRO: 85992231683
TIPO: RETORNO
SUB-ESPECIALIDADE: OTOLOGIA
ESPECIALIDADE: OTORRINOLARINGOLOGIA
DATA AGHU: 5/20/2024
MEDICO_SOLICITANTE: JULIANA SOEIRO MAIA
```

---

## 🔧 MUDANÇAS NO CADASTRO DE USUÁRIOS

### Campo Adicional no Modelo `Usuario`:

**ANTES:**
```python
tipo_sistema = db.Column(db.String(50), default='BUSCA_ATIVA')
# Só tinha BUSCA_ATIVA
```

**DEPOIS:**
```python
tipo_sistema = db.Column(db.String(50), default='BUSCA_ATIVA')
# Valores possíveis:
# - BUSCA_ATIVA (Fila Cirúrgica) ← MANTÉM COMO ESTÁ
# - AGENDAMENTO_CONSULTA (Consultas)
```

### Tela de Cadastro/Edição de Usuário:

**Adicionar campo:**
```html
<label>Tipo de Sistema</label>
<select name="tipo_sistema" class="form-control">
    <option value="BUSCA_ATIVA">Fila Cirúrgica</option>
    <option value="AGENDAMENTO_CONSULTA">Agendamento de Consultas</option>
</select>
```

**Comportamento:**
- Se tipo = `BUSCA_ATIVA` → Menu mostra "Fila Cirúrgica"
- Se tipo = `AGENDAMENTO_CONSULTA` → Menu mostra "Consultas"

---

## 📊 BANCO DE DADOS - NOVAS TABELAS

### 1. `campanhas_consultas`

```sql
CREATE TABLE campanhas_consultas (
    id SERIAL PRIMARY KEY,
    criador_id INTEGER REFERENCES usuarios(id),
    nome VARCHAR(200) NOT NULL,
    descricao TEXT,
    status VARCHAR(50) DEFAULT 'pendente',
    -- pendente, enviando, pausado, concluido, erro

    -- Configurações (IGUAIS à fila cirúrgica)
    meta_diaria INTEGER DEFAULT 50,
    hora_inicio INTEGER DEFAULT 8,
    hora_fim INTEGER DEFAULT 23,
    tempo_entre_envios INTEGER DEFAULT 15,
    dias_duracao INTEGER DEFAULT 0,

    -- Controle diário
    enviados_hoje INTEGER DEFAULT 0,
    data_ultimo_envio DATE,

    -- Estatísticas
    total_consultas INTEGER DEFAULT 0,
    total_enviados INTEGER DEFAULT 0,
    total_confirmados INTEGER DEFAULT 0,
    total_aguardando_comprovante INTEGER DEFAULT 0,
    total_rejeitados INTEGER DEFAULT 0,

    -- Timestamps
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_inicio TIMESTAMP,
    data_fim TIMESTAMP
);
```

### 2. `agendamentos_consultas`

```sql
CREATE TABLE agendamentos_consultas (
    id SERIAL PRIMARY KEY,
    campanha_id INTEGER REFERENCES campanhas_consultas(id),
    usuario_id INTEGER REFERENCES usuarios(id),

    -- Dados da planilha (TODAS as colunas)
    posicao VARCHAR(50),
    cod_master VARCHAR(50),
    codigo_aghu VARCHAR(50),
    paciente VARCHAR(200) NOT NULL,
    telefone_cadastro VARCHAR(20),
    telefone_registro VARCHAR(20),
    data_registro VARCHAR(50),
    procedencia VARCHAR(200),
    medico_solicitante VARCHAR(200),
    tipo VARCHAR(50) NOT NULL,  -- RETORNO ou INTERCONSULTA
    observacoes TEXT,
    exames TEXT,
    sub_especialidade VARCHAR(200),
    especialidade VARCHAR(200),
    grade_aghu VARCHAR(50),
    prioridade VARCHAR(50),
    indicacao_data VARCHAR(50),
    data_requisicao VARCHAR(50),
    data_exata_ou_dias VARCHAR(50),
    estimativa_agendamento VARCHAR(50),
    data_aghu VARCHAR(50),  -- Data da consulta

    -- Campo específico INTERCONSULTA
    paciente_voltar_posto_sms VARCHAR(10),  -- SIM ou NÃO

    -- Controle de status
    status VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO',
    -- AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO → AGUARDANDO_COMPROVANTE → CONFIRMADO
    --                                           → REJEITADO

    mensagem_enviada BOOLEAN DEFAULT FALSE,
    data_envio_mensagem TIMESTAMP,

    -- Comprovante
    comprovante_path VARCHAR(255),

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_confirmacao TIMESTAMP,
    data_rejeicao TIMESTAMP
);
```

### 3. `telefones_consultas`

```sql
CREATE TABLE telefones_consultas (
    id SERIAL PRIMARY KEY,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
    numero VARCHAR(20) NOT NULL,
    prioridade INTEGER DEFAULT 1,
    enviado BOOLEAN DEFAULT FALSE,
    data_envio TIMESTAMP,
    msg_id VARCHAR(100),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_telefones_consultas_consulta ON telefones_consultas(consulta_id);
```

### 4. `logs_msgs_consultas`

```sql
CREATE TABLE logs_msgs_consultas (
    id SERIAL PRIMARY KEY,
    campanha_id INTEGER REFERENCES campanhas_consultas(id) ON DELETE CASCADE,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
    direcao VARCHAR(20) NOT NULL,  -- enviada ou recebida
    telefone VARCHAR(20) NOT NULL,
    mensagem TEXT,
    status VARCHAR(20),  -- sucesso ou erro
    erro TEXT,
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_logs_msgs_consultas_campanha ON logs_msgs_consultas(campanha_id);
CREATE INDEX idx_logs_msgs_consultas_consulta ON logs_msgs_consultas(consulta_id);
```

---

## 🎯 PASSO A PASSO DA IMPLEMENTAÇÃO

### FASE 1: Banco de Dados ✅

1. Criar as 4 tabelas novas
2. Não alterar nada da fila cirúrgica
3. Adicionar campo `tipo_sistema` se não existir em `usuarios`

### FASE 2: Modelos SQLAlchemy ✅

1. Criar modelos em `app.py`:
   - `CampanhaConsulta`
   - `AgendamentoConsulta`
   - `TelefoneConsulta`
   - `LogMsgConsulta`

2. Métodos importantes:
   - `pode_enviar_hoje()` - Verifica meta diária
   - `pode_enviar_agora()` - Verifica horário
   - `calcular_intervalo()` - Calcula tempo entre envios
   - `atualizar_stats()` - Atualiza estatísticas

### FASE 3: Funções de Mensagens ✅

Criar em `app.py`:

```python
def formatar_mensagem_consulta_inicial(consulta):
    """MSG 1: Confirmação inicial"""
    return f"""Bom dia!
Falamos do HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO.
Estamos informando que a CONSULTA do paciente {consulta.paciente}, foi MARCADA para o dia {consulta.data_aghu}, com {consulta.medico_solicitante}, com especialidade em {consulta.especialidade}.

Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?"""

def formatar_mensagem_comprovante():
    """MSG 2: Envio de comprovante"""
    return """O Hospital Walter Cantídio agradece seu contato. CONSULTA CONFIRMADA!

Responda a pesquisa de satisfação: https://forms.gle/feteZxSNBRd5xfDUA

O hospital entra em contato através do: (85) 992081534 / (85)996700783 / (85)991565903 / (85) 992614237 / (85) 992726080. É importante que atenda as ligações e responda as mensagens desses números. Por tanto, salve-os!

Confira seu comprovante: data, horário e nome do(a) médico(a).

Não fazemos marcação de exames, apenas consultas.

Caso falte, procurar o ambulatório para ser colocado novamente no pré-agendamento.

Você sabia que pode verificar sua consulta no app HU Digital? https://play.google.com/store/apps/details?id=br.gov.ebserh.hudigital&pcampaignid=web_share . Após 5 horas dessa mensagem, verifique sua consulta agendada no app.

Reagendamentos estarão presentes no app HU Digital. Verifique sempre o app HU Digital."""

def formatar_mensagem_voltar_posto(consulta):
    """MSG 3: Rejeitado - Voltar ao posto"""
    return f"""HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com {consulta.paciente}? Sua consulta para o serviço de {consulta.especialidade} foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!"""
```

### FASE 4: Task Celery de Envio ✅

Criar em `tasks.py`:

```python
@celery.task(base=DatabaseTask, bind=True)
def enviar_campanha_consultas_task(self, campanha_id):
    """
    Envia MSG 1 automaticamente para todas as consultas
    AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO
    """
    # Cópia exata da lógica da fila cirúrgica
    # Respeita meta diária, horário, intervalo
    # Envia formatar_mensagem_consulta_inicial()
```

### FASE 5: Endpoints Flask ✅

Criar em `app.py`:

```python
# Dashboard
@app.route('/consultas/dashboard')

# Detalhes da campanha
@app.route('/consultas/campanha/<int:id>')

# Controle de envio (IGUAL fila cirúrgica)
@app.route('/consultas/campanha/<int:id>/iniciar', methods=['POST'])
@app.route('/consultas/campanha/<int:id>/pausar', methods=['POST'])
@app.route('/consultas/campanha/<int:id>/continuar', methods=['POST'])

# Importar planilha
@app.route('/consultas/importar', methods=['POST'])

# Enviar comprovante (NOVO - específico de consultas)
@app.route('/api/consulta/<int:id>/enviar_comprovante', methods=['POST'])
# Upload de PDF/JPG + envio da MSG 2

# Confirmar/Cancelar manualmente
@app.route('/api/consulta/<int:id>/confirmar', methods=['POST'])
@app.route('/api/consulta/<int:id>/cancelar', methods=['POST'])
```

### FASE 6: Webhook - Processar Respostas ✅

Adicionar ao webhook existente:

```python
def processar_resposta_consulta(telefone, mensagem_texto):
    """
    Processa resposta do paciente

    SIM/OK/CONFIRMO → Status: AGUARDANDO_COMPROVANTE
    NÃO/CANCELO → Status: REJEITADO
        → Se INTERCONSULTA e PACIENTE_VOLTAR_POSTO_SMS = SIM
           → Enviar MSG 3 (voltar ao posto)
    """
```

### FASE 7: Templates HTML ✅

Criar:
- `consultas_dashboard.html` - Lista de campanhas
- `campanha_consultas_detalhe.html` - Detalhes da campanha
- `consulta_detalhe.html` - Detalhes individual + Upload de comprovante

### FASE 8: Menu Dinâmico ✅

Alterar menu em `base.html`:

```html
{% if current_user.tipo_sistema == 'BUSCA_ATIVA' %}
    <a href="/dashboard">Fila Cirúrgica</a>
{% elif current_user.tipo_sistema == 'AGENDAMENTO_CONSULTA' %}
    <a href="/consultas/dashboard">Consultas</a>
{% endif %}
```

---

## 🔄 FLUXO COMPLETO - EXEMPLO PRÁTICO

### Cenário 1: RETORNO - Paciente Confirma

```
1. Importar planilha → Cria consulta (status: AGUARDANDO_ENVIO)
2. Iniciar envio → Celery envia MSG 1
   ↓
3. Status muda: AGUARDANDO_CONFIRMACAO
4. Paciente responde: "SIM"
   ↓
5. Status muda: AGUARDANDO_COMPROVANTE
6. Usuário do sistema:
   - Acessa detalhes da consulta
   - Faz upload do comprovante (PDF/JPG)
   - Clica "Enviar Comprovante"
   ↓
7. Sistema envia MSG 2 + arquivo
8. Status muda: CONFIRMADO ✅
```

### Cenário 2: INTERCONSULTA - Paciente Rejeita (Voltar ao Posto)

```
1. Importar planilha → Cria consulta
   - TIPO: INTERCONSULTA
   - PACIENTE_VOLTAR_POSTO_SMS: SIM
   - Status: AGUARDANDO_ENVIO
   ↓
2. Iniciar envio → Celery envia MSG 1
   ↓
3. Status muda: AGUARDANDO_CONFIRMACAO
4. Paciente responde: "NÃO"
   ↓
5. Status muda: REJEITADO
6. Sistema verifica:
   - É INTERCONSULTA? SIM
   - PACIENTE_VOLTAR_POSTO_SMS = SIM? SIM
   ↓
7. Sistema envia automaticamente MSG 3 (voltar ao posto)
8. Fim ❌
```

### Cenário 3: RETORNO - Paciente Rejeita (Simples)

```
1. Importar planilha → Cria consulta (TIPO: RETORNO)
2. Iniciar envio → Celery envia MSG 1
   ↓
3. Paciente responde: "NÃO"
   ↓
4. Status muda: REJEITADO
5. Fim (sem enviar MSG 3) ❌
```

---

## ✅ CHECKLIST DE IMPLEMENTAÇÃO

### Banco de Dados
- [ ] Criar tabela `campanhas_consultas`
- [ ] Criar tabela `agendamentos_consultas`
- [ ] Criar tabela `telefones_consultas`
- [ ] Criar tabela `logs_msgs_consultas`
- [ ] Verificar campo `tipo_sistema` em `usuarios`

### Backend
- [ ] Modelos SQLAlchemy (4 classes)
- [ ] Função `formatar_mensagem_consulta_inicial()`
- [ ] Função `formatar_mensagem_comprovante()`
- [ ] Função `formatar_mensagem_voltar_posto()`
- [ ] Task Celery `enviar_campanha_consultas_task()`
- [ ] Endpoints Flask (8 rotas)
- [ ] Webhook `processar_resposta_consulta()`
- [ ] Importação de planilha Excel

### Frontend
- [ ] Template `consultas_dashboard.html`
- [ ] Template `campanha_consultas_detalhe.html`
- [ ] Template `consulta_detalhe.html` (com upload)
- [ ] Menu dinâmico baseado em `tipo_sistema`
- [ ] Tela de cadastro de usuário (select tipo_sistema)

### Testes
- [ ] Importar planilha de RETORNO
- [ ] Importar planilha de INTERCONSULTA
- [ ] Iniciar envio automático
- [ ] Paciente confirmar (SIM)
- [ ] Enviar comprovante
- [ ] Paciente rejeitar (NÃO)
- [ ] Verificar MSG 3 em INTERCONSULTA com VOLTAR_POSTO = SIM

---

## ⚠️ O QUE NÃO ALTERAR

### MANTER INTACTO:
1. ✅ Todas as tabelas da fila cirúrgica:
   - `campanhas`
   - `contatos`
   - `telefones`
   - `logs_msgs`
   - `procedimentos_normalizados`
   - etc.

2. ✅ Todos os endpoints da fila cirúrgica:
   - `/dashboard`
   - `/campanha/<id>`
   - `/campanha/<id>/iniciar`
   - etc.

3. ✅ Task Celery da fila cirúrgica:
   - `enviar_campanha_task()`
   - `validar_campanha_task()`
   - `follow_up_automatico_task()`
   - etc.

4. ✅ Templates da fila cirúrgica:
   - `dashboard.html`
   - `campanha.html`
   - `contato_detalhes.html`
   - etc.

### APENAS ADICIONAR NOVO:
- ✅ Novas tabelas (prefixo `_consultas`)
- ✅ Novos endpoints (prefixo `/consultas/`)
- ✅ Nova task Celery (`enviar_campanha_consultas_task`)
- ✅ Novos templates (prefixo `consultas_`)

---

## 🎯 RESUMO EXECUTIVO

### O que será feito:
1. **4 novas tabelas** no banco (não altera nada da fila)
2. **3 funções de mensagens** (MSG 1, MSG 2, MSG 3)
3. **1 task Celery** (cópia da fila cirúrgica)
4. **8 endpoints Flask** novos
5. **3 templates HTML** novos
6. **Menu dinâmico** (mostra Fila OU Consultas conforme usuário)
7. **Upload de comprovante** (funcionalidade nova)

### Diferenciais da Fila Cirúrgica:
- Fila: Envia e aguarda resposta (fim)
- Consultas: Envia → Aguarda confirmação → Aguarda comprovante → Confirmado
- Consultas: Tem MSG 3 específica para INTERCONSULTA rejeitada

### Tecnologias:
- Backend: Flask + SQLAlchemy (mesmas que a fila)
- Processamento: Celery + Redis (mesmos que a fila)
- WhatsApp: Evolution API (mesma que a fila)

---

## ❓ DÚVIDAS PARA ESCLARECER

Antes de implementar, confirme:

1. ✅ As 3 mensagens estão corretas?
2. ✅ O fluxo de status está correto?
3. ✅ A coluna `PACIENTE_VOLTAR_POSTO_SMS` só existe em INTERCONSULTA?
4. ✅ O comprovante é sempre PDF/JPG?
5. ✅ Após enviar comprovante, já marca como CONFIRMADO ou aguarda algo?
6. ✅ A planilha terá TODAS as colunas listadas?

---

## 🚀 PRÓXIMOS PASSOS (AGUARDANDO SUA APROVAÇÃO)

1. ✅ Você APROVA este plano?
2. ✅ Tem alguma correção/ajuste?
3. ✅ Posso começar a implementar?

**AGUARDANDO SUA RESPOSTA PARA INICIAR! 🎯**
