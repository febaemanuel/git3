"""Consulta (agendamento) models and helper lookups."""

from datetime import datetime

from app.extensions import db
from app.services.timezone import (
    obter_agora_fortaleza,
    obter_hora_fortaleza,
    obter_hoje_fortaleza,
)


class CampanhaConsulta(db.Model):
    """Campanha de agendamento de consultas - separado da fila cirúrgica"""
    __tablename__ = 'campanhas_consultas'
    id = db.Column(db.Integer, primary_key=True)
    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
    nome = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    status = db.Column(db.String(50), default='pendente')  # pendente, enviando, pausado, concluido, erro
    status_msg = db.Column(db.String(255))

    # Configurações de envio (mesmas da fila cirúrgica)
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
    total_rejeitados = db.Column(db.Integer, default=0)

    # Timestamps
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_inicio = db.Column(db.DateTime)
    data_fim = db.Column(db.DateTime)

    # Task ID do Celery
    celery_task_id = db.Column(db.String(100))

    # Relationships
    criador = db.relationship('Usuario', backref='campanhas_consultas')

    def pode_enviar_hoje(self):
        """Verifica se pode enviar mais mensagens hoje (meta diária) - timezone Fortaleza"""
        hoje = obter_hoje_fortaleza()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 0
            self.data_ultimo_envio = hoje
            db.session.commit()
        return self.enviados_hoje < self.meta_diaria

    def pode_enviar_agora(self):
        """Verifica se está dentro do horário de funcionamento (timezone Fortaleza)"""
        hora_atual = obter_hora_fortaleza()

        # Verificar horário
        if self.hora_inicio <= self.hora_fim:
            # Horário normal (ex: 8h às 18h)
            dentro_horario = self.hora_inicio <= hora_atual < self.hora_fim
        else:
            # Horário overnight (ex: 22h às 6h)
            dentro_horario = hora_atual >= self.hora_inicio or hora_atual < self.hora_fim

        return dentro_horario

    def calcular_intervalo(self):
        """Calcula intervalo entre envios baseado na meta diária e horário de funcionamento"""
        # Validação da meta
        if self.meta_diaria <= 0:
            return self.tempo_entre_envios

        # Calcular horas disponíveis
        if self.hora_inicio <= self.hora_fim:
            # Horário normal (ex: 8h às 18h)
            horas_trabalho = self.hora_fim - self.hora_inicio
        else:
            # Horário overnight (ex: 22h às 6h)
            horas_trabalho = (24 - self.hora_inicio) + self.hora_fim

        if horas_trabalho <= 0:
            return self.tempo_entre_envios

        # Converter para segundos
        segundos_disponiveis = horas_trabalho * 3600

        # Calcular intervalo
        intervalo = segundos_disponiveis / self.meta_diaria

        # Garantir mínimo de 5 segundos (evitar flood)
        intervalo = max(5, int(intervalo))

        return intervalo

    def atualizar_stats(self):
        """Atualiza estatísticas da campanha"""
        self.total_consultas = AgendamentoConsulta.query.filter_by(campanha_id=self.id).count()
        self.total_enviados = AgendamentoConsulta.query.filter_by(campanha_id=self.id, mensagem_enviada=True).count()
        self.total_confirmados = AgendamentoConsulta.query.filter_by(campanha_id=self.id, status='CONFIRMADO').count()
        self.total_aguardando_comprovante = AgendamentoConsulta.query.filter_by(campanha_id=self.id, status='AGUARDANDO_COMPROVANTE').count()
        self.total_rejeitados = AgendamentoConsulta.query.filter_by(campanha_id=self.id, status='REJEITADO').count()

    def atingiu_duracao(self):
        """Verifica se atingiu o número de dias definido (timezone Fortaleza)"""
        if self.dias_duracao == 0:
            return False  # Até acabar

        if not self.data_inicio:
            return False

        dias_decorridos = (obter_agora_fortaleza().replace(tzinfo=None) - self.data_inicio).days
        return dias_decorridos >= self.dias_duracao

    def registrar_envio(self):
        """Registra que um envio foi realizado hoje (timezone Fortaleza)"""
        hoje = obter_hoje_fortaleza()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 1
            self.data_ultimo_envio = hoje
        else:
            self.enviados_hoje += 1
        db.session.commit()

    def pct_envio(self):
        """Percentual de consultas enviadas"""
        return round((self.total_enviados / self.total_consultas * 100), 1) if self.total_consultas else 0

    def pct_confirmacao(self):
        """Percentual de consultas confirmadas"""
        return round((self.total_confirmados / self.total_enviados * 100), 1) if self.total_enviados else 0

    def percentual_conclusao(self):
        """Percentual de conclusão total"""
        return round((self.total_enviados / self.total_consultas * 100), 1) if self.total_consultas else 0

    def pendentes_enviar(self):
        """Consultas pendentes de envio"""
        return AgendamentoConsulta.query.filter_by(campanha_id=self.id, status='AGUARDANDO_ENVIO').count()

    # Aliases para compatibilidade com templates
    percentual_envio = pct_envio
    percentual_confirmacao = pct_confirmacao


class AgendamentoConsulta(db.Model):
    """Agendamento individual de consulta com dados da planilha"""
    __tablename__ = 'agendamentos_consultas'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas_consultas.id', ondelete='CASCADE'))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Dados da planilha (TODAS as colunas)
    posicao = db.Column(db.String(50))
    cod_master = db.Column(db.String(50))
    codigo_aghu = db.Column(db.String(50))
    paciente = db.Column(db.String(200), nullable=False)
    telefone_cadastro = db.Column(db.String(200))  # Pode conter múltiplos telefones separados por /
    telefone_registro = db.Column(db.String(200))  # Pode conter múltiplos telefones separados por /
    data_registro = db.Column(db.String(50))
    procedencia = db.Column(db.String(200))
    medico_solicitante = db.Column(db.String(200))
    tipo = db.Column(db.String(50), nullable=False)  # RETORNO ou INTERCONSULTA
    observacoes = db.Column(db.Text)
    exames = db.Column(db.Text)
    sub_especialidade = db.Column(db.String(200))
    especialidade = db.Column(db.String(200))
    grade_aghu = db.Column(db.String(50))
    prioridade = db.Column(db.String(50))
    indicacao_data = db.Column(db.String(50))
    data_requisicao = db.Column(db.String(50))
    data_exata_ou_dias = db.Column(db.String(50))
    estimativa_agendamento = db.Column(db.String(50))
    data_aghu = db.Column(db.String(50))  # Data da consulta

    # Campo específico para INTERCONSULTA
    paciente_voltar_posto_sms = db.Column(db.String(10))  # SIM ou NÃO

    # Campos específicos para REMARCACAO
    motivo_remarcacao = db.Column(db.String(200))  # Motivo da remarcação (atestado, férias, etc.)
    data_anterior = db.Column(db.String(50))  # Data anterior da consulta (antes da remarcação)

    # Controle de tentativas de contato (retry logic)
    tentativas_contato = db.Column(db.Integer, default=0)  # Número de tentativas de contato
    data_ultima_tentativa = db.Column(db.DateTime)  # Data da última tentativa de contato
    cancelado_sem_resposta = db.Column(db.Boolean, default=False)  # Cancelado por falta de resposta

    # Controle de status do fluxo
    status = db.Column(db.String(50), default='AGUARDANDO_ENVIO')
    # Fluxo: AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO → AGUARDANDO_COMPROVANTE → CONFIRMADO
    #                                                   → AGUARDANDO_OPCAO_REJEICAO → AGUARDANDO_MOTIVO_REJEICAO → REJEITADO
    #                                                                               → AGUARDANDO_REAGENDAMENTO → REAGENDADO

    mensagem_enviada = db.Column(db.Boolean, default=False)
    data_envio_mensagem = db.Column(db.DateTime)

    # Comprovante (PDF/JPG)
    comprovante_path = db.Column(db.String(255))
    comprovante_nome = db.Column(db.String(255))

    # Telefone que confirmou (para enviar comprovante ao número certo)
    telefone_confirmacao = db.Column(db.String(20))  # Armazena qual telefone respondeu SIM


    # Rejeição
    motivo_rejeicao = db.Column(db.Text)  # Armazena o motivo quando paciente rejeita

    # Reagendamento
    data_reagendamento = db.Column(db.DateTime)  # Quando foi reagendado
    nova_data = db.Column(db.String(50))         # Nova data da consulta
    nova_hora = db.Column(db.String(20))         # Nova hora da consulta

    # Timestamps
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    data_confirmacao = db.Column(db.DateTime)
    data_rejeicao = db.Column(db.DateTime)

    # Pesquisa de satisfação - controle de etapa
    etapa_pesquisa = db.Column(db.String(30))  # NOTA, ATENDIMENTO, COMENTARIO, CONCLUIDA, PULOU

    # Relationships
    campanha = db.relationship('CampanhaConsulta', backref='agendamentos')
    usuario = db.relationship('Usuario', backref='agendamentos_consultas')


class TelefoneConsulta(db.Model):
    """Telefones de cada consulta (cadastro e registro)"""
    __tablename__ = 'telefones_consultas'
    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='CASCADE'))
    numero = db.Column(db.String(20), nullable=False)
    prioridade = db.Column(db.Integer, default=1)  # 1 = telefone_cadastro, 2 = telefone_registro
    enviado = db.Column(db.Boolean, default=False)
    data_envio = db.Column(db.DateTime)
    msg_id = db.Column(db.String(100))  # ID da mensagem na Evolution API
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Status do telefone
    invalido = db.Column(db.Boolean, default=False)  # True se número inválido (erro de envio)
    nao_pertence = db.Column(db.Boolean, default=False)  # True se respondeu "DESCONHEÇO" (opção 3)
    erro_envio = db.Column(db.String(200))  # Mensagem de erro do envio

    # Relationships
    consulta = db.relationship('AgendamentoConsulta', backref='telefones')


class LogMsgConsulta(db.Model):
    """Log de todas as mensagens enviadas e recebidas nas campanhas de consultas"""
    __tablename__ = 'logs_msgs_consultas'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas_consultas.id', ondelete='CASCADE'))
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='CASCADE'))
    direcao = db.Column(db.String(20), nullable=False)  # 'enviada' ou 'recebida'
    telefone = db.Column(db.String(20), nullable=False)
    mensagem = db.Column(db.Text)
    status = db.Column(db.String(20))  # 'sucesso' ou 'erro'
    erro = db.Column(db.Text)
    msg_id = db.Column(db.String(100))  # ID da mensagem na Evolution API
    data = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    campanha = db.relationship('CampanhaConsulta', backref='logs_msgs')
    consulta = db.relationship('AgendamentoConsulta', backref='logs_msgs')


class PesquisaSatisfacao(db.Model):
    """Pesquisa de satisfação respondida via WhatsApp"""
    __tablename__ = 'pesquisas_satisfacao'
    id = db.Column(db.Integer, primary_key=True)
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='CASCADE'))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Respostas
    nota_satisfacao = db.Column(db.Integer)       # 1-10
    equipe_atenciosa = db.Column(db.Boolean)      # True/False
    comentario = db.Column(db.Text)               # Texto livre

    # Dados automáticos (da consulta)
    tipo_agendamento = db.Column(db.String(50))   # RETORNO/INTERCONSULTA
    especialidade = db.Column(db.String(100))     # Puxado da consulta

    # Metadados
    data_resposta = db.Column(db.DateTime, default=datetime.utcnow)
    pulou = db.Column(db.Boolean, default=False)  # Se pulou a pesquisa

    # Relationships
    consulta = db.relationship('AgendamentoConsulta', backref='pesquisa_satisfacao')
    usuario = db.relationship('Usuario', backref='pesquisas_satisfacao')


class Paciente(db.Model):
    """Cadastro de pacientes para histórico de consultas"""
    __tablename__ = 'pacientes'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Dados do paciente (extraídos do comprovante)
    nome = db.Column(db.String(200), nullable=False)
    data_nascimento = db.Column(db.String(20))
    prontuario = db.Column(db.String(50))
    codigo = db.Column(db.String(50))
    telefone = db.Column(db.String(20))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # Relationships
    usuario = db.relationship('Usuario', backref='pacientes')


class ComprovanteAntecipado(db.Model):
    """Comprovante pré-carregado na campanha para envio automático quando paciente confirmar"""
    __tablename__ = 'comprovantes_antecipados'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas_consultas.id', ondelete='CASCADE'), nullable=False)
    nome_paciente = db.Column(db.String(200), nullable=False)   # extraído do nome do arquivo
    filename = db.Column(db.String(255), nullable=False)        # nome do arquivo no disco
    filepath = db.Column(db.String(500), nullable=False)        # caminho completo no servidor
    usado = db.Column(db.Boolean, default=False)                # True após ser enviado
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='SET NULL'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=True)
    data_upload = db.Column(db.DateTime, default=datetime.utcnow)

    campanha = db.relationship('CampanhaConsulta', backref='comprovantes_antecipados')
    consulta = db.relationship('AgendamentoConsulta', backref='comprovante_antecipado', uselist=False)
    usuario = db.relationship('Usuario', backref='comprovantes_antecipados_upload')


def normalizar_nome_paciente(nome):
    """Normaliza nome de paciente para matching: remove acentos, lowercase, colapsa espaços."""
    import unicodedata
    nome = unicodedata.normalize('NFKD', nome or '')
    nome = nome.encode('ascii', 'ignore').decode('ascii')
    return ' '.join(nome.lower().split())


def buscar_comprovante_antecipado(campanha_id, nome_paciente):
    """Busca comprovante antecipado não usado com nome matching na campanha."""
    nome_normalizado = normalizar_nome_paciente(nome_paciente)
    candidatos = ComprovanteAntecipado.query.filter_by(
        campanha_id=campanha_id, usado=False
    ).all()
    for c in candidatos:
        if normalizar_nome_paciente(c.nome_paciente) == nome_normalizado:
            return c
    return None


class HistoricoConsulta(db.Model):
    """Histórico de consultas do paciente (dados do comprovante OCR)"""
    __tablename__ = 'historico_consultas'
    id = db.Column(db.Integer, primary_key=True)
    paciente_id = db.Column(db.Integer, db.ForeignKey('pacientes.id', ondelete='CASCADE'))
    consulta_id = db.Column(db.Integer, db.ForeignKey('agendamentos_consultas.id', ondelete='SET NULL'))
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    # Dados do comprovante (OCR)
    nro_consulta = db.Column(db.String(50))
    data_consulta = db.Column(db.String(20))
    hora_consulta = db.Column(db.String(10))
    dia_semana = db.Column(db.String(10))
    grade = db.Column(db.String(50))
    unidade_funcional = db.Column(db.String(200))
    andar = db.Column(db.String(10))
    ala_bloco = db.Column(db.String(50))
    setor = db.Column(db.String(50))
    sala = db.Column(db.String(10))
    tipo_consulta = db.Column(db.String(100))  # S ANESTESIOLOG, etc
    tipo_demanda = db.Column(db.String(100))   # SUS/DEMANDA ESPONTANEA/RETORNO
    equipe = db.Column(db.String(100))
    profissional = db.Column(db.String(200))   # Médico
    especialidade = db.Column(db.String(100))
    exames = db.Column(db.Text)  # Nome do exame (da planilha)
    marcado_por = db.Column(db.String(100))
    observacao = db.Column(db.Text)
    nro_autorizacao = db.Column(db.String(50))

    # Status
    status = db.Column(db.String(50), default='CONFIRMADA')  # CONFIRMADA, CANCELADA, REAGENDADA, FALTOU

    # Comprovante
    comprovante_path = db.Column(db.String(255))

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    paciente = db.relationship('Paciente', backref='historico')
    consulta = db.relationship('AgendamentoConsulta', backref='historico')
    usuario = db.relationship('Usuario', backref='historico_consultas')
