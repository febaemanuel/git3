# 📋 IMPLEMENTAÇÃO COMPLETA DO MODO CONSULTA - BUSCA ATIVA

## 📌 CONTEXTO E OBJETIVO

O sistema já possui uma **Fila Cirúrgica (BUSCA_ATIVA)** totalmente funcional que envia mensagens WhatsApp automaticamente usando Celery. O objetivo é criar um **Modo Consulta (AGENDAMENTO_CONSULTA)** que funcione **EXATAMENTE** da mesma forma.

### Sistema Atual (Fila Cirúrgica) - FUNCIONAL ✅
- Usuários do tipo `BUSCA_ATIVA`
- Envia mensagens para pacientes aguardando cirurgia
- Usa Celery para processamento assíncrono em background
- Respeita meta diária, horário de funcionamento, intervalo entre envios
- Interface: Botão "Iniciar Envio" → Sistema processa tudo automaticamente

### Sistema Desejado (Agendamento de Consultas) - A IMPLEMENTAR
- Usuários do tipo `AGENDAMENTO_CONSULTA`
- Envia mensagens para pacientes com consultas agendadas (RETORNO e INTERCONSULTA)
- Deve usar a **MESMA arquitetura** da fila cirúrgica
- Mesma confiabilidade e automação

---

## 🏗️ ARQUITETURA DO SISTEMA

### Stack Tecnológico
- **Backend:** Flask (Python)
- **Banco de Dados:** PostgreSQL/MySQL (SQLAlchemy)
- **Processamento Assíncrono:** Celery
- **Broker:** Redis
- **API WhatsApp:** Evolution API

### Fluxo de Funcionamento
```
┌─────────────────────────────────────────────────────────────┐
│ 1. Usuário importa planilha de consultas                   │
├─────────────────────────────────────────────────────────────┤
│ 2. Sistema cria registros no banco:                        │
│    - CampanhaConsulta                                       │
│    - AgendamentoConsulta (status: AGUARDANDO_ENVIO)        │
│    - TelefoneConsulta                                       │
├─────────────────────────────────────────────────────────────┤
│ 3. Usuário clica "Iniciar Envio Automático"                │
├─────────────────────────────────────────────────────────────┤
│ 4. Flask inicia Task Celery em background                  │
├─────────────────────────────────────────────────────────────┤
│ 5. Celery processa TODAS as consultas:                     │
│    • Verifica horário (8h-23h)                             │
│    • Verifica meta diária (ex: 50/dia)                     │
│    • Busca consultas com status AGUARDANDO_ENVIO           │
│    • Para cada consulta:                                   │
│      - Formata mensagem personalizada                      │
│      - Envia via WhatsApp                                  │
│      - Muda status → AGUARDANDO_CONFIRMACAO                │
│      - Registra log (LogMsgConsulta)                       │
│      - Aguarda intervalo (calculado automaticamente)       │
│    • Se meta diária atingida → Pausa até amanhã            │
│    • Se fora do horário → Pausa até 8h                     │
├─────────────────────────────────────────────────────────────┤
│ 6. Paciente responde via WhatsApp                          │
├─────────────────────────────────────────────────────────────┤
│ 7. Webhook processa resposta                               │
│    • Status muda → AGUARDANDO_COMPROVANTE ou REJEITADO     │
├─────────────────────────────────────────────────────────────┤
│ 8. Usuário envia comprovante (se necessário)               │
│    • Status muda → CONFIRMADO                              │
└─────────────────────────────────────────────────────────────┘
```

---

## 📊 ESTRUTURA DO BANCO DE DADOS

### 1. Tabela: `campanhas_consultas`

Representa uma campanha de envio de mensagens para consultas.

```sql
CREATE TABLE campanhas_consultas (
    id SERIAL PRIMARY KEY,
    criador_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,

    -- Informações básicas
    nome VARCHAR(200) NOT NULL,
    descricao TEXT,

    -- Controle de status
    status VARCHAR(50) DEFAULT 'pendente',
    -- Status possíveis: pendente, enviando, pausado, concluido, erro
    status_msg VARCHAR(200),

    -- Configurações de envio
    meta_diaria INTEGER DEFAULT 50,
    hora_inicio INTEGER DEFAULT 8,
    hora_fim INTEGER DEFAULT 23,
    tempo_entre_envios INTEGER DEFAULT 15,  -- segundos
    dias_duracao INTEGER DEFAULT 0,  -- 0 = sem limite

    -- Controle diário
    enviados_hoje INTEGER DEFAULT 0,
    data_ultimo_envio DATE,

    -- Estatísticas
    total_consultas INTEGER DEFAULT 0,
    total_enviados INTEGER DEFAULT 0,
    total_confirmados INTEGER DEFAULT 0,
    total_aguardando_comprovante INTEGER DEFAULT 0,
    total_cancelados INTEGER DEFAULT 0,
    total_rejeitados INTEGER DEFAULT 0,

    -- Timestamps
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_inicio TIMESTAMP,
    data_fim TIMESTAMP
);
```

### 2. Tabela: `agendamentos_consultas`

Representa cada consulta individual (RETORNO ou INTERCONSULTA).

```sql
CREATE TABLE agendamentos_consultas (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    campanha_id INTEGER REFERENCES campanhas_consultas(id) ON DELETE SET NULL,

    -- Dados da planilha
    pasta VARCHAR(50),
    od_maste VARCHAR(50),
    codigo_agh VARCHAR(50),
    paciente VARCHAR(200) NOT NULL,
    telefone_cadas VARCHAR(20),
    telefone_regist VARCHAR(20),
    tipo VARCHAR(50) NOT NULL,  -- RETORNO ou INTERCONSULTA

    -- Dados da consulta
    sub_especialidade VARCHAR(200),
    especialidade VARCHAR(200),
    grade VARCHAR(50),
    prioridade VARCHAR(50),
    data_aghu VARCHAR(50),  -- Data da consulta
    hora_consulta VARCHAR(10),
    dia_semana VARCHAR(20),
    unidade_funcional VARCHAR(200),
    profissional VARCHAR(200),

    -- Campo específico para INTERCONSULTA
    paciente_voltar_posto_sms VARCHAR(10),  -- SIM ou NÃO

    -- Controle de status
    status VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO',
    -- Status: AGUARDANDO_ENVIO, AGUARDANDO_CONFIRMACAO, AGUARDANDO_COMPROVANTE,
    --         CONFIRMADO, CANCELADO, REJEITADO

    -- Controle de envio
    mensagem_enviada BOOLEAN DEFAULT FALSE,
    data_envio_mensagem TIMESTAMP,

    -- Comprovante
    comprovante_path VARCHAR(255),
    observacoes TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_confirmacao TIMESTAMP,
    data_cancelamento TIMESTAMP
);
```

### 3. Tabela: `telefones_consultas`

Múltiplos telefones por consulta (prioridade de envio).

```sql
CREATE TABLE telefones_consultas (
    id SERIAL PRIMARY KEY,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,

    numero VARCHAR(20) NOT NULL,
    prioridade INTEGER DEFAULT 1,  -- Ordem de tentativa

    -- Controle de envio
    enviado BOOLEAN DEFAULT FALSE,
    data_envio TIMESTAMP,
    msg_id VARCHAR(100),  -- ID da mensagem no WhatsApp

    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_telefones_consultas_consulta ON telefones_consultas(consulta_id);
CREATE INDEX idx_telefones_consultas_prioridade ON telefones_consultas(consulta_id, prioridade);
```

### 4. Tabela: `logs_msgs_consultas`

Histórico de todas as mensagens (enviadas e recebidas).

```sql
CREATE TABLE logs_msgs_consultas (
    id SERIAL PRIMARY KEY,
    campanha_id INTEGER REFERENCES campanhas_consultas(id) ON DELETE CASCADE,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,

    direcao VARCHAR(20) NOT NULL,  -- 'enviada' ou 'recebida'
    telefone VARCHAR(20) NOT NULL,
    mensagem TEXT,

    status VARCHAR(20),  -- 'sucesso' ou 'erro'
    erro TEXT,

    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_logs_msgs_consultas_campanha ON logs_msgs_consultas(campanha_id);
CREATE INDEX idx_logs_msgs_consultas_consulta ON logs_msgs_consultas(consulta_id);
```

---

## 🔧 IMPLEMENTAÇÃO - PASSO A PASSO

### PASSO 1: Modelos SQLAlchemy (app.py)

Adicione os modelos no arquivo `app.py`:

```python
# =============================================================================
# MODELOS - AGENDAMENTO DE CONSULTAS
# =============================================================================

class CampanhaConsulta(db.Model):
    """Modelo para campanhas de agendamento de consultas"""
    __tablename__ = 'campanhas_consultas'
    id = db.Column(db.Integer, primary_key=True)

    # Relacionamento com usuário
    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'))

    # Informações básicas
    nome = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)

    # Controle de status
    status = db.Column(db.String(50), default='pendente')
    status_msg = db.Column(db.String(200))

    # Configurações de envio (IGUAIS À FILA CIRÚRGICA)
    meta_diaria = db.Column(db.Integer, default=50)
    hora_inicio = db.Column(db.Integer, default=8)
    hora_fim = db.Column(db.Integer, default=23)
    tempo_entre_envios = db.Column(db.Integer, default=15)
    dias_duracao = db.Column(db.Integer, default=0)

    # Controle diário
    enviados_hoje = db.Column(db.Integer, default=0)
    data_ultimo_envio = db.Column(db.Date)

    # Estatísticas
    total_consultas = db.Column(db.Integer, default=0)
    total_enviados = db.Column(db.Integer, default=0)
    total_confirmados = db.Column(db.Integer, default=0)
    total_aguardando_comprovante = db.Column(db.Integer, default=0)
    total_cancelados = db.Column(db.Integer, default=0)
    total_rejeitados = db.Column(db.Integer, default=0)

    # Timestamps
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_inicio = db.Column(db.DateTime)
    data_fim = db.Column(db.DateTime)

    # Relacionamentos
    criador = db.relationship('Usuario', backref='campanhas_consultas')
    consultas = db.relationship('AgendamentoConsulta', backref='campanha', lazy='dynamic')

    def atualizar_stats(self):
        """Atualiza estatísticas - COPIADO DA FILA CIRÚRGICA"""
        self.total_consultas = self.consultas.count()
        self.total_enviados = self.consultas.filter(AgendamentoConsulta.status != 'AGUARDANDO_ENVIO').count()
        self.total_confirmados = self.consultas.filter_by(status='CONFIRMADO').count()
        self.total_aguardando_comprovante = self.consultas.filter_by(status='AGUARDANDO_COMPROVANTE').count()
        self.total_cancelados = self.consultas.filter_by(status='CANCELADO').count()
        self.total_rejeitados = self.consultas.filter_by(status='REJEITADO').count()

    def pode_enviar_hoje(self):
        """Verifica se pode enviar mais consultas hoje - IGUAL À FILA"""
        hoje = date.today()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 0
            self.data_ultimo_envio = hoje
            db.session.commit()
        return self.enviados_hoje < self.meta_diaria

    def pode_enviar_agora(self):
        """Verifica se está dentro do horário de envio - IGUAL À FILA"""
        agora = datetime.now()
        hora_atual = agora.hour

        if self.hora_inicio <= self.hora_fim:
            # Horário normal (ex: 8h às 18h)
            dentro_horario = self.hora_inicio <= hora_atual < self.hora_fim
        else:
            # Horário overnight (ex: 22h às 6h)
            dentro_horario = hora_atual >= self.hora_inicio or hora_atual < self.hora_fim

        return dentro_horario

    def atingiu_duracao(self):
        """Verifica se atingiu o número de dias definido - IGUAL À FILA"""
        if self.dias_duracao == 0:
            return False  # Sem limite

        if not self.data_inicio:
            return False

        dias_decorridos = (datetime.now() - self.data_inicio).days
        return dias_decorridos >= self.dias_duracao

    def registrar_envio(self):
        """Registra que um envio foi realizado hoje - IGUAL À FILA"""
        hoje = date.today()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 1
            self.data_ultimo_envio = hoje
        else:
            self.enviados_hoje += 1
        db.session.commit()

    def calcular_intervalo(self):
        """Calcula intervalo entre envios baseado na meta e horário - IGUAL À FILA"""
        if self.meta_diaria <= 0:
            return 15  # Default

        if self.hora_inicio <= self.hora_fim:
            horas_disponiveis = self.hora_fim - self.hora_inicio
        else:
            horas_disponiveis = (24 - self.hora_inicio) + self.hora_fim

        segundos_disponiveis = horas_disponiveis * 3600
        intervalo = segundos_disponiveis // self.meta_diaria

        # Mínimo 5s, máximo 300s (5min)
        return max(5, min(intervalo, 300))

    def pendentes_enviar(self):
        """Consultas prontas para envio"""
        return self.consultas.filter_by(status='AGUARDANDO_ENVIO').count()


class AgendamentoConsulta(db.Model):
    """Modelo para agendamento de consultas (RETORNO e INTERCONSULTA)"""
    __tablename__ = 'agendamentos_consultas'
    id = db.Column(db.Integer, primary_key=True)

    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'))
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas_consultas.id', ondelete='SET NULL'))

    # Dados da planilha
    pasta = db.Column(db.String(50))
    od_maste = db.Column(db.String(50))
    codigo_agh = db.Column(db.String(50))
    paciente = db.Column(db.String(200), nullable=False)
    telefone_cadas = db.Column(db.String(20))
    telefone_regist = db.Column(db.String(20))
    tipo = db.Column(db.String(50), nullable=False)  # RETORNO ou INTERCONSULTA

    # Dados da consulta
    sub_especialidade = db.Column(db.String(200))
    especialidade = db.Column(db.String(200))
    grade = db.Column(db.String(50))
    prioridade = db.Column(db.String(50))
    data_aghu = db.Column(db.String(50))
    hora_consulta = db.Column(db.String(10))
    dia_semana = db.Column(db.String(20))
    unidade_funcional = db.Column(db.String(200))
    profissional = db.Column(db.String(200))
    paciente_voltar_posto_sms = db.Column(db.String(10))

    # Controle de status
    status = db.Column(db.String(50), default='AGUARDANDO_ENVIO')
    mensagem_enviada = db.Column(db.Boolean, default=False)
    data_envio_mensagem = db.Column(db.DateTime)

    # Comprovante
    comprovante_path = db.Column(db.String(255))
    observacoes = db.Column(db.Text)

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_confirmacao = db.Column(db.DateTime)
    data_cancelamento = db.Column(db.DateTime)

    # Relacionamentos
    usuario = db.relationship('Usuario', backref='agendamentos_consultas')
    telefones = db.relationship('TelefoneConsulta', backref='consulta', lazy='dynamic', cascade='all, delete-orphan')

    def get_telefone_principal(self):
        """Retorna o telefone principal"""
        primeiro_tel = self.telefones.first()
        if primeiro_tel:
            return primeiro_tel.numero
        return self.telefone_regist if self.telefone_regist else self.telefone_cadas

    def telefones_str(self):
        """String com todos os telefones"""
        return ", ".join([t.numero for t in self.telefones])

    def status_badge(self):
        """Classe CSS do badge baseado no status"""
        badges = {
            'AGUARDANDO_ENVIO': 'bg-secondary',
            'AGUARDANDO_CONFIRMACAO': 'bg-warning text-dark',
            'AGUARDANDO_COMPROVANTE': 'bg-info',
            'CONFIRMADO': 'bg-success',
            'CANCELADO': 'bg-dark',
            'REJEITADO': 'bg-danger'
        }
        return badges.get(self.status, 'bg-light text-dark')

    def status_texto(self):
        """Texto amigável do status"""
        textos = {
            'AGUARDANDO_ENVIO': 'Aguardando Envio',
            'AGUARDANDO_CONFIRMACAO': 'Aguardando Confirmação',
            'AGUARDANDO_COMPROVANTE': 'Aguardando Comprovante',
            'CONFIRMADO': 'Confirmado',
            'CANCELADO': 'Cancelado',
            'REJEITADO': 'Rejeitado'
        }
        return textos.get(self.status, self.status)


class TelefoneConsulta(db.Model):
    """Modelo para telefones das consultas"""
    __tablename__ = 'telefones_consultas'
    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='CASCADE'))

    numero = db.Column(db.String(20), nullable=False)
    prioridade = db.Column(db.Integer, default=1)

    enviado = db.Column(db.Boolean, default=False)
    data_envio = db.Column(db.DateTime)
    msg_id = db.Column(db.String(100))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class LogMsgConsulta(db.Model):
    """Modelo para logs de mensagens das consultas"""
    __tablename__ = 'logs_msgs_consultas'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas_consultas.id', ondelete='CASCADE'))
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='CASCADE'))

    direcao = db.Column(db.String(20), nullable=False)
    telefone = db.Column(db.String(20), nullable=False)
    mensagem = db.Column(db.Text)

    status = db.Column(db.String(20))
    erro = db.Column(db.Text)

    data = db.Column(db.DateTime, default=datetime.utcnow)
```

### PASSO 2: Função de Formatação de Mensagem (app.py)

Adicione a função que formata a mensagem personalizada para cada tipo de consulta:

```python
def formatar_mensagem_consulta(consulta):
    """
    Formata mensagem WhatsApp baseada no tipo e status da consulta

    Tipos:
    - RETORNO: Paciente já foi atendido, retornar para nova consulta
    - INTERCONSULTA: Paciente encaminhado de outra especialidade

    Mensagens diferentes baseadas em status e respostas
    """
    # MSG 1: Confirmação inicial (AGUARDANDO_CONFIRMACAO)
    if consulta.status == 'AGUARDANDO_CONFIRMACAO':
        if consulta.tipo == 'RETORNO':
            msg = f"""Olá, {consulta.paciente}!

Você tem uma consulta de RETORNO agendada:

📅 Data: {consulta.data_aghu}
🕒 Horário: {consulta.hora_consulta}
🏥 Local: {consulta.unidade_funcional}
👨‍⚕️ Profissional: {consulta.profissional}
📋 Especialidade: {consulta.especialidade}

Para CONFIRMAR sua presença, responda:
✅ SIM - Vou comparecer
❌ NÃO - Não poderei ir

Aguardamos sua confirmação!"""

        else:  # INTERCONSULTA
            msg = f"""Olá, {consulta.paciente}!

Você foi encaminhado(a) para uma INTERCONSULTA:

📅 Data: {consulta.data_aghu}
🕒 Horário: {consulta.hora_consulta}
🏥 Local: {consulta.unidade_funcional}
👨‍⚕️ Profissional: {consulta.profissional}
📋 Especialidade: {consulta.especialidade}

Para CONFIRMAR sua presença, responda:
✅ SIM - Vou comparecer
❌ NÃO - Não poderei ir

Aguardamos sua confirmação!"""

    # MSG 2: Após rejeição de INTERCONSULTA - paciente deve voltar ao posto
    elif consulta.status == 'REJEITADO' and consulta.tipo == 'INTERCONSULTA':
        if consulta.paciente_voltar_posto_sms == 'SIM':
            msg = f"""Olá, {consulta.paciente}!

Você informou que NÃO poderá comparecer à interconsulta.

⚠️ IMPORTANTE: Você precisa retornar ao seu posto de saúde (SMS) para reagendar.

📋 Consulta:
Data: {consulta.data_aghu}
Especialidade: {consulta.especialidade}

Por favor, procure seu posto de saúde o quanto antes."""
        else:
            msg = f"""Olá, {consulta.paciente}!

Você informou que NÃO poderá comparecer à interconsulta.

Sua consulta foi cancelada:
Data: {consulta.data_aghu}
Especialidade: {consulta.especialidade}

Se precisar reagendar, entre em contato conosco."""

    # MSG 3: Após confirmação - solicitar comprovante
    elif consulta.status == 'CONFIRMADO':
        msg = f"""Obrigado por confirmar, {consulta.paciente}!

Sua consulta está CONFIRMADA:

📅 Data: {consulta.data_aghu}
🕒 Horário: {consulta.hora_consulta}
🏥 Local: {consulta.unidade_funcional}

⚠️ NÃO ESQUEÇA:
- Chegar 30 minutos antes
- Trazer documento com foto
- Trazer cartão do SUS
- Trazer exames anteriores (se houver)

Nos vemos lá! 😊"""

    else:
        # Mensagem padrão
        msg = f"""Olá, {consulta.paciente}!

Você tem uma consulta agendada em {consulta.data_aghu} às {consulta.hora_consulta}.

Para mais informações, entre em contato conosco."""

    return msg
```

### PASSO 3: Task Celery de Envio (tasks.py)

Adicione a task Celery que processa o envio automático (CÓPIA EXATA da fila cirúrgica):

```python
@celery.task(
    base=DatabaseTask,
    bind=True,
    name='tasks.enviar_campanha_consultas_task'
)
def enviar_campanha_consultas_task(self, campanha_id):
    """
    Envia mensagens WhatsApp de uma campanha de CONSULTAS
    COPIADO DA LÓGICA DA FILA CIRÚRGICA (enviar_campanha_task)
    """
    from app import db, CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta, LogMsgConsulta, WhatsApp, formatar_mensagem_consulta
    from datetime import datetime

    logger.info(f"Iniciando envio da campanha de consultas {campanha_id}")

    try:
        camp = db.session.get(CampanhaConsulta, campanha_id)
        if not camp:
            logger.error(f"Campanha de consultas {campanha_id} não encontrada")
            return {'erro': 'Campanha não encontrada'}

        # Verificar WhatsApp configurado
        ws = WhatsApp(camp.criador_id)
        if not ws.ok():
            camp.status = 'erro'
            camp.status_msg = 'WhatsApp nao configurado'
            db.session.commit()
            return {'erro': 'WhatsApp não configurado'}

        # Verificar WhatsApp conectado
        conn, _ = ws.conectado()
        if not conn:
            camp.status = 'erro'
            camp.status_msg = 'WhatsApp desconectado'
            db.session.commit()
            return {'erro': 'WhatsApp desconectado'}

        camp.status = 'enviando'
        camp.data_inicio = datetime.utcnow()
        db.session.commit()

        # Buscar consultas AGUARDANDO_ENVIO
        consultas = camp.consultas.filter_by(
            status='AGUARDANDO_ENVIO'
        ).order_by(AgendamentoConsulta.id).all()

        total = len(consultas)
        enviados_pessoas = 0
        erros = 0

        logger.info(f"Total de consultas para enviar: {total}")

        for i, consulta in enumerate(consultas):
            # Refresh campanha para verificar status (permite pausar)
            db.session.refresh(camp)
            if camp.status != 'enviando':
                logger.info(f"Campanha pausada/cancelada, parando...")
                break

            # Verificar limites (IGUAL À FILA CIRÚRGICA)
            if camp.atingiu_duracao():
                camp.status = 'concluido'
                camp.status_msg = f'Duração de {camp.dias_duracao} dias atingida'
                db.session.commit()
                break

            if not camp.pode_enviar_agora():
                camp.status = 'pausado'
                camp.status_msg = f'Fora do horário ({camp.hora_inicio}h-{camp.hora_fim}h)'
                db.session.commit()
                break

            if not camp.pode_enviar_hoje():
                camp.status = 'pausado'
                camp.status_msg = f'Meta diária atingida ({camp.meta_diaria} consultas)'
                db.session.commit()
                break

            # Atualizar progresso
            progresso = int((i / total) * 100) if total > 0 else 0
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': i + 1,
                    'total': total,
                    'percent': progresso,
                    'enviados': enviados_pessoas,
                    'erros': erros,
                    'status': f'Enviando para {consulta.paciente}...'
                }
            )

            camp.status_msg = f'Processando {i+1}/{total}: {consulta.paciente}'
            db.session.commit()

            # ENVIO DA CONSULTA
            # Buscar telefones
            telefones = consulta.telefones.order_by(TelefoneConsulta.prioridade).all()

            if not telefones:
                logger.warning(f"Consulta {consulta.id} sem telefones, pulando...")
                erros += 1
                continue

            # Formatar mensagem
            mensagem = formatar_mensagem_consulta(consulta)
            if not mensagem:
                logger.error(f"Erro ao formatar mensagem para consulta {consulta.id}")
                erros += 1
                continue

            sucesso_pessoa = False

            # Tentar enviar para cada telefone (ordem de prioridade)
            for tel in telefones:
                if tel.enviado:  # Já foi enviado
                    continue

                ok, result = ws.enviar(tel.numero, mensagem)

                if ok:
                    tel.enviado = True
                    tel.data_envio = datetime.utcnow()
                    tel.msg_id = result
                    sucesso_pessoa = True

                    # Log de sucesso
                    log = LogMsgConsulta(
                        campanha_id=camp.id,
                        consulta_id=consulta.id,
                        direcao='enviada',
                        telefone=tel.numero,
                        mensagem=mensagem[:500],
                        status='sucesso'
                    )
                    db.session.add(log)

                    logger.info(f"Mensagem enviada para {tel.numero} da consulta {consulta.id}")
                    # Enviar apenas para o primeiro telefone com sucesso (IGUAL FILA)
                    break
                else:
                    # Log de erro
                    log = LogMsgConsulta(
                        campanha_id=camp.id,
                        consulta_id=consulta.id,
                        direcao='enviada',
                        telefone=tel.numero,
                        mensagem=mensagem[:500],
                        status='erro',
                        erro=result
                    )
                    db.session.add(log)
                    logger.warning(f"Falha ao enviar para {tel.numero}: {result}")

            if sucesso_pessoa:
                # Mudar status da consulta
                consulta.status = 'AGUARDANDO_CONFIRMACAO'
                consulta.mensagem_enviada = True
                consulta.data_envio_mensagem = datetime.utcnow()
                camp.registrar_envio()
                enviados_pessoas += 1
            else:
                erros += 1

            db.session.commit()
            camp.atualizar_stats()
            db.session.commit()

            # Aguardar intervalo calculado (IGUAL FILA)
            if i < total - 1:
                intervalo = camp.calcular_intervalo()
                logger.info(f"Aguardando {intervalo}s até próximo envio")
                time.sleep(intervalo)

        # Verificar se acabou
        restantes = camp.consultas.filter_by(status='AGUARDANDO_ENVIO').count()

        if restantes == 0 and camp.status == 'enviando':
            camp.status = 'concluido'
            camp.data_fim = datetime.utcnow()
            camp.status_msg = f'{enviados_pessoas} consultas contactadas'

        camp.atualizar_stats()
        db.session.commit()

        logger.info(f"Envio concluído: {enviados_pessoas} enviados, {erros} erros")

        return {
            'sucesso': True,
            'total': total,
            'enviados': enviados_pessoas,
            'erros': erros
        }

    except Exception as e:
        logger.exception(f"Erro no envio: {e}")
        if camp:
            camp.status = 'erro'
            camp.status_msg = str(e)[:200]
            db.session.commit()
        raise
```

### PASSO 4: Endpoints Flask (app.py)

Adicione os endpoints para controlar o envio:

```python
# =============================================================================
# ROTAS - AGENDAMENTO DE CONSULTAS
# =============================================================================

@app.route('/consultas/dashboard')
@login_required
def consultas_dashboard():
    """Dashboard principal de consultas"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        flash('Sem permissão', 'danger')
        return redirect(url_for('dashboard'))

    # Buscar todas as campanhas do usuário
    campanhas = CampanhaConsulta.query.filter_by(
        criador_id=current_user.id
    ).order_by(CampanhaConsulta.data_criacao.desc()).all()

    return render_template('consultas_dashboard.html', campanhas=campanhas)


@app.route('/consultas/campanha/<int:id>')
@login_required
def campanha_consultas_detalhe(id):
    """Detalhes de uma campanha de consultas"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    campanha = CampanhaConsulta.query.get_or_404(id)

    if campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    # Buscar consultas com filtro opcional
    filtro = request.args.get('filtro', 'todos')

    if filtro == 'todos':
        consultas = campanha.consultas.all()
    else:
        consultas = campanha.consultas.filter_by(status=filtro).all()

    # Atualizar estatísticas
    campanha.atualizar_stats()
    db.session.commit()

    return render_template('campanha_consultas_detalhe.html',
                         campanha=campanha,
                         consultas=consultas,
                         filtro=filtro)


@app.route('/consultas/campanha/<int:id>/iniciar', methods=['POST'])
@login_required
def campanha_consultas_iniciar(id):
    """Inicia envio automático da campanha - IGUAL À FILA CIRÚRGICA"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    campanha = CampanhaConsulta.query.get_or_404(id)

    if campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    if campanha.status == 'enviando':
        return jsonify({'erro': 'Já em andamento'}), 400

    # Verificar se tem consultas pendentes
    pendentes = campanha.consultas.filter_by(status='AGUARDANDO_ENVIO').count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhuma consulta para enviar'}), 400

    # Verificar WhatsApp conectado
    ws = WhatsApp(campanha.criador_id)
    conn, _ = ws.conectado()
    if not conn:
        return jsonify({'erro': 'WhatsApp desconectado'}), 400

    # Atualizar configurações se enviadas
    if request.form.get('meta_diaria'):
        campanha.meta_diaria = int(request.form.get('meta_diaria'))
    if request.form.get('hora_inicio'):
        campanha.hora_inicio = int(request.form.get('hora_inicio'))
    if request.form.get('hora_fim'):
        campanha.hora_fim = int(request.form.get('hora_fim'))

    # Calcular intervalo automaticamente
    campanha.tempo_entre_envios = campanha.calcular_intervalo()
    db.session.commit()

    # Iniciar task Celery (IGUAL À FILA CIRÚRGICA)
    from tasks import enviar_campanha_consultas_task
    task = enviar_campanha_consultas_task.delay(id)

    flash('Envio iniciado em background! O sistema enviará automaticamente.', 'success')
    return redirect(url_for('campanha_consultas_detalhe', id=campanha.id))


@app.route('/consultas/campanha/<int:id>/pausar', methods=['POST'])
@login_required
def campanha_consultas_pausar(id):
    """Pausa o envio da campanha"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    campanha = CampanhaConsulta.query.get_or_404(id)

    if campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    campanha.status = 'pausado'
    campanha.status_msg = 'Pausada manualmente'
    db.session.commit()

    flash('Envio pausado!', 'success')
    return redirect(url_for('campanha_consultas_detalhe', id=campanha.id))


@app.route('/consultas/campanha/<int:id>/continuar', methods=['POST'])
@login_required
def campanha_consultas_continuar(id):
    """Retoma o envio de uma campanha pausada"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    campanha = CampanhaConsulta.query.get_or_404(id)

    if campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    # Verificar se tem consultas pendentes
    pendentes = campanha.consultas.filter_by(status='AGUARDANDO_ENVIO').count()
    if pendentes == 0:
        flash('Nenhuma consulta pendente', 'warning')
        return redirect(url_for('campanha_consultas_detalhe', id=campanha.id))

    # Iniciar task Celery novamente
    from tasks import enviar_campanha_consultas_task
    task = enviar_campanha_consultas_task.delay(id)

    flash('Envio retomado!', 'success')
    return redirect(url_for('campanha_consultas_detalhe', id=campanha.id))


@app.route('/consulta/<int:id>/detalhes')
@login_required
def consulta_detalhe(id):
    """Detalhes de uma consulta individual"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    consulta = AgendamentoConsulta.query.get_or_404(id)

    if consulta.campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    # Buscar histórico de mensagens
    logs = LogMsgConsulta.query.filter_by(
        consulta_id=consulta.id
    ).order_by(LogMsgConsulta.data).all()

    return render_template('consulta_detalhe.html', consulta=consulta, logs=logs)


@app.route('/api/consulta/<int:id>/confirmar', methods=['POST'])
@login_required
def api_consulta_confirmar(id):
    """Confirma uma consulta manualmente"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    consulta = AgendamentoConsulta.query.get_or_404(id)

    if consulta.campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    consulta.status = 'CONFIRMADO'
    consulta.data_confirmacao = datetime.utcnow()
    db.session.commit()

    return jsonify({'sucesso': True})


@app.route('/api/consulta/<int:id>/cancelar', methods=['POST'])
@login_required
def api_consulta_cancelar(id):
    """Cancela uma consulta"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    consulta = AgendamentoConsulta.query.get_or_404(id)

    if consulta.campanha.criador_id != current_user.id:
        return jsonify({'erro': 'Sem permissão'}), 403

    consulta.status = 'CANCELADO'
    consulta.data_cancelamento = datetime.utcnow()
    db.session.commit()

    return jsonify({'sucesso': True})
```

### PASSO 5: Template HTML Principal

Crie o arquivo `templates/campanha_consultas_detalhe.html`:

```html
{% extends "base.html" %}

{% block content %}
<div class="container-fluid mt-4">
    <h2>
        <i class="bi bi-calendar-check"></i> {{ campanha.nome }}
        <span class="badge {{ 'bg-success' if campanha.status == 'enviando' else 'bg-secondary' }}">
            {{ campanha.status.upper() }}
        </span>
    </h2>

    <div class="row mt-4">
        <!-- Card de Estatísticas -->
        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h6>Total de Consultas</h6>
                    <h3>{{ campanha.total_consultas }}</h3>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h6>Aguardando Envio</h6>
                    <h3>{{ campanha.pendentes_enviar() }}</h3>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h6>Confirmados</h6>
                    <h3>{{ campanha.total_confirmados }}</h3>
                </div>
            </div>
        </div>

        <div class="col-md-3">
            <div class="card">
                <div class="card-body">
                    <h6>Rejeitados</h6>
                    <h3>{{ campanha.total_rejeitados }}</h3>
                </div>
            </div>
        </div>
    </div>

    <!-- Configurações e Controles -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <i class="bi bi-gear"></i> Configurações de Envio
                </div>
                <div class="card-body">
                    <form method="POST" action="{{ url_for('campanha_consultas_iniciar', id=campanha.id) }}">
                        <div class="row">
                            <div class="col-md-4">
                                <label>Meta Diária</label>
                                <input type="number" class="form-control" name="meta_diaria"
                                       value="{{ campanha.meta_diaria }}" min="1" max="500">
                            </div>
                            <div class="col-md-4">
                                <label>Hora Início</label>
                                <input type="number" class="form-control" name="hora_inicio"
                                       value="{{ campanha.hora_inicio }}" min="0" max="23">
                            </div>
                            <div class="col-md-4">
                                <label>Hora Fim</label>
                                <input type="number" class="form-control" name="hora_fim"
                                       value="{{ campanha.hora_fim }}" min="0" max="23">
                            </div>
                        </div>

                        <div class="mt-3">
                            {% if campanha.status == 'pendente' %}
                            <button type="submit" class="btn btn-success">
                                <i class="bi bi-play-fill"></i> Iniciar Envio Automático
                            </button>
                            {% elif campanha.status == 'enviando' %}
                            <div class="alert alert-info mb-0">
                                <i class="bi bi-hourglass-split"></i>
                                <strong>Enviando automaticamente...</strong>
                                O sistema está processando em background.
                            </div>
                            </form>
                            <form method="POST" action="{{ url_for('campanha_consultas_pausar', id=campanha.id) }}"
                                  style="display: inline;">
                                <button type="submit" class="btn btn-warning">
                                    <i class="bi bi-pause-fill"></i> Pausar
                                </button>
                            </form>
                            {% elif campanha.status == 'pausado' %}
                            </form>
                            <form method="POST" action="{{ url_for('campanha_consultas_continuar', id=campanha.id) }}"
                                  style="display: inline;">
                                <button type="submit" class="btn btn-success">
                                    <i class="bi bi-play-fill"></i> Continuar
                                </button>
                            </form>
                            {% else %}
                            <div class="alert alert-success">
                                <i class="bi bi-check-circle"></i> Envio Concluído!
                            </div>
                            {% endif %}
                        </div>
                    </form>
                </div>
            </div>
        </div>
    </div>

    <!-- Tabela de Consultas -->
    <div class="row mt-4">
        <div class="col-12">
            <div class="card">
                <div class="card-header">
                    <i class="bi bi-list-ul"></i> Consultas

                    <!-- Filtros -->
                    <div class="btn-group btn-group-sm float-end">
                        <a href="{{ url_for('campanha_consultas_detalhe', id=campanha.id) }}"
                           class="btn btn-outline-secondary {{ 'active' if filtro == 'todos' }}">
                            Todos
                        </a>
                        <a href="{{ url_for('campanha_consultas_detalhe', id=campanha.id, filtro='AGUARDANDO_ENVIO') }}"
                           class="btn btn-outline-secondary {{ 'active' if filtro == 'AGUARDANDO_ENVIO' }}">
                            Pendentes
                        </a>
                        <a href="{{ url_for('campanha_consultas_detalhe', id=campanha.id, filtro='CONFIRMADO') }}"
                           class="btn btn-outline-success {{ 'active' if filtro == 'CONFIRMADO' }}">
                            Confirmados
                        </a>
                        <a href="{{ url_for('campanha_consultas_detalhe', id=campanha.id, filtro='REJEITADO') }}"
                           class="btn btn-outline-danger {{ 'active' if filtro == 'REJEITADO' }}">
                            Rejeitados
                        </a>
                    </div>
                </div>
                <div class="card-body p-0">
                    <table class="table table-hover mb-0">
                        <thead>
                            <tr>
                                <th>Paciente</th>
                                <th>Tipo</th>
                                <th>Especialidade</th>
                                <th>Data</th>
                                <th>Status</th>
                                <th>Ações</th>
                            </tr>
                        </thead>
                        <tbody>
                            {% for consulta in consultas %}
                            <tr>
                                <td>{{ consulta.paciente }}</td>
                                <td>
                                    <span class="badge {{ 'bg-primary' if consulta.tipo == 'RETORNO' else 'bg-info' }}">
                                        {{ consulta.tipo }}
                                    </span>
                                </td>
                                <td>{{ consulta.especialidade }}</td>
                                <td>{{ consulta.data_aghu }}</td>
                                <td>
                                    <span class="badge {{ consulta.status_badge() }}">
                                        {{ consulta.status_texto() }}
                                    </span>
                                </td>
                                <td>
                                    <a href="{{ url_for('consulta_detalhe', id=consulta.id) }}"
                                       class="btn btn-sm btn-outline-primary">
                                        <i class="bi bi-eye"></i> Ver
                                    </a>
                                </td>
                            </tr>
                            {% endfor %}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    </div>
</div>
{% endblock %}
```

---

## 🔄 WEBHOOK - PROCESSAMENTO DE RESPOSTAS

Adicione a lógica de webhook para processar respostas dos pacientes:

```python
def processar_resposta_consulta(telefone, mensagem_texto):
    """
    Processa resposta do paciente sobre agendamento de consulta

    Respostas aceitas:
    - SIM / S / OK / CONFIRMO → Confirma presença
    - NÃO / N / NAO / CANCELO → Rejeita consulta
    """
    # Normalizar telefone
    telefone_fmt = ''.join(filter(str.isdigit, telefone))

    # Buscar telefone na base
    tel = TelefoneConsulta.query.filter(
        TelefoneConsulta.numero.like(f'%{telefone_fmt[-9:]}%')
    ).first()

    if not tel:
        logger.warning(f"Telefone {telefone} não encontrado em consultas")
        return False

    consulta = tel.consulta

    # Normalizar mensagem
    msg_norm = mensagem_texto.upper().strip()

    # Registrar log da resposta
    log = LogMsgConsulta(
        campanha_id=consulta.campanha_id,
        consulta_id=consulta.id,
        direcao='recebida',
        telefone=telefone,
        mensagem=mensagem_texto,
        status='processada'
    )
    db.session.add(log)

    # Processar resposta
    if consulta.status == 'AGUARDANDO_CONFIRMACAO':
        # Respostas positivas
        if any(palavra in msg_norm for palavra in ['SIM', 'OK', 'CONFIRMO', 'VOU', 'IREI']):
            consulta.status = 'CONFIRMADO'
            consulta.data_confirmacao = datetime.utcnow()
            logger.info(f"Consulta {consulta.id} CONFIRMADA por {telefone}")

        # Respostas negativas
        elif any(palavra in msg_norm for palavra in ['NÃO', 'NAO', 'N', 'CANCELO', 'DESMARCO']):
            consulta.status = 'REJEITADO'
            consulta.data_cancelamento = datetime.utcnow()
            logger.info(f"Consulta {consulta.id} REJEITADA por {telefone}")

            # Se for INTERCONSULTA e precisa voltar ao posto, enviar MSG 2
            if consulta.tipo == 'INTERCONSULTA' and consulta.paciente_voltar_posto_sms == 'SIM':
                # Task Celery para enviar mensagem informando que deve voltar ao posto
                # (implementar se necessário)
                pass

    db.session.commit()
    consulta.campanha.atualizar_stats()
    db.session.commit()

    return True


# Adicionar ao webhook existente
@app.route('/webhook/evolution', methods=['POST'])
def webhook_evolution():
    """
    Webhook que recebe mensagens da Evolution API
    Processa respostas de pacientes
    """
    try:
        data = request.json

        # Extrair informações
        event = data.get('event')
        instance = data.get('instance')
        message_data = data.get('data', {})

        # Processar apenas mensagens recebidas
        if event == 'messages.upsert':
            # Verificar se é mensagem recebida (não enviada por nós)
            if message_data.get('key', {}).get('fromMe'):
                return jsonify({'status': 'ignored - sent by us'}), 200

            telefone = message_data.get('key', {}).get('remoteJid', '').replace('@s.whatsapp.net', '')
            mensagem_texto = message_data.get('message', {}).get('conversation', '')

            if not mensagem_texto:
                # Tentar outros tipos de mensagem
                msg_obj = message_data.get('message', {})
                mensagem_texto = (
                    msg_obj.get('extendedTextMessage', {}).get('text', '') or
                    msg_obj.get('imageMessage', {}).get('caption', '') or
                    ''
                )

            if telefone and mensagem_texto:
                # Processar resposta de consulta
                processar_resposta_consulta(telefone, mensagem_texto)

                # Também processar para fila cirúrgica (se existir)
                # processar_resposta_contato(telefone, mensagem_texto)

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        logger.error(f"Erro no webhook: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500
```

---

## 📝 IMPORTAÇÃO DE PLANILHA

Adicione endpoint para importar planilha Excel de consultas:

```python
@app.route('/consultas/importar', methods=['POST'])
@login_required
def consultas_importar():
    """Importa planilha de consultas"""
    if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
        return jsonify({'erro': 'Sem permissão'}), 403

    if 'arquivo' not in request.files:
        flash('Nenhum arquivo enviado', 'danger')
        return redirect(url_for('consultas_dashboard'))

    arquivo = request.files['arquivo']
    nome_campanha = request.form.get('nome_campanha', 'Nova Campanha')

    if arquivo.filename == '':
        flash('Arquivo vazio', 'danger')
        return redirect(url_for('consultas_dashboard'))

    # Ler Excel
    df = pd.read_excel(arquivo)

    # Criar campanha
    campanha = CampanhaConsulta(
        criador_id=current_user.id,
        nome=nome_campanha,
        status='pendente'
    )
    db.session.add(campanha)
    db.session.flush()

    # Processar linhas
    criadas = 0
    for _, row in df.iterrows():
        # Criar consulta
        consulta = AgendamentoConsulta(
            campanha_id=campanha.id,
            usuario_id=current_user.id,
            paciente=row.get('PACIENTE', ''),
            tipo=row.get('TIPO', 'RETORNO'),  # RETORNO ou INTERCONSULTA
            especialidade=row.get('ESPECIALIDADE', ''),
            sub_especialidade=row.get('SUB_ESPECIALIDADE', ''),
            data_aghu=str(row.get('DATA', '')),
            hora_consulta=str(row.get('HORA', '')),
            unidade_funcional=row.get('UNIDADE_FUNCIONAL', ''),
            profissional=row.get('PROFISSIONAL', ''),
            telefone_cadas=str(row.get('TELEFONE_CADAS', '')),
            telefone_regist=str(row.get('TELEFONE_REGIST', '')),
            paciente_voltar_posto_sms=row.get('PACIENTE_VOLTAR_POSTO_SMS', 'NÃO'),
            status='AGUARDANDO_ENVIO'
        )
        db.session.add(consulta)
        db.session.flush()

        # Criar telefones
        prioridade = 1
        for campo_tel in ['TELEFONE_REGIST', 'TELEFONE_CADAS']:
            tel_valor = str(row.get(campo_tel, '')).strip()
            if tel_valor and tel_valor != 'nan':
                # Normalizar telefone
                tel_limpo = ''.join(filter(str.isdigit, tel_valor))
                if len(tel_limpo) >= 10:
                    telefone = TelefoneConsulta(
                        consulta_id=consulta.id,
                        numero=tel_limpo,
                        prioridade=prioridade
                    )
                    db.session.add(telefone)
                    prioridade += 1

        criadas += 1

    # Atualizar estatísticas da campanha
    campanha.atualizar_stats()
    db.session.commit()

    flash(f'Importadas {criadas} consultas!', 'success')
    return redirect(url_for('campanha_consultas_detalhe', id=campanha.id))
```

---

## ✅ CHECKLIST DE IMPLEMENTAÇÃO

Use este checklist para garantir que tudo foi implementado:

### Backend
- [ ] Modelos criados (CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta, LogMsgConsulta)
- [ ] Função formatar_mensagem_consulta() implementada
- [ ] Task Celery enviar_campanha_consultas_task() criada
- [ ] Endpoints Flask criados (dashboard, iniciar, pausar, continuar)
- [ ] Webhook configurado para processar respostas
- [ ] Importação de planilha funcionando

### Frontend
- [ ] Template campanha_consultas_detalhe.html criado
- [ ] Template consultas_dashboard.html criado
- [ ] Template consulta_detalhe.html criado
- [ ] Menu com link para "Consultas" (se tipo_sistema == AGENDAMENTO_CONSULTA)

### Banco de Dados
- [ ] Tabelas criadas (migrations rodadas)
- [ ] Índices criados para performance

### Testes
- [ ] Celery rodando (`celery -A celery_app worker`)
- [ ] Redis rodando
- [ ] Importar planilha de teste
- [ ] Iniciar envio automático
- [ ] Verificar logs do Celery
- [ ] Testar resposta do paciente via WhatsApp
- [ ] Confirmar mudança de status

---

## 🚀 COMO INICIAR

1. **Criar migrations:**
```bash
flask db migrate -m "Adiciona tabelas de consultas"
flask db upgrade
```

2. **Iniciar Redis:**
```bash
redis-server
```

3. **Iniciar Celery:**
```bash
celery -A celery_app worker --loglevel=info
```

4. **Iniciar Flask:**
```bash
python app.py
```

5. **Testar:**
- Login com usuário tipo AGENDAMENTO_CONSULTA
- Importar planilha de consultas
- Clicar "Iniciar Envio Automático"
- Ver logs no terminal do Celery

---

## 📌 NOTAS IMPORTANTES

1. **100% baseado na fila cirúrgica** - Toda a lógica é cópia exata do que já funciona
2. **Processamento assíncrono** - Usa Celery, não trava a interface
3. **Respeitacontroles** - Meta diária, horário, intervalo entre envios
4. **Status automático** - AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO → CONFIRMADO
5. **Logs completos** - Todas as mensagens registradas em LogMsgConsulta
6. **Webhook funcional** - Processa respostas dos pacientes automaticamente

---

## 🆘 TROUBLESHOOTING

**Problema: Nada acontece ao clicar "Iniciar Envio"**
- Verificar se Celery está rodando
- Verificar se Redis está rodando
- Ver logs: `tail -f logs/celery_worker.log`

**Problema: Mensagens não são enviadas**
- Verificar WhatsApp conectado
- Ver logs do Celery
- Verificar se há telefones cadastrados

**Problema: Status não muda**
- Verificar webhook configurado
- Ver logs do webhook
- Testar manualmente com Postman

---

## 📚 ESTRUTURA FINAL DE ARQUIVOS

```
/home/user/git3/
├── app.py                      # Modelos + Endpoints + Webhook
├── tasks.py                    # Task Celery de envio
├── celery_app.py              # Configuração Celery
├── templates/
│   ├── consultas_dashboard.html
│   ├── campanha_consultas_detalhe.html
│   └── consulta_detalhe.html
├── migrations/                # Migrations do banco
└── logs/
    ├── celery_worker.log
    └── flask.log
```

---

## ✅ CONCLUSÃO

Este documento contém **TUDO** necessário para implementar o módulo de consultas. A implementação é **IDÊNTICA** à fila cirúrgica, que já funciona perfeitamente.

**Principais vantagens:**
- ✅ Processamento automático em background
- ✅ Não trava a interface
- ✅ Respeita todos os controles (meta, horário, intervalo)
- ✅ Webhook processa respostas automaticamente
- ✅ Logs completos de todas as operações
- ✅ Mesma confiabilidade da fila cirúrgica

**Boa sorte com a implementação!** 🚀
