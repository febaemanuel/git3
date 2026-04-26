"""Modelos do módulo GERAL (pesquisas/enquetes/envios)."""

from datetime import datetime

from app.extensions import db
from app.main import obter_hora_fortaleza, obter_hoje_fortaleza


class ConfigUsuarioGeral(db.Model):
    """Preferências configuradas via wizard pelo usuário do tipo GERAL.

    Onda 1: só armazena o que o usuário escolheu no wizard. Nenhuma rotina
    de envio consome essas preferências ainda — isso entra na Onda 2.
    """
    __tablename__ = 'config_usuario_geral'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), unique=True, nullable=False)

    # Multi-select: lista JSON de strings em {'CONFIRMACAO','PESQUISA','ENQUETE'}
    tipos_uso = db.Column(db.Text)

    # Um único valor: 'WHATSAPP_LINK_EXTERNO' | 'WHATSAPP_INTERATIVO' | 'LINK_INTERNO'
    canal_resposta = db.Column(db.String(40))

    wizard_concluido = db.Column(db.Boolean, default=False, nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_atualizacao = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    usuario = db.relationship('Usuario', backref=db.backref('config_geral', uselist=False))

    def tipos_uso_lista(self):
        import json
        try:
            return json.loads(self.tipos_uso) if self.tipos_uso else []
        except (ValueError, TypeError):
            return []

    def set_tipos_uso(self, lista):
        import json
        self.tipos_uso = json.dumps(list(lista or []))


# Tipos de pergunta suportados na pesquisa do tipo GERAL.
TIPOS_PERGUNTA = ['TEXTO_CURTO', 'TEXTO_LONGO', 'SIM_NAO', 'MULTI_ESCOLHA', 'ESCALA_1_10']


class Pesquisa(db.Model):
    """Pesquisa/enquete avulsa criada por um usuário GERAL."""
    __tablename__ = 'pesquisas'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)

    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    # Texto que o usuário pode copiar pra mandar pelo WhatsApp manualmente.
    mensagem_whatsapp = db.Column(db.Text)

    # Token público que aparece em /p/<token>. URL-safe, fixo por pesquisa.
    token_publico = db.Column(db.String(40), unique=True, nullable=False, index=True)

    ativa = db.Column(db.Boolean, default=True, nullable=False)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario', backref='pesquisas_geral')
    perguntas = db.relationship(
        'PerguntaPesquisa',
        backref='pesquisa',
        cascade='all, delete-orphan',
        order_by='PerguntaPesquisa.ordem',
    )
    respostas = db.relationship(
        'RespostaPesquisa',
        backref='pesquisa',
        cascade='all, delete-orphan',
    )

    @staticmethod
    def gerar_token():
        import secrets
        return secrets.token_urlsafe(12)


class PerguntaPesquisa(db.Model):
    __tablename__ = 'perguntas_pesquisa'
    id = db.Column(db.Integer, primary_key=True)
    pesquisa_id = db.Column(db.Integer, db.ForeignKey('pesquisas.id', ondelete='CASCADE'), nullable=False, index=True)
    ordem = db.Column(db.Integer, default=0, nullable=False)
    texto = db.Column(db.String(500), nullable=False)
    tipo = db.Column(db.String(30), nullable=False, default='TEXTO_CURTO')
    # JSON com lista de opções (só usado em MULTI_ESCOLHA).
    opcoes = db.Column(db.Text)
    obrigatoria = db.Column(db.Boolean, default=True, nullable=False)

    def opcoes_lista(self):
        import json
        try:
            return json.loads(self.opcoes) if self.opcoes else []
        except (ValueError, TypeError):
            return []

    def set_opcoes(self, lista):
        import json
        self.opcoes = json.dumps(list(lista or []))


class RespostaPesquisa(db.Model):
    """Cada submissão do formulário público gera uma RespostaPesquisa."""
    __tablename__ = 'respostas_pesquisa'
    id = db.Column(db.Integer, primary_key=True)
    pesquisa_id = db.Column(db.Integer, db.ForeignKey('pesquisas.id', ondelete='CASCADE'), nullable=False, index=True)
    iniciada_em = db.Column(db.DateTime, default=datetime.utcnow)
    concluida_em = db.Column(db.DateTime)
    ip_origem = db.Column(db.String(45))
    user_agent = db.Column(db.String(255))

    itens = db.relationship(
        'RespostaItem',
        backref='resposta',
        cascade='all, delete-orphan',
    )


class RespostaItem(db.Model):
    __tablename__ = 'respostas_itens'
    id = db.Column(db.Integer, primary_key=True)
    resposta_id = db.Column(db.Integer, db.ForeignKey('respostas_pesquisa.id', ondelete='CASCADE'), nullable=False, index=True)
    pergunta_id = db.Column(db.Integer, db.ForeignKey('perguntas_pesquisa.id', ondelete='CASCADE'), nullable=False, index=True)
    # Para MULTI_ESCOLHA, valor é JSON com lista de opções selecionadas.
    valor = db.Column(db.Text)

    pergunta = db.relationship('PerguntaPesquisa')

    def valor_lista(self):
        import json
        try:
            return json.loads(self.valor) if self.valor else []
        except (ValueError, TypeError):
            return []


# Status possíveis para um lote de envio em massa do link da pesquisa.
STATUS_ENVIO_PESQUISA = ['pendente', 'enviando', 'pausado', 'concluido', 'erro']
STATUS_ENVIO_TELEFONE = ['pendente', 'enviado', 'falhou']


# Templates de pesquisa pré-configurados. Cada chave vira a URL do template.
# Cada item descreve título, descrição, mensagem padrão e a lista de perguntas
# a serem criadas automaticamente. Pensado para casos reais (ex.: SCIH/MEAC).
TEMPLATES_PESQUISA = {
    'busca_fonada_cesarea': {
        'titulo': 'Busca fonada pós-cesárea',
        'descricao': 'Questionário do Serviço de Controle de Infecção Hospitalar para '
                     'identificar sinais de infecção em pacientes pós-cesárea.',
        'mensagem_whatsapp': (
            'Prezada paciente, esperamos que esta mensagem a encontre bem. '
            'Estamos entrando em contato do Serviço de Controle de Infecção '
            'Hospitalar para realizar um breve questionário a respeito da sua '
            'experiência pós-cirúrgica, buscando identificar possíveis sinais '
            'de infecções relacionadas à sua cirurgia. Sua participação é '
            'muito importante! Agradecemos sua atenção!\n\n'
            'Clique no link abaixo e responda:\n{LINK}'
        ),
        'perguntas': [
            {'texto': 'Nome completo', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Idade', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Dia da ligação', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Qual o dia da sua cesárea?', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Você apresentou algum sintoma após a cirurgia?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {
                'texto': 'Quais sintomas você apresentou? (pode marcar mais de um)',
                'tipo': 'MULTI_ESCOLHA',
                'obrigatoria': False,
                'opcoes': [
                    'febre',
                    'ferida cirúrgica avermelhada',
                    'ferida cirúrgica inchada',
                    'ferida cirúrgica com dor',
                    'ferida cirúrgica com secreção',
                    'ferida cirúrgica com pus',
                    'ferida cirúrgica com sangramento',
                    'ferida cirúrgica com mau cheiro',
                ],
            },
            {'texto': 'Você buscou atendimento médico?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {'texto': 'Você utilizou algum remédio?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {'texto': 'Qual remédio?', 'tipo': 'TEXTO_CURTO', 'obrigatoria': False},
            {'texto': 'Observações', 'tipo': 'TEXTO_LONGO', 'obrigatoria': False},
        ],
    },
    'busca_fonada_mastologia': {
        'titulo': 'Busca fonada pós-mastologia',
        'descricao': 'Questionário do Serviço de Controle de Infecção Hospitalar para '
                     'identificar sinais de infecção em pacientes pós-mastologia.',
        'mensagem_whatsapp': (
            'Prezada paciente, esperamos que esta mensagem a encontre bem. '
            'Estamos entrando em contato do Serviço de Controle de Infecção '
            'Hospitalar para realizar um breve questionário a respeito da sua '
            'experiência pós-cirúrgica, buscando identificar possíveis sinais '
            'de infecções relacionadas à sua cirurgia. Sua participação é '
            'muito importante! Agradecemos sua atenção!\n\n'
            'Clique no link abaixo e responda:\n{LINK}'
        ),
        'perguntas': [
            {'texto': 'Nome completo', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Idade', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Dia da ligação', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Qual o dia da sua mastologia?', 'tipo': 'TEXTO_CURTO', 'obrigatoria': True},
            {'texto': 'Você apresentou algum sintoma após a cirurgia?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {
                'texto': 'Quais sintomas você apresentou? (pode marcar mais de um)',
                'tipo': 'MULTI_ESCOLHA',
                'obrigatoria': False,
                'opcoes': [
                    'febre',
                    'ferida cirúrgica avermelhada',
                    'ferida cirúrgica inchada',
                    'ferida cirúrgica com dor',
                    'ferida cirúrgica com secreção',
                    'ferida cirúrgica com pus',
                    'ferida cirúrgica com sangramento',
                    'ferida cirúrgica com mau cheiro',
                ],
            },
            {'texto': 'Você buscou atendimento médico?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {'texto': 'Você utilizou algum remédio?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {'texto': 'Qual remédio?', 'tipo': 'TEXTO_CURTO', 'obrigatoria': False},
            {'texto': 'Observações', 'tipo': 'TEXTO_LONGO', 'obrigatoria': False},
        ],
    },
    'satisfacao_simples': {
        'titulo': 'Pesquisa de satisfação',
        'descricao': 'Pesquisa rápida de satisfação com nota e comentário livre.',
        'mensagem_whatsapp': (
            'Olá! Por favor, ajude-nos a melhorar respondendo a esta pesquisa rápida:\n{LINK}\n'
            'Leva menos de 1 minuto. Obrigado!'
        ),
        'perguntas': [
            {'texto': 'De 1 a 10, qual sua satisfação com o atendimento?', 'tipo': 'ESCALA_1_10', 'obrigatoria': True},
            {'texto': 'A equipe foi atenciosa?', 'tipo': 'SIM_NAO', 'obrigatoria': True},
            {'texto': 'Comentários ou sugestões', 'tipo': 'TEXTO_LONGO', 'obrigatoria': False},
        ],
    },
}


class EnvioPesquisa(db.Model):
    """Lote de envio em massa do link da pesquisa via WhatsApp.

    Um EnvioPesquisa = uma "campanha" simples: o usuário cola lista de
    telefones, define intervalo/horário/meta diária e o sistema dispara
    a mensagem (com o link público) para cada um. Sem retry, sem chat
    de volta — é uma única mensagem por destinatário.
    """
    __tablename__ = 'envios_pesquisa'
    id = db.Column(db.Integer, primary_key=True)
    pesquisa_id = db.Column(db.Integer, db.ForeignKey('pesquisas.id', ondelete='CASCADE'), nullable=False, index=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, index=True)

    nome = db.Column(db.String(120))  # rótulo do lote, ex.: "Cesáreas semana 17/04"
    mensagem_template = db.Column(db.Text, nullable=False)  # texto que vai pra cada paciente

    # Configurações de envio (mesmos defaults dos outros sistemas).
    intervalo_segundos = db.Column(db.Integer, default=60, nullable=False)
    hora_inicio = db.Column(db.Integer, default=8, nullable=False)
    hora_fim = db.Column(db.Integer, default=18, nullable=False)
    meta_diaria = db.Column(db.Integer, default=50, nullable=False)
    enviados_hoje = db.Column(db.Integer, default=0, nullable=False)
    data_ultimo_envio = db.Column(db.Date)

    status = db.Column(db.String(20), default='pendente', nullable=False)
    status_msg = db.Column(db.String(200))

    total = db.Column(db.Integer, default=0, nullable=False)
    enviados = db.Column(db.Integer, default=0, nullable=False)
    falhas = db.Column(db.Integer, default=0, nullable=False)

    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    data_inicio = db.Column(db.DateTime)
    data_fim = db.Column(db.DateTime)
    celery_task_id = db.Column(db.String(100))

    pesquisa = db.relationship('Pesquisa', backref='envios')
    usuario = db.relationship('Usuario')
    telefones = db.relationship(
        'EnvioPesquisaTelefone',
        backref='envio',
        cascade='all, delete-orphan',
    )

    def pode_enviar_agora(self):
        # Reusa fuso de Fortaleza pra consistência com Campanha/CampanhaConsulta.
        hora_atual = obter_hora_fortaleza()
        if self.hora_inicio <= self.hora_fim:
            return self.hora_inicio <= hora_atual < self.hora_fim
        return hora_atual >= self.hora_inicio or hora_atual < self.hora_fim

    def pode_enviar_hoje(self):
        hoje = obter_hoje_fortaleza()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 0
            self.data_ultimo_envio = hoje
        return self.enviados_hoje < self.meta_diaria

    def registrar_envio(self):
        hoje = obter_hoje_fortaleza()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 0
            self.data_ultimo_envio = hoje
        self.enviados_hoje += 1


class EnvioPesquisaTelefone(db.Model):
    __tablename__ = 'envios_pesquisa_telefones'
    id = db.Column(db.Integer, primary_key=True)
    envio_id = db.Column(db.Integer, db.ForeignKey('envios_pesquisa.id', ondelete='CASCADE'), nullable=False, index=True)
    numero = db.Column(db.String(20), nullable=False)
    nome = db.Column(db.String(120))
    status = db.Column(db.String(20), default='pendente', nullable=False)
    erro = db.Column(db.String(300))
    data_envio = db.Column(db.DateTime)
