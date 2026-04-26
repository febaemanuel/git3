"""Fila cirúrgica (busca ativa) models: Campanha, Contato, Telefone, LogMsg
plus the related ticket / retry / config tables."""

from datetime import date, datetime, timedelta

from app.extensions import db
from app.main import (
    obter_agora_fortaleza,
    obter_hora_fortaleza,
    obter_hoje_fortaleza,
)


class Campanha(db.Model):
    __tablename__ = 'campanhas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    mensagem = db.Column(db.Text, nullable=False)
    arquivo = db.Column(db.String(255))

    status = db.Column(db.String(50), default='pendente')
    status_msg = db.Column(db.String(255))
    task_id = db.Column(db.String(100))  # ID da task Celery para polling de progresso

    # Estatisticas (Baseadas em PESSOAS/CONTATOS)
    total_contatos = db.Column(db.Integer, default=0)  # Total de pessoas
    total_numeros = db.Column(db.Integer, default=0)   # Total de telefones

    total_validos = db.Column(db.Integer, default=0)   # Pessoas com pelo menos 1 zap valido
    total_invalidos = db.Column(db.Integer, default=0) # Pessoas sem nenhum zap valido

    total_enviados = db.Column(db.Integer, default=0)  # Pessoas contactadas com sucesso
    total_confirmados = db.Column(db.Integer, default=0)
    total_rejeitados = db.Column(db.Integer, default=0)
    total_erros = db.Column(db.Integer, default=0)

    limite_diario = db.Column(db.Integer, default=50)
    tempo_entre_envios = db.Column(db.Integer, default=15)

    # Campos de agendamento avançado
    meta_diaria = db.Column(db.Integer, default=50)  # Meta de pessoas por dia
    hora_inicio = db.Column(db.Integer, default=8)   # Hora de início (0-23)
    hora_fim = db.Column(db.Integer, default=18)     # Hora de fim (0-23)
    dias_duracao = db.Column(db.Integer, default=0)  # 0 = até acabar, >0 = quantidade de dias

    # Controle diário
    enviados_hoje = db.Column(db.Integer, default=0)
    data_ultimo_envio = db.Column(db.Date)

    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'))
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_inicio = db.Column(db.DateTime)
    data_fim = db.Column(db.DateTime)

    criador = db.relationship('Usuario', backref='campanhas')
    contatos = db.relationship('Contato', backref='campanha', lazy='dynamic', cascade='all, delete-orphan')

    def atualizar_stats(self):
        self.total_contatos = self.contatos.count()

        # Contar numeros
        self.total_numeros = Telefone.query.join(Contato).filter(Contato.campanha_id == self.id).count()

        # Pessoas validas: tem pelo menos 1 telefone valido
        self.total_validos = self.contatos.join(Telefone).filter(Telefone.whatsapp_valido == True).distinct().count()

        # Pessoas invalidas: todos os telefones sao invalidos (ou nao tem telefone)
        # Simplificacao: Total - Validos (pode nao ser exato se nao foi validado ainda, mas serve)
        # Melhor: Pessoas que ja foram validadas e nao tem nenhum valido
        # Por enquanto vamos usar a logica simples de status do contato se tiver

        # Contar pessoas enviadas (todos os status que indicam que a pessoa foi contactada)
        self.total_enviados = self.contatos.filter(
            Contato.status.in_(['enviado', 'aguardando_nascimento', 'aguardando_motivo_rejeicao', 'concluido'])
        ).count()
        self.total_confirmados = self.contatos.filter_by(confirmado=True).count()
        self.total_rejeitados = self.contatos.filter_by(rejeitado=True).count()
        self.total_erros = self.contatos.filter(Contato.erro.isnot(None)).count()

    def pct_validacao(self):
        return round((self.total_validos / self.total_contatos * 100), 1) if self.total_contatos else 0

    def pct_envio(self):
        return round((self.total_enviados / self.total_validos * 100), 1) if self.total_validos else 0

    def pct_confirmacao(self):
        return round((self.total_confirmados / self.total_enviados * 100), 1) if self.total_enviados else 0

    def percentual_conclusao(self):
        return round((self.total_enviados / self.total_contatos * 100), 1) if self.total_contatos else 0

    # Aliases para compatibilidade template
    percentual_validacao = pct_validacao
    percentual_envio = pct_envio
    percentual_confirmacao = pct_confirmacao

    def pendentes_validar(self):
        # Contar telefones pendentes de validacao
        return Telefone.query.join(Contato).filter(Contato.campanha_id == self.id, Telefone.whatsapp_valido == None).count()

    def pendentes_enviar(self):
        # Pessoas validas que ainda nao foram enviadas
        return self.contatos.join(Telefone).filter(Telefone.whatsapp_valido == True, Contato.status == 'pendente').distinct().count()

    def pode_enviar_hoje(self):
        """Verifica se ainda pode enviar hoje baseado na meta diária"""
        hoje = date.today()

        # Se mudou o dia, resetar contador
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 0
            self.data_ultimo_envio = hoje
            db.session.commit()

        # Verificar se atingiu a meta
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

    def atingiu_duracao(self):
        """Verifica se atingiu o número de dias definido"""
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

    def calcular_intervalo(self):
        """
        Calcula automaticamente o intervalo entre envios baseado em:
        - Horário de trabalho (hora_inicio até hora_fim)
        - Meta diária de envios

        Retorna: intervalo em segundos

        Exemplo:
        - Horário: 8h às 18h = 10 horas = 36000 segundos
        - Meta: 100 pessoas/dia
        - Intervalo: 36000 / 100 = 360 segundos (6 minutos)
        """
        if self.meta_diaria <= 0:
            return 15  # Padrão: 15 segundos se meta inválida

        # Calcular horas disponíveis
        if self.hora_inicio <= self.hora_fim:
            horas_trabalho = self.hora_fim - self.hora_inicio
        else:
            # Horário overnight (ex: 22h às 6h)
            horas_trabalho = (24 - self.hora_inicio) + self.hora_fim

        # Converter para segundos
        segundos_disponiveis = horas_trabalho * 3600

        # Calcular intervalo
        intervalo = segundos_disponiveis / self.meta_diaria

        # Garantir mínimo de 5 segundos (evitar flood)
        intervalo = max(5, int(intervalo))

        return intervalo


class Contato(db.Model):
    __tablename__ = 'contatos'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id', ondelete='CASCADE'), nullable=False)

    nome = db.Column(db.String(200), nullable=False)
    data_nascimento = db.Column(db.Date) # NOVO
    procedimento = db.Column(db.String(500))  # Termo original da planilha
    procedimento_normalizado = db.Column(db.String(300))  # Termo normalizado pela IA

    # Status do contato/pessoa
    status = db.Column(db.String(50), default='pendente') # pendente, validando, pronto_envio, enviado, respondido, concluido, erro

    confirmado = db.Column(db.Boolean, default=False)
    rejeitado = db.Column(db.Boolean, default=False)
    resposta = db.Column(db.Text)
    data_resposta = db.Column(db.DateTime)
    motivo_rejeicao = db.Column(db.Text)
    data_rejeicao = db.Column(db.DateTime)

    erro = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    # Controle de tentativas de recontato (retry automático)
    tentativas_contato = db.Column(db.Integer, default=0)
    data_ultima_tentativa = db.Column(db.DateTime)

    telefones = db.relationship('Telefone', backref='contato', lazy='dynamic', cascade='all, delete-orphan')

    def telefones_str(self):
        return ", ".join([t.numero_fmt for t in self.telefones])

    def formatar_telefone(self):
        nums = []
        for t in self.telefones:
            n = t.numero_fmt
            if n and len(n) >= 12 and n.startswith('55'):
                ddd = n[2:4]
                rest = n[4:]
                if len(rest) == 9:
                    nums.append(f'({ddd}) {rest[:5]}-{rest[5:]}')
                elif len(rest) == 8:
                    nums.append(f'({ddd}) {rest[:4]}-{rest[4:]}')
                else:
                    nums.append(n)
            else:
                nums.append(t.numero if t.numero else (t.numero_fmt or ''))
        return ", ".join(nums)

    @property
    def resposta_texto(self):
        return self.resposta

    def status_texto(self):
        if self.erro: return f'Erro: {self.erro}'
        if self.confirmado: return 'CONFIRMADO'
        if self.rejeitado: return 'REJEITADO'
        if self.status == 'enviado': return 'Aguardando resposta'
        if self.status == 'pronto_envio': return 'Pronto para envio'
        if self.status == 'aguardando_motivo_rejeicao': return 'Aguardando motivo'
        if self.status == 'sem_resposta': return 'Sem resposta'
        return self.status

    def status_badge(self):
        if self.erro: return 'bg-danger'
        if self.confirmado: return 'bg-success'
        if self.rejeitado: return 'bg-warning text-dark'
        if self.status == 'enviado': return 'bg-info'
        if self.status == 'pronto_envio': return 'bg-primary'
        if self.status == 'aguardando_motivo_rejeicao': return 'bg-warning text-dark'
        if self.status == 'sem_resposta': return 'bg-secondary'
        return 'bg-light text-dark'

    def calcular_status_final(self):
        """
        Calcula o status final baseado em todas as respostas dos telefones.
        Hierarquia: CONFIRMADO > REJEITADO > DESCONHEÇO > PENDENTE

        Regra: Se QUALQUER número confirmou, status final é CONFIRMADO.
        "Desconheço" não é considerado conflito.
        """
        telefones = list(self.telefones.all())

        # Conta cada tipo de resposta
        tem_confirmado = any(t.tipo_resposta == 'confirmado' for t in telefones)
        tem_rejeitado = any(t.tipo_resposta == 'rejeitado' for t in telefones)
        tem_desconheco = any(t.tipo_resposta == 'desconheco' for t in telefones)

        # Se qualquer número confirmou, status final é CONFIRMADO
        if tem_confirmado:
            self.confirmado = True
            self.rejeitado = False
            if self.status not in ['erro']:
                self.status = 'concluido'
        # Se nenhum confirmou mas algum rejeitou, status é REJEITADO
        elif tem_rejeitado:
            self.confirmado = False
            self.rejeitado = True
            if self.status not in ['erro']:
                self.status = 'concluido'
        # Se só tem "desconheço", mantém como não confirmado/rejeitado
        elif tem_desconheco:
            self.confirmado = False
            self.rejeitado = False
            if self.status not in ['erro']:
                self.status = 'concluido'
        # Se nenhuma resposta, mantém pendente
        else:
            self.confirmado = False
            self.rejeitado = False

        # Atualiza os campos legados de resposta para compatibilidade
        respostas_com_data = [t for t in telefones if t.data_resposta]
        if respostas_com_data:
            ultima = max(respostas_com_data, key=lambda t: t.data_resposta)
            self.resposta = ultima.resposta
            self.data_resposta = ultima.data_resposta

    def obter_respostas_detalhadas(self):
        """
        Retorna informações detalhadas de todas as respostas recebidas.
        """
        resultado = []
        for telefone in self.telefones.all():
            info = {
                'numero': telefone.numero,
                'numero_fmt': telefone.numero_fmt,
                'prioridade': telefone.prioridade,
                'resposta': telefone.resposta,
                'data_resposta': telefone.data_resposta,
                'tipo_resposta': telefone.tipo_resposta,
                'validacao_pendente': telefone.validacao_pendente
            }
            resultado.append(info)

        # Ordena por prioridade (menor = mais importante)
        resultado.sort(key=lambda x: x['prioridade'])
        return resultado

    def tem_respostas_multiplas(self):
        """Verifica se há múltiplas respostas de telefones diferentes."""
        respostas = [t for t in self.telefones.all() if t.tipo_resposta]
        return len(respostas) > 1

    def tem_conflito_real(self):
        """
        Verifica se há conflito REAL entre respostas.
        "Desconheço" não é considerado conflito.
        Conflito = ter CONFIRMADO e REJEITADO ao mesmo tempo.
        """
        telefones = list(self.telefones.all())
        tem_confirmado = any(t.tipo_resposta == 'confirmado' for t in telefones)
        tem_rejeitado = any(t.tipo_resposta == 'rejeitado' for t in telefones)

        # Conflito real apenas se tem confirmado E rejeitado simultaneamente
        return tem_confirmado and tem_rejeitado

    # Métodos para badges/alertas na lista
    def tem_mensagens_recentes(self):
        """Verifica se tem mensagens recebidas nas últimas 24h"""
        limite = datetime.utcnow() - timedelta(hours=24)
        return LogMsg.query.filter(
            LogMsg.contato_id == self.id,
            LogMsg.direcao == 'recebida',
            LogMsg.data >= limite
        ).first() is not None

    def sentimento_recente(self):
        """Retorna sentimento da mensagem mais recente (se houver)"""
        msg = LogMsg.query.filter_by(
            contato_id=self.id,
            direcao='recebida'
        ).order_by(LogMsg.data.desc()).first()

        if msg and msg.sentimento:
            return msg.sentimento
        return None


class Telefone(db.Model):
    __tablename__ = 'telefones'
    id = db.Column(db.Integer, primary_key=True)
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id', ondelete='CASCADE'), nullable=False)

    numero = db.Column(db.String(20), nullable=False)
    numero_fmt = db.Column(db.String(20)) # 558599999999

    whatsapp_valido = db.Column(db.Boolean, default=None)
    jid = db.Column(db.String(50))
    data_validacao = db.Column(db.DateTime)

    enviado = db.Column(db.Boolean, default=False)
    data_envio = db.Column(db.DateTime)
    msg_id = db.Column(db.String(100))

    # Status do telefone
    invalido = db.Column(db.Boolean, default=False)  # True se número inválido (erro de envio)
    erro_envio = db.Column(db.String(200))            # Mensagem de erro do envio

    # Response tracking per phone number
    resposta = db.Column(db.Text)
    data_resposta = db.Column(db.DateTime)
    tipo_resposta = db.Column(db.String(20))  # 'confirmado', 'rejeitado', 'desconheco', null
    validacao_pendente = db.Column(db.Boolean, default=False)  # waiting for birth date validation

    nao_pertence = db.Column(db.Boolean, default=False)  # Número não pertence ao paciente (DESCONHEÇO)

    prioridade = db.Column(db.Integer, default=1) # 1 = principal


class LogMsg(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id', ondelete='CASCADE'))
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id', ondelete='CASCADE'))
    direcao = db.Column(db.String(10))
    telefone = db.Column(db.String(20))
    mensagem = db.Column(db.Text)
    status = db.Column(db.String(20))
    erro = db.Column(db.Text)
    sentimento = db.Column(db.String(20))
    sentimento_score = db.Column(db.Float)
    data = db.Column(db.DateTime, default=datetime.utcnow)


class TicketAtendimento(db.Model):
    __tablename__ = 'tickets_atendimento'
    id = db.Column(db.Integer, primary_key=True)
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id', ondelete='CASCADE'))
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id', ondelete='CASCADE'))
    mensagem_usuario = db.Column(db.Text)
    status = db.Column(db.String(20), default='pendente')  # pendente, em_atendimento, resolvido, cancelado
    prioridade = db.Column(db.String(20), default='media')  # baixa, media, alta, urgente
    atendente_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'))
    notas_atendente = db.Column(db.Text)
    resposta = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_atendimento = db.Column(db.DateTime)
    data_resolucao = db.Column(db.DateTime)

    contato = db.relationship('Contato', backref='tickets')
    campanha = db.relationship('Campanha', backref='tickets')
    atendente = db.relationship('Usuario', backref='tickets_atendidos')


class TentativaContato(db.Model):
    __tablename__ = 'tentativas_contato'
    id = db.Column(db.Integer, primary_key=True)
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id', ondelete='CASCADE'))
    numero_tentativa = db.Column(db.Integer)
    data_tentativa = db.Column(db.DateTime, default=datetime.utcnow)
    proxima_tentativa = db.Column(db.DateTime)
    status = db.Column(db.String(20))  # agendada, enviada, respondida, cancelada
    mensagem_enviada = db.Column(db.Text)

    contato = db.relationship('Contato', backref='tentativas')


class ConfigTentativas(db.Model):
    __tablename__ = 'config_tentativas'
    id = db.Column(db.Integer, primary_key=True)
    max_tentativas = db.Column(db.Integer, default=3)
    intervalo_dias = db.Column(db.Integer, default=3)
    ativo = db.Column(db.Boolean, default=False)

    @classmethod
    def get(cls):
        c = cls.query.first()
        if not c:
            c = cls()
            db.session.add(c)
            db.session.commit()
        return c
