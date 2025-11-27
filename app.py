"""
=============================================================================
BUSCA ATIVA DE PACIENTES - HUWC/CHUFC
Sistema Completo para Envio de Mensagens WhatsApp
=============================================================================

Funcionalidades:
- Upload de planilha Excel com contatos
- Verificacao de numeros no WhatsApp (Evolution API)
- Envio automatizado de mensagens personalizadas
- Recepcao de respostas via webhook
- Dashboard com estatisticas em tempo real
- Exportacao de relatorios Excel
- Historico de mensagens
- Controle de limite diario

Usuario Admin Padrao:
- Email: admin@huwc.com
- Senha: admin123

Versao: 2.0
"""

from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta, date
import pandas as pd
import os
import threading
import time
import logging
import requests
import json
from io import BytesIO

# Carregar variaveis de ambiente do .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# =============================================================================
# CONFIGURACAO
# =============================================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('busca_ativa.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'busca-ativa-huwc-2024-secret')

# Database - PostgreSQL (padrao) ou SQLite (fallback)
DATABASE_URL = os.environ.get('DATABASE_URL', '')
if DATABASE_URL:
    # PostgreSQL
    app.config['SQLALCHEMY_DATABASE_URI'] = DATABASE_URL
else:
    # Fallback para SQLite (desenvolvimento)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///busca_ativa.db'

app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {'pool_pre_ping': True}
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(__file__), 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faca login para acessar.'
login_manager.login_message_category = 'warning'

# Constantes
ADMIN_EMAIL = 'admin@huwc.com'
ADMIN_SENHA = 'admin123'
ADMIN_NOME = 'Administrador'

RESPOSTAS_SIM = ['SIM', 'S', '1', 'CONFIRMO', 'QUERO', 'TENHO', 'CLARO', 'POSITIVO', 'TENHO INTERESSE']
RESPOSTAS_NAO = ['NAO', 'NÃO', 'N', '2', 'DESISTO', 'CANCELA', 'NEGATIVO', 'NAO QUERO', 'NAO TENHO']
RESPOSTAS_DESCONHECO = ['3', 'DESCONHECO', 'DESCONHEÇO', 'NAO SOU', 'ENGANO', 'ERRADO']

MENSAGEM_PADRAO = """📋 *Olá, {nome}*!

Aqui é da *Central de Agendamentos do Hospital Universitário Walter Cantídio*.

Consta em nossos registros que você está na lista de espera para o procedimento: *{procedimento}*.

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa

_Por favor, responda com o número da opção._
"""


# =============================================================================
# MODELOS
# =============================================================================

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    senha_hash = db.Column(db.String(255), nullable=False)
    ativo = db.Column(db.Boolean, default=True)
    is_admin = db.Column(db.Boolean, default=False)  # Flag de administrador
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_acesso = db.Column(db.DateTime)

    def set_password(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)


class ConfigGlobal(db.Model):
    """Configurações globais da Evolution API (definidas pelo admin)"""
    __tablename__ = 'config_global'
    id = db.Column(db.Integer, primary_key=True)
    evolution_api_url = db.Column(db.String(200))  # Ex: https://api.evolution.com
    evolution_api_key = db.Column(db.String(200))  # Global API key
    ativo = db.Column(db.Boolean, default=False)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_por = db.Column(db.Integer, db.ForeignKey('usuarios.id'))

    @classmethod
    def get(cls):
        """Obtém ou cria configuração global"""
        c = cls.query.first()
        if not c:
            c = cls()
            db.session.add(c)
            db.session.commit()
        return c


class ConfigWhatsApp(db.Model):
    """Configuração de instância WhatsApp por usuário (criada automaticamente)"""
    __tablename__ = 'config_whatsapp'
    id = db.Column(db.Integer, primary_key=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'), nullable=False, unique=True)
    instance_name = db.Column(db.String(100))  # Gerado automaticamente: hospital_user_{id}
    conectado = db.Column(db.Boolean, default=False)  # Status da conexão
    tempo_entre_envios = db.Column(db.Integer, default=15)
    limite_diario = db.Column(db.Integer, default=100)
    data_conexao = db.Column(db.DateTime)  # Quando conectou pela última vez
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)

    usuario = db.relationship('Usuario', backref='config_whatsapp_obj')

    @classmethod
    def get(cls, usuario_id):
        """Obtém ou cria config para um usuário específico"""
        c = cls.query.filter_by(usuario_id=usuario_id).first()
        if not c:
            # Gerar instance_name automaticamente
            instance_name = f"hospital_user_{usuario_id}"
            c = cls(usuario_id=usuario_id, instance_name=instance_name)
            db.session.add(c)
            db.session.commit()
        return c


class Campanha(db.Model):
    __tablename__ = 'campanhas'
    id = db.Column(db.Integer, primary_key=True)
    nome = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    mensagem = db.Column(db.Text, nullable=False)
    arquivo = db.Column(db.String(255))

    status = db.Column(db.String(50), default='pendente')
    status_msg = db.Column(db.String(255))

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

    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
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
            Contato.status.in_(['enviado', 'aguardando_nascimento', 'concluido'])
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
        """Verifica se está dentro do horário de funcionamento"""
        agora = datetime.now()
        hora_atual = agora.hour

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

        dias_decorridos = (datetime.now() - self.data_inicio).days
        return dias_decorridos >= self.dias_duracao

    def registrar_envio(self):
        """Registra que um envio foi realizado hoje"""
        hoje = date.today()
        if self.data_ultimo_envio != hoje:
            self.enviados_hoje = 1
            self.data_ultimo_envio = hoje
        else:
            self.enviados_hoje += 1
        db.session.commit()


class Contato(db.Model):
    __tablename__ = 'contatos'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id'), nullable=False)

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

    erro = db.Column(db.Text)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    
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
        return self.status

    def status_badge(self):
        if self.erro: return 'bg-danger'
        if self.confirmado: return 'bg-success'
        if self.rejeitado: return 'bg-warning text-dark'
        if self.status == 'enviado': return 'bg-info'
        if self.status == 'pronto_envio': return 'bg-primary'
        return 'bg-light text-dark'


class Telefone(db.Model):
    __tablename__ = 'telefones'
    id = db.Column(db.Integer, primary_key=True)
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id'), nullable=False)
    
    numero = db.Column(db.String(20), nullable=False)
    numero_fmt = db.Column(db.String(20)) # 558599999999
    
    whatsapp_valido = db.Column(db.Boolean, default=None)
    jid = db.Column(db.String(50))
    data_validacao = db.Column(db.DateTime)
    
    enviado = db.Column(db.Boolean, default=False)
    data_envio = db.Column(db.DateTime)
    msg_id = db.Column(db.String(100))
    
    prioridade = db.Column(db.Integer, default=1) # 1 = principal


class LogMsg(db.Model):
    __tablename__ = 'logs'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id'))
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id'))
    direcao = db.Column(db.String(10))
    telefone = db.Column(db.String(20))
    mensagem = db.Column(db.Text)
    status = db.Column(db.String(20))
    erro = db.Column(db.Text)
    sentimento = db.Column(db.String(20))
    sentimento_score = db.Column(db.Float)
    data = db.Column(db.DateTime, default=datetime.utcnow)


class RespostaAutomatica(db.Model):
    __tablename__ = 'respostas_automaticas'
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50), nullable=False)
    gatilhos = db.Column(db.Text)  # JSON string com lista de palavras
    resposta = db.Column(db.Text, nullable=False)
    ativa = db.Column(db.Boolean, default=True)
    prioridade = db.Column(db.Integer, default=1)
    contador_uso = db.Column(db.Integer, default=0)
    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))  # NOVO - FAQ privado do usuário
    global_faq = db.Column(db.Boolean, default=False)  # NOVO - FAQ global (apenas admin)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

    criador = db.relationship('Usuario', backref='faqs_criados')

    def get_gatilhos(self):
        try:
            return json.loads(self.gatilhos) if self.gatilhos else []
        except:
            return []

    def set_gatilhos(self, lista):
        self.gatilhos = json.dumps(lista, ensure_ascii=False)


class TicketAtendimento(db.Model):
    __tablename__ = 'tickets_atendimento'
    id = db.Column(db.Integer, primary_key=True)
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id'))
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id'))
    mensagem_usuario = db.Column(db.Text)
    status = db.Column(db.String(20), default='pendente')  # pendente, em_atendimento, resolvido, cancelado
    prioridade = db.Column(db.String(20), default='media')  # baixa, media, alta, urgente
    atendente_id = db.Column(db.Integer, db.ForeignKey('usuarios.id'))
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
    contato_id = db.Column(db.Integer, db.ForeignKey('contatos.id'))
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


class Tutorial(db.Model):
    __tablename__ = 'tutoriais'
    id = db.Column(db.Integer, primary_key=True)
    titulo = db.Column(db.String(200), nullable=False)
    descricao = db.Column(db.Text)
    conteudo = db.Column(db.Text)  # HTML ou Markdown
    ordem = db.Column(db.Integer, default=0)
    categoria = db.Column(db.String(50))  # inicio, campanhas, configuracoes, atendimento
    ativo = db.Column(db.Boolean, default=True)
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)


class ProcedimentoNormalizado(db.Model):
    """Cache de procedimentos médicos normalizados pela IA"""
    __tablename__ = 'procedimentos_normalizados'
    id = db.Column(db.Integer, primary_key=True)
    termo_original = db.Column(db.String(300), unique=True, index=True, nullable=False)  # Ex: "COLPOPERINEOPLASTIA ANTERIOR E POSTERIOR"
    termo_normalizado = db.Column(db.String(300))  # Ex: "Cirurgia de correção íntima"
    termo_simples = db.Column(db.String(200))  # Ex: "Cirurgia ginecológica"
    explicacao = db.Column(db.Text)  # Explicação breve do procedimento
    criado_em = db.Column(db.DateTime, default=datetime.utcnow)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    usado_count = db.Column(db.Integer, default=0)  # Contador de uso
    aprovado = db.Column(db.Boolean, default=True)  # Admin pode reprovar
    fonte = db.Column(db.String(50), default='deepseek')  # deepseek, manual, etc

    def incrementar_uso(self):
        """Incrementa contador de uso"""
        self.usado_count += 1
        db.session.commit()

    @classmethod
    def obter_ou_criar(cls, termo_original):
        """Busca no cache ou retorna None se não existir"""
        return cls.query.filter_by(termo_original=termo_original.upper().strip()).first()

    @classmethod
    def salvar_normalizacao(cls, termo_original, termo_normalizado, termo_simples, explicacao, fonte='deepseek'):
        """Salva uma normalização no cache"""
        proc = cls(
            termo_original=termo_original.upper().strip(),
            termo_normalizado=termo_normalizado,
            termo_simples=termo_simples,
            explicacao=explicacao,
            fonte=fonte
        )
        db.session.add(proc)
        db.session.commit()
        return proc


# =============================================================================
# CLASSES AUXILIARES - FAQ E ANALISE DE SENTIMENTO
# =============================================================================

class AnaliseSentimento:
    """Analise de sentimento simples baseada em palavras-chave"""

    POSITIVO = ['obrigado', 'obrigada', 'agradeço', 'agradeco', 'perfeito', 'ótimo',
                'otimo', 'excelente', 'maravilha', 'sim', 'confirmo', 'quero', 'bom', 'boa']

    NEGATIVO = ['não', 'nao', 'nunca', 'desisto', 'cancelar', 'problema',
                'ruim', 'horrível', 'horrible', 'demora', 'demorado', 'péssimo', 'pessimo']

    URGENTE = ['urgente', 'emergência', 'emergencia', 'rápido', 'rapido',
               'agora', 'hoje', 'imediato', 'socorro', 'ajuda', 'dor', 'grave']

    INSATISFACAO = ['reclamar', 'reclamação', 'reclamacao', 'absurdo', 'ridículo', 'ridiculo',
                    'descaso', 'demora', 'espera', 'meses', 'anos', 'revoltante']

    DUVIDA = ['?', 'como', 'quando', 'onde', 'qual', 'dúvida', 'duvida',
              'não entendi', 'nao entendi', 'explica', 'explicar']

    @classmethod
    def analisar(cls, texto):
        texto_lower = texto.lower()
        score = 0
        categorias = []

        # Contar ocorrências
        positivos = sum(1 for p in cls.POSITIVO if p in texto_lower)
        negativos = sum(1 for p in cls.NEGATIVO if p in texto_lower)
        urgentes = sum(1 for p in cls.URGENTE if p in texto_lower)
        insatisfeitos = sum(1 for p in cls.INSATISFACAO if p in texto_lower)
        duvidas = sum(1 for p in cls.DUVIDA if p in texto_lower)

        score = positivos - negativos + (urgentes * 2) - (insatisfeitos * 2)

        if urgentes > 0:
            categorias.append('urgente')
        if insatisfeitos > 0:
            categorias.append('insatisfeito')
        if duvidas > 0:
            categorias.append('duvida')
        if positivos > negativos:
            categorias.append('positivo')
        elif negativos > positivos:
            categorias.append('negativo')

        # Mensagem muito longa (provavelmente complexa)
        if len(texto) > 200:
            categorias.append('complexo')

        # Classificação final
        if 'urgente' in categorias:
            sentimento = 'urgente'
        elif 'insatisfeito' in categorias:
            sentimento = 'insatisfeito'
        elif 'duvida' in categorias:
            sentimento = 'duvida'
        elif 'positivo' in categorias:
            sentimento = 'positivo'
        elif 'negativo' in categorias:
            sentimento = 'negativo'
        else:
            sentimento = 'neutro'

        return {
            'sentimento': sentimento,
            'score': score,
            'categorias': categorias,
            'requer_atencao': sentimento in ['urgente', 'insatisfeito', 'complexo']
        }


class SistemaFAQ:
    """Sistema de respostas automáticas"""

    @staticmethod
    def buscar_resposta(texto, usuario_id=None):
        """Busca resposta automática baseada no texto

        Busca em:
        1. FAQs globais (global_faq=True)
        2. FAQs privados do usuário (criador_id=usuario_id)
        """
        texto_lower = texto.lower()

        # Buscar FAQs globais + FAQs do usuário
        query = RespostaAutomatica.query.filter_by(ativa=True)

        if usuario_id:
            # FAQs globais OU FAQs do usuário
            query = query.filter(
                db.or_(
                    RespostaAutomatica.global_faq == True,
                    RespostaAutomatica.criador_id == usuario_id
                )
            )
        else:
            # Apenas FAQs globais (fallback se não tiver usuário)
            query = query.filter_by(global_faq=True)

        faqs = query.order_by(RespostaAutomatica.prioridade.desc()).all()

        for faq in faqs:
            gatilhos = faq.get_gatilhos()
            for gatilho in gatilhos:
                if gatilho.lower() in texto_lower:
                    # Incrementar contador
                    faq.contador_uso += 1
                    db.session.commit()
                    return faq.resposta

        return None

    @staticmethod
    def requer_atendimento_humano(texto, contato):
        """Verifica se a mensagem requer atendimento humano"""
        texto_lower = texto.lower()

        # Análise de sentimento
        analise = AnaliseSentimento.analisar(texto)

        if analise['requer_atencao']:
            if analise['sentimento'] == 'urgente':
                return 'urgente'
            elif analise['sentimento'] == 'insatisfeito':
                return 'alta'
            else:
                return 'media'

        # Mensagem muito longa
        if len(texto) > 200:
            return 'media'

        # Múltiplas mensagens em curto período
        if contato:
            msgs_recentes = LogMsg.query.filter_by(
                contato_id=contato.id,
                direcao='recebida'
            ).filter(
                LogMsg.data > datetime.utcnow() - timedelta(hours=1)
            ).count()

            if msgs_recentes > 3:
                return 'alta'

        return None


# =============================================================================
# SERVICO DEEPSEEK AI - NORMALIZAÇÃO DE PROCEDIMENTOS
# =============================================================================

class DeepSeekAI:
    """Cliente para normalização de procedimentos médicos usando DeepSeek API"""

    def __init__(self):
        self.base_url = os.getenv('AI_API_BASE_URL', 'https://api.deepseek.com').rstrip('/')
        self.api_key = os.getenv('AI_API_KEY', '')
        self.timeout = int(os.getenv('AI_API_TIMEOUT', '30'))
        self.model = os.getenv('AI_API_MODEL', 'deepseek-chat')

    def _esta_configurado(self):
        """Verifica se a API está configurada"""
        return bool(self.api_key and self.base_url)

    def _eh_termo_complexo(self, procedimento):
        """Determina se um termo médico é complexo e precisa normalização"""
        if not procedimento or len(procedimento) < 10:
            return False

        # Termos médicos complexos geralmente:
        # - São longos (>20 caracteres)
        # - Contêm termos técnicos médicos
        # - Estão em MAIÚSCULAS
        # - Contêm palavras gregas/latinas

        termos_tecnicos = [
            'ECTOMIA', 'PLASTIA', 'TOMIA', 'SCOPIA', 'GRAFIA',
            'EMULSIFICA', 'ADENOMECTOMIA', 'COLPOPERINE', 'FACOEMULSIFICA',
            'HERNIOPLASTIA', 'COLECIST', 'APENDICECTOMIA', 'HISTERECTOMIA',
            'MASTECTOMIA', 'PROSTATECTOMIA', 'ARTROSCOPIA', 'ENDOSCOPIA',
            'COLONOSCOPIA', 'LAPAROSCOPIA', 'IMPLANTE', 'PRÓTESE', 'PROTESE'
        ]

        procedimento_up = procedimento.upper()

        # Se tem mais de 25 caracteres, provavelmente é complexo
        if len(procedimento) > 25:
            return True

        # Se contém termos técnicos
        for termo in termos_tecnicos:
            if termo in procedimento_up:
                return True

        return False

    def normalizar_procedimento(self, procedimento_original):
        """
        Normaliza um procedimento médico usando cache e IA

        Returns:
            dict: {
                'original': str,
                'normalizado': str,
                'simples': str,
                'explicacao': str,
                'fonte': 'cache'|'deepseek'|'original'
            }
        """
        if not procedimento_original or not procedimento_original.strip():
            return None

        procedimento_original = procedimento_original.strip()

        # 1. Verificar se já está normalizado no cache
        cached = ProcedimentoNormalizado.obter_ou_criar(procedimento_original)
        if cached and cached.aprovado:
            cached.incrementar_uso()
            return {
                'original': procedimento_original,
                'normalizado': cached.termo_normalizado,
                'simples': cached.termo_simples,
                'explicacao': cached.explicacao,
                'fonte': 'cache'
            }

        # 2. Verificar se o termo é complexo o suficiente para normalizar
        if not self._eh_termo_complexo(procedimento_original):
            # Termo simples, usar o próprio termo
            return {
                'original': procedimento_original,
                'normalizado': procedimento_original.title(),
                'simples': procedimento_original.title(),
                'explicacao': '',
                'fonte': 'original'
            }

        # 3. Se API não está configurada, usar o original
        if not self._esta_configurado():
            logger.warning("DeepSeek AI não configurada. Usando termo original.")
            return {
                'original': procedimento_original,
                'normalizado': procedimento_original.title(),
                'simples': procedimento_original.title(),
                'explicacao': '',
                'fonte': 'original'
            }

        # 4. Chamar a API DeepSeek para normalizar
        try:
            resultado = self._chamar_api(procedimento_original)
            if resultado:
                # Salvar no cache
                ProcedimentoNormalizado.salvar_normalizacao(
                    termo_original=procedimento_original,
                    termo_normalizado=resultado['termo_normalizado'],
                    termo_simples=resultado['termo_simples'],
                    explicacao=resultado.get('explicacao', ''),
                    fonte='deepseek'
                )
                return {
                    'original': procedimento_original,
                    'normalizado': resultado['termo_normalizado'],
                    'simples': resultado['termo_simples'],
                    'explicacao': resultado.get('explicacao', ''),
                    'fonte': 'deepseek'
                }
        except Exception as e:
            logger.error(f"Erro ao normalizar procedimento '{procedimento_original}': {e}")

        # Fallback: usar o original
        return {
            'original': procedimento_original,
            'normalizado': procedimento_original.title(),
            'simples': procedimento_original.title(),
            'explicacao': '',
            'fonte': 'original'
        }

    def _chamar_api(self, procedimento):
        """Chama a API DeepSeek para normalizar o procedimento"""
        prompt = f"""Você é um assistente médico especializado em comunicação com pacientes.

TAREFA: Simplifique o seguinte termo médico para que pacientes leigos possam entender facilmente.

TERMO MÉDICO: {procedimento}

RETORNE UM JSON com:
1. "termo_normalizado": Nome mais amigável do procedimento (máximo 60 caracteres)
2. "termo_simples": Versão ultra-simplificada (máximo 40 caracteres)
3. "explicacao": Breve explicação em 1 linha do que é o procedimento

EXEMPLO:
{{
  "termo_normalizado": "Cirurgia de correção da bexiga e região íntima",
  "termo_simples": "Cirurgia ginecológica",
  "explicacao": "Procedimento para corrigir problemas na região íntima feminina"
}}

Responda APENAS com o JSON, sem texto adicional."""

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': self.model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,  # Baixa temperatura para respostas mais consistentes
            'max_tokens': 300
        }

        try:
            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=self.timeout
            )

            if response.status_code == 200:
                data = response.json()
                content = data['choices'][0]['message']['content'].strip()

                # Tentar extrair JSON da resposta
                # A API pode retornar markdown com ```json```
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()

                resultado = json.loads(content)
                return resultado
            else:
                logger.error(f"Erro na API DeepSeek: {response.status_code} - {response.text}")
                return None

        except Exception as e:
            logger.error(f"Exceção ao chamar DeepSeek API: {e}")
            return None


# =============================================================================
# SERVICO WHATSAPP
# =============================================================================

class WhatsApp:
    def __init__(self, usuario_id=None):
        """
        Inicializa conexão WhatsApp para um usuário específico
        API URL e Key vêm do ConfigGlobal (admin)
        Instance name é única por usuário

        Args:
            usuario_id: ID do usuário (obrigatório)
        """
        if not usuario_id:
            # Fallback: pegar do current_user se disponível
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                usuario_id = current_user.id
            else:
                raise ValueError("usuario_id é obrigatório para WhatsApp")

        # Buscar config global (API URL e Key definidos pelo admin)
        cfg_global = ConfigGlobal.get()

        # Buscar config do usuário (instance name única)
        cfg_user = ConfigWhatsApp.get(usuario_id)

        self.url = (cfg_global.evolution_api_url or '').rstrip('/')
        self.key = cfg_global.evolution_api_key or ''
        self.instance = cfg_user.instance_name or ''
        self.ativo = cfg_global.ativo  # Global ativo
        self.usuario_id = usuario_id
        self.cfg_user = cfg_user  # Guardar referência para atualizar depois

        # Configurações de envio (valores padrão)
        self.tempo_entre_envios = cfg_user.tempo_entre_envios or 15  # 15 segundos padrão
        self.limite_diario = cfg_user.limite_diario or 500  # 500 mensagens/dia padrão

    def ok(self):
        """Verifica se configuração global está ativa"""
        return bool(self.ativo and self.url and self.instance and self.key)

    def _headers(self):
        return {'apikey': self.key, 'Content-Type': 'application/json'}

    def _req(self, method, endpoint, data=None):
        try:
            url = f"{self.url}{endpoint}"
            if method == 'GET':
                r = requests.get(url, headers=self._headers(), timeout=30)
            else:
                r = requests.post(url, headers=self._headers(), json=data, timeout=30)
            return True, r
        except Exception as e:
            return False, str(e)

    def conectado(self):
        if not self.ok():
            return False, "Nao configurado"
        ok, r = self._req('GET', f"/instance/connectionState/{self.instance}")
        if ok and r.status_code == 200:
            data = r.json()
            state = data.get('instance', {}).get('state', '')
            if not state:
                state = data.get('state', '')
            return state == 'open', state
        return False, "Erro ao verificar conexao"

    def listar_instancias(self):
        """Lista todas as instancias"""
        if not self.ok():
            return False, "Nao configurado"
        ok, r = self._req('GET', '/instance/fetchInstances')
        if ok and r.status_code == 200:
            return True, r.json()
        return False, f"Erro: {r.status_code if ok else r}"

    def criar_instancia(self):
        """Cria nova instancia"""
        if not self.ok():
            return False, "Nao configurado"

        ok, r = self._req('POST', '/instance/create', {
            'instanceName': self.instance,
            'token': self.key,
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        })

        if ok and r.status_code in [200, 201]:
            logger.info(f"Instancia criada: {self.instance}")
            return True, "Instancia criada"
        elif ok and r.status_code == 403:
            # Pode ser que ja existe
            if 'already' in r.text.lower():
                return True, "Instancia ja existe"
        elif ok and r.status_code == 409:
            return True, "Instancia ja existe"

        return False, f"Erro ao criar: {r.status_code if ok else r}"

    def qrcode(self):
        """
        Obtem QR Code para conectar WhatsApp
        Baseado na implementacao funcional da Evolution API v2
        """
        if not self.ok():
            return False, "WhatsApp nao configurado. Preencha URL, Nome da Instancia e API Key."

        try:
            logger.info(f"=== OBTENDO QR CODE ===")
            logger.info(f"Instancia: {self.instance}")
            logger.info(f"URL: {self.url}")

            # Passo 1: Verifica se instancia existe
            sucesso, instances = self.listar_instancias()

            if not sucesso:
                if "403" in str(instances):
                    return False, "API Key invalida. Verifique a configuracao."
                return False, f"Erro ao verificar instancias: {instances}"

            # Verifica se nossa instancia existe
            instance_exists = False
            if isinstance(instances, list):
                for inst in instances:
                    inst_name = inst.get('instance', {}).get('instanceName') or inst.get('instanceName')
                    if inst_name == self.instance:
                        instance_exists = True
                        state = inst.get('instance', {}).get('status') or inst.get('state') or inst.get('instance', {}).get('state')
                        logger.info(f"Instancia encontrada - Estado: {state}")

                        if state == 'open':
                            return False, "WhatsApp ja esta conectado!"
                        break

            # Passo 2: Se nao existe, cria
            if not instance_exists:
                logger.info("Instancia nao existe, criando...")
                sucesso, msg = self.criar_instancia()
                if not sucesso:
                    return False, f"Erro ao criar instancia: {msg}"
                logger.info("Instancia criada, aguardando...")
                time.sleep(2)

            # Passo 3: Conecta e obtem QR Code
            ok, r = self._req('GET', f"/instance/connect/{self.instance}")

            logger.info(f"Response Status: {r.status_code if ok else 'erro'}")

            if ok and r.status_code == 200:
                data = r.json()
                logger.info(f"Response data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

                qrcode = None

                # Formato 1: { "base64": "data:image..." }
                if isinstance(data, dict):
                    if 'base64' in data:
                        qrcode = data['base64']
                        logger.info("QR Code encontrado (formato: base64)")

                    # Formato 2: { "qrcode": { "base64": "..." } }
                    elif 'qrcode' in data:
                        qr_obj = data['qrcode']
                        if isinstance(qr_obj, dict):
                            qrcode = qr_obj.get('base64') or qr_obj.get('code')
                        elif isinstance(qr_obj, str):
                            qrcode = qr_obj
                        if qrcode:
                            logger.info("QR Code encontrado (formato: qrcode)")

                    # Formato 3: { "code": "..." }
                    elif 'code' in data:
                        qrcode = data['code']
                        logger.info("QR Code encontrado (formato: code)")

                    # Formato 4: Pairing code
                    elif 'pairingCode' in data:
                        pairing = data['pairingCode']
                        logger.info(f"Pairing code: {pairing}")
                        return False, f"Use o codigo de pareamento: {pairing}"

                    # Formato 5: Ja conectado
                    elif data.get('instance', {}).get('state') == 'open':
                        return False, "WhatsApp ja esta conectado!"

                if qrcode:
                    if not qrcode.startswith('data:image'):
                        qrcode = f"data:image/png;base64,{qrcode}"
                    logger.info(f"QR Code retornado ({len(qrcode)} chars)")
                    return True, qrcode
                else:
                    logger.warning(f"QR nao encontrado. Resposta: {str(data)[:300]}")
                    return False, "QR Code nao disponivel. Tente novamente em alguns segundos."

            elif ok and r.status_code == 404:
                return False, "Instancia nao encontrada. Verifique o nome da instancia."

            elif ok and r.status_code in [401, 403]:
                return False, "API Key invalida."

            else:
                error_msg = f"HTTP {r.status_code}: {r.text[:200]}" if ok else str(r)
                logger.error(f"Erro: {error_msg}")
                return False, error_msg

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Erro de conexao: {e}")
            return False, f"Nao foi possivel conectar em {self.url}. Verifique se a Evolution API esta rodando."

        except Exception as e:
            logger.error(f"Excecao ao obter QR Code: {e}", exc_info=True)
            return False, f"Erro: {str(e)}"

    def verificar_numeros(self, numeros):
        """Verifica lista de numeros no WhatsApp"""
        if not self.ok():
            return {}

        result = {}
        nums = [str(n) for n in numeros if n]
        if not nums:
            return {}

        ok, r = self._req('POST', f"/chat/whatsappNumbers/{self.instance}", {'numbers': nums})

        if ok and r.status_code == 200:
            try:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        num = ''.join(filter(str.isdigit, str(item.get('number', ''))))
                        exists = item.get('exists', False) or item.get('numberExists', False)
                        jid = item.get('jid', '')
                        if num:
                            result[num] = {'exists': exists, 'jid': jid}
                elif isinstance(data, dict):
                    for num, info in data.items():
                        num_clean = ''.join(filter(str.isdigit, num))
                        if isinstance(info, dict):
                            result[num_clean] = {'exists': info.get('exists', False), 'jid': info.get('jid', '')}
                        else:
                            result[num_clean] = {'exists': bool(info), 'jid': ''}
            except:
                pass
        return result

    def enviar(self, numero, texto):
        if not self.ok():
            return False, "Nao configurado"

        num = ''.join(filter(str.isdigit, str(numero)))
        ok, r = self._req('POST', f"/message/sendText/{self.instance}", {'number': num, 'text': texto})

        if ok and r.status_code in [200, 201]:
            try:
                mid = r.json().get('key', {}).get('id', '')
                return True, mid
            except:
                return True, ''
        return False, r.text[:100] if ok else r


# =============================================================================
# FUNCOES AUXILIARES
# =============================================================================

def verificar_acesso_campanha(campanha_id):
    """Verifica se o usuario atual tem acesso a campanha.
    Retorna a campanha se tiver acesso, senao retorna None."""
    from flask import abort
    camp = Campanha.query.get_or_404(campanha_id)
    if camp.criador_id != current_user.id:
        abort(403)  # Forbidden
    return camp

def verificar_acesso_ticket(ticket_id):
    """Verifica se o usuario atual tem acesso ao ticket.
    Retorna o ticket se tiver acesso, senao retorna None."""
    from flask import abort
    ticket = TicketAtendimento.query.get_or_404(ticket_id)
    if ticket.campanha and ticket.campanha.criador_id != current_user.id:
        abort(403)  # Forbidden
    return ticket

def verificar_acesso_contato(contato_id):
    """Verifica se o usuario atual tem acesso ao contato.
    Retorna o contato se tiver acesso, senao retorna None."""
    from flask import abort
    contato = Contato.query.get_or_404(contato_id)
    if contato.campanha.criador_id != current_user.id:
        abort(403)  # Forbidden
    return contato

def formatar_numero(num):
    if not num:
        return None
    num = ''.join(filter(str.isdigit, str(num))).lstrip('0')
    if not num:
        return None
    if num.startswith('55'):
        return num if len(num) in [12, 13] else None
    if len(num) in [10, 11]:
        return '55' + num
    return None


def processar_planilha(arquivo, campanha_id):
    try:
        df = pd.read_excel(arquivo)
        if df.empty:
            return False, "Planilha vazia", 0

        df.columns = [str(c).strip().lower() for c in df.columns]

        col_nome = col_tel = col_proc = col_nasc = None
        for c in df.columns:
            if c in ['nome', 'usuario', 'usuário', 'paciente']:
                col_nome = c
            elif c in ['telefone', 'celular', 'fone', 'tel', 'whatsapp', 'contato']:
                col_tel = c
            elif c in ['procedimento', 'cirurgia', 'procedimentos']:
                col_proc = c
            elif c in ['nascimento', 'data_nascimento', 'data nascimento', 'dt_nasc', 'dtnasc', 'dt nasc']:
                col_nasc = c

        if not col_nome or not col_tel:
            return False, f"Colunas obrigatorias nao encontradas. Disponiveis: {list(df.columns)}", 0

        criados = 0

        # Agrupar por Nome e Data de Nascimento (se houver) para unificar contatos
        pessoas = {} # chave: (nome, data_nascimento_str) -> {telefones: set(), proc: str, data_nasc_obj: date}

        for _, row in df.iterrows():
            nome = str(row.get(col_nome, '')).strip()
            if not nome or nome.lower() == 'nan':
                continue

            # Tratamento Data Nascimento
            dt_nasc = None
            dt_nasc_str = ''
            if col_nasc:
                val = row.get(col_nasc)
                if pd.notna(val):
                    try:
                        if isinstance(val, datetime):
                            dt_nasc = val.date()
                        else:
                            # Tentar parsear string
                            dt_nasc = pd.to_datetime(val, dayfirst=True).date()
                        dt_nasc_str = dt_nasc.isoformat()
                    except:
                        pass

            chave = (nome, dt_nasc_str)

            if chave not in pessoas:
                # Procedimento
                proc = str(row.get(col_proc, 'o procedimento')).strip() if col_proc else 'o procedimento'
                if proc.lower() == 'nan': proc = 'o procedimento'
                if '-' in proc:
                    partes = proc.split('-', 1)
                    if partes[0].strip().isdigit():
                        proc = partes[1].strip()

                pessoas[chave] = {
                    'nome': nome,
                    'nascimento': dt_nasc,
                    'procedimento': proc,
                    'telefones': set()
                }

            # Telefones
            tels = str(row.get(col_tel, '')).strip()
            if tels and tels.lower() != 'nan':
                for tel in tels.replace(',', ' ').replace(';', ' ').replace('/', ' ').split():
                    tel = tel.strip()
                    if not tel: continue
                    fmt = formatar_numero(tel)
                    if fmt:
                        pessoas[chave]['telefones'].add((tel, fmt))

        # =========================================================================
        # NORMALIZAÇÃO DE PROCEDIMENTOS COM IA (DeepSeek)
        # =========================================================================
        # Coletar procedimentos únicos da planilha
        procedimentos_unicos = set()
        for dados in pessoas.values():
            if dados['procedimento']:
                procedimentos_unicos.add(dados['procedimento'])

        # Normalizar procedimentos únicos usando IA com cache
        ai = DeepSeekAI()
        mapa_normalizacao = {}  # original -> normalizado

        logger.info(f"Normalizando {len(procedimentos_unicos)} procedimentos únicos...")

        for proc_original in procedimentos_unicos:
            resultado = ai.normalizar_procedimento(proc_original)
            if resultado:
                mapa_normalizacao[proc_original] = resultado['normalizado']
                logger.info(f"Normalizado: '{proc_original}' -> '{resultado['normalizado']}' (fonte: {resultado['fonte']})")
            else:
                # Fallback: usar o original
                mapa_normalizacao[proc_original] = proc_original

        logger.info(f"Normalização concluída. {len(mapa_normalizacao)} mapeamentos criados.")
        # =========================================================================

        # Salvar no Banco
        for chave, dados in pessoas.items():
            if not dados['telefones']:
                continue

            # Obter procedimento normalizado
            proc_original = dados['procedimento']
            proc_normalizado = mapa_normalizacao.get(proc_original, proc_original)

            c = Contato(
                campanha_id=campanha_id,
                nome=dados['nome'][:200],
                data_nascimento=dados['nascimento'],
                procedimento=proc_original[:500],  # Termo original
                procedimento_normalizado=proc_normalizado[:300],  # Termo normalizado
                status='pendente'
            )
            db.session.add(c)
            db.session.flush() # Para ter o ID

            for i, (original, fmt) in enumerate(dados['telefones']):
                t = Telefone(
                    contato_id=c.id,
                    numero=original[:20],
                    numero_fmt=fmt,
                    prioridade=i+1
                )
                db.session.add(t)

            criados += 1

        db.session.commit()
        camp = db.session.get(Campanha, campanha_id)
        if camp:
            camp.atualizar_stats()
            db.session.commit()

        return True, "OK", criados
    except Exception as e:
        logger.error(f"Erro processar planilha: {e}")
        return False, str(e), 0


def validar_campanha_bg(campanha_id):
    with app.app_context():
        try:
            camp = db.session.get(Campanha, campanha_id)
            if not camp:
                return

            camp.status = 'validando'
            camp.status_msg = 'Verificando numeros...'
            db.session.commit()

            # Usar WhatsApp do criador da campanha
            ws = WhatsApp(camp.criador_id)
            if not ws.ok():
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp nao configurado'
                db.session.commit()
                return

            # Buscar telefones pendentes de validacao
            # Join com Contato para garantir que sao da campanha certa
            telefones = Telefone.query.join(Contato).filter(Contato.campanha_id == campanha_id, Telefone.whatsapp_valido == None).all()
            
            if not telefones:
                camp.status = 'pronta'
                camp.status_msg = 'Nenhum numero para validar'
                db.session.commit()
                return

            total = len(telefones)
            validos = invalidos = 0

            # Processa em lotes
            batch = 50
            for i in range(0, total, batch):
                lote = telefones[i:i+batch]
                nums = [t.numero_fmt for t in lote]

                camp.status_msg = f'Verificando {i+len(lote)}/{total}...'
                db.session.commit()

                result = ws.verificar_numeros(nums)

                for t in lote:
                    info = result.get(t.numero_fmt, {})
                    t.whatsapp_valido = info.get('exists', False)
                    t.jid = info.get('jid', '')
                    t.data_validacao = datetime.utcnow()
                    if t.whatsapp_valido:
                        validos += 1
                    else:
                        invalidos += 1

                db.session.commit()
                time.sleep(1)

            # Atualizar status dos contatos
            # Se tiver pelo menos 1 valido -> pronto_envio
            contatos = camp.contatos.all()
            for c in contatos:
                tels_validos = c.telefones.filter_by(whatsapp_valido=True).count()
                if tels_validos > 0:
                    if c.status == 'pendente':
                        c.status = 'pronto_envio'
                else:
                    # Se ja validou todos e nao tem nenhum valido
                    tels_pendentes = c.telefones.filter_by(whatsapp_valido=None).count()
                    if tels_pendentes == 0:
                        c.status = 'sem_whatsapp' # ou erro

            camp.status = 'pronta'
            camp.status_msg = f'{validos} nums validos, {invalidos} invalidos'
            camp.atualizar_stats()
            db.session.commit()

        except Exception as e:
            logger.error(f"Erro validacao: {e}")
            camp = db.session.get(Campanha, campanha_id)
            if camp:
                camp.status = 'erro'
                camp.status_msg = str(e)[:200]
                db.session.commit()


def enviar_campanha_bg(campanha_id):
    with app.app_context():
        try:
            camp = db.session.get(Campanha, campanha_id)
            if not camp:
                return

            ws = WhatsApp(camp.criador_id)
            if not ws.ok():
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp nao configurado'
                db.session.commit()
                return

            conn, _ = ws.conectado()
            if not conn:
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp desconectado'
                db.session.commit()
                return

            camp.status = 'em_andamento'
            camp.data_inicio = datetime.utcnow()
            db.session.commit()

            # Buscar contatos pendentes ou prontos
            # Prioriza prontos, depois pendentes
            contatos = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).order_by(Contato.status.desc(), Contato.id).all()
            
            total = len(contatos)
            enviados_pessoas = 0 # Contador de PESSOAS contactadas com sucesso
            erros = 0

            for i, c in enumerate(contatos):
                db.session.refresh(camp)
                if camp.status != 'em_andamento':
                    break

                # Verificar se atingiu duração máxima
                if camp.atingiu_duracao():
                    camp.status = 'concluida'
                    camp.status_msg = f'Duração de {camp.dias_duracao} dias atingida'
                    db.session.commit()
                    break

                # Verificar se está dentro do horário de funcionamento
                if not camp.pode_enviar_agora():
                    camp.status = 'pausada'
                    camp.status_msg = f'Fora do horário ({camp.hora_inicio}h-{camp.hora_fim}h)'
                    db.session.commit()
                    break

                # Verificar se atingiu meta diária
                if not camp.pode_enviar_hoje():
                    camp.status = 'pausada'
                    camp.status_msg = f'Meta diária atingida ({camp.meta_diaria} pessoas)'
                    db.session.commit()
                    break

                camp.status_msg = f'Processando {i+1}/{total}: {c.nome}'
                db.session.commit()
                
                # Validacao JIT (Just-In-Time)
                if c.status == 'pendente':
                    # Validar numeros deste contato
                    tels = c.telefones.filter_by(whatsapp_valido=None).all()
                    if tels:
                        nums = [t.numero_fmt for t in tels]
                        result = ws.verificar_numeros(nums)
                        
                        tem_valido = False
                        for t in tels:
                            info = result.get(t.numero_fmt, {})
                            t.whatsapp_valido = info.get('exists', False)
                            t.jid = info.get('jid', '')
                            t.data_validacao = datetime.utcnow()
                            if t.whatsapp_valido:
                                tem_valido = True
                        
                        db.session.commit()
                        
                        # Re-verificar se tem validos agora
                        if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                            c.status = 'pronto_envio'
                        else:
                            c.status = 'sem_whatsapp'
                            db.session.commit()
                            continue # Pula para proximo
                    else:
                        # Se estava pendente mas nao tinha numeros para validar (??)
                        if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                            c.status = 'pronto_envio'
                        else:
                            c.status = 'sem_whatsapp'
                            db.session.commit()
                            continue

                # Envio
                if c.status == 'pronto_envio':
                    # Usar procedimento normalizado (mais simples) se disponível, senão usar original
                    procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
                    msg = camp.mensagem.replace('{nome}', c.nome).replace('{procedimento}', procedimento_msg)
                    
                    # Enviar para TODOS os numeros validos da pessoa
                    telefones_validos = c.telefones.filter_by(whatsapp_valido=True).all()
                    
                    sucesso_pessoa = False
                    
                    for t in telefones_validos:
                        ok, result = ws.enviar(t.numero_fmt, msg)

                        if ok:
                            t.enviado = True
                            t.data_envio = datetime.utcnow()
                            t.msg_id = result
                            sucesso_pessoa = True

                            log = LogMsg(campanha_id=camp.id, contato_id=c.id, direcao='enviada',
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='ok')
                            db.session.add(log)
                        else:
                            log = LogMsg(campanha_id=camp.id, contato_id=c.id, direcao='enviada',
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='erro', erro=result)

                    # Se conseguiu enviar para pelo menos um número, registrar o envio
                    if sucesso_pessoa:
                        c.status = 'enviado'
                        camp.registrar_envio()  # Incrementar contador diário
                        enviados_pessoas += 1

                    db.session.commit()
                    camp.atualizar_stats()
                    db.session.commit()

                    if i < total - 1:
                        time.sleep(camp.tempo_entre_envios)

            # Verificar se acabou
            # Se nao tem mais pendentes ou pronto_envio
            restantes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
            if restantes == 0 and camp.status == 'em_andamento':
                camp.status = 'concluida'
                camp.data_fim = datetime.utcnow()
                camp.status_msg = f'{enviados_pessoas} pessoas contactadas'

            camp.atualizar_stats()
            db.session.commit()

        except Exception as e:
            logger.error(f"Erro envio: {e}")
            camp = db.session.get(Campanha, campanha_id)
            if camp:
                camp.status = 'erro'
                camp.status_msg = str(e)[:200]
                db.session.commit()


def processar_followup_bg():
    """Processa follow-up para contatos que não responderam"""
    with app.app_context():
        try:
            config = ConfigTentativas.get()
            if not config.ativo:
                logger.info("Follow-up desativado")
                return

            logger.info("=== INICIANDO PROCESSAMENTO DE FOLLOW-UP ===")

            # Mensagens de follow-up personalizadas
            MENSAGENS_FOLLOWUP = {
                1: """📋 *Olá novamente, {nome}*!

Não recebemos sua resposta sobre o procedimento: *{procedimento}*.

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa""",

                2: """📋 *{nome}*, esta é nossa penúltima tentativa de contato.

Procedimento: *{procedimento}*

⚠️ *IMPORTANTE:* Se não recebermos resposta em {dias} dias, faremos uma última tentativa.

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho interesse""",

                3: """📋 *{nome}*, este é nosso último contato.

Como não recebemos resposta, vamos considerar que você não tem mais interesse no procedimento: *{procedimento}*.

Se ainda tiver interesse, responda URGENTE nesta mensagem ou ligue para (85) 3366-8000.

Caso contrário, sua vaga será disponibilizada."""
            }

            data_limite = datetime.utcnow() - timedelta(days=config.intervalo_dias)

            # Buscar contatos que precisam de follow-up
            contatos = Contato.query.join(Telefone).filter(
                Contato.status == 'enviado',
                Contato.confirmado == False,
                Contato.rejeitado == False,
                Contato.data_resposta == None,
                Telefone.enviado == True,
                Telefone.whatsapp_valido == True
            ).distinct().all()

            logger.info(f"Total de contatos para verificar: {len(contatos)}")

            processados = 0

            for c in contatos:
                # Verificar última tentativa
                ultima_tentativa = TentativaContato.query.filter_by(
                    contato_id=c.id
                ).order_by(TentativaContato.numero_tentativa.desc()).first()

                # Verificar primeira tentativa (envio original)
                primeiro_envio = c.telefones.filter(Telefone.enviado == True).order_by(Telefone.data_envio).first()

                if not ultima_tentativa:
                    # Primeira tentativa de follow-up
                    if primeiro_envio and primeiro_envio.data_envio < data_limite:
                        num_tentativa = 1
                    else:
                        continue
                else:
                    # Já tem tentativas
                    if ultima_tentativa.numero_tentativa >= config.max_tentativas:
                        # Esgotou tentativas - marcar como "sem resposta"
                        if c.status != 'sem_resposta':
                            c.status = 'sem_resposta'
                            c.erro = f'Sem resposta após {config.max_tentativas} tentativas'
                            db.session.commit()
                            logger.info(f"Contato {c.nome} marcado como sem resposta")
                        continue

                    if ultima_tentativa.data_tentativa < data_limite:
                        num_tentativa = ultima_tentativa.numero_tentativa + 1
                    else:
                        continue

                # Enviar follow-up
                msg_template = MENSAGENS_FOLLOWUP.get(num_tentativa, MENSAGENS_FOLLOWUP[1])
                msg = msg_template.replace('{nome}', c.nome).replace(
                    '{procedimento}', c.procedimento or 'o procedimento'
                ).replace('{dias}', str(config.intervalo_dias))

                # Criar WhatsApp instance para o criador da campanha
                if not c.campanha or not c.campanha.criador_id:
                    logger.warning(f"Contato {c.id} sem campanha ou criador válido")
                    continue

                ws = WhatsApp(c.campanha.criador_id)
                if not ws.ok():
                    logger.error(f"WhatsApp não configurado para usuário {c.campanha.criador_id}")
                    continue

                telefones = c.telefones.filter_by(whatsapp_valido=True).all()
                enviado = False

                for t in telefones:
                    ok, _ = ws.enviar(t.numero_fmt, msg)
                    if ok:
                        enviado = True

                        # Registrar tentativa
                        tentativa = TentativaContato(
                            contato_id=c.id,
                            numero_tentativa=num_tentativa,
                            data_tentativa=datetime.utcnow(),
                            proxima_tentativa=datetime.utcnow() + timedelta(days=config.intervalo_dias),
                            status='enviada',
                            mensagem_enviada=msg
                        )
                        db.session.add(tentativa)

                        # Log
                        log = LogMsg(
                            campanha_id=c.campanha_id,
                            contato_id=c.id,
                            direcao='enviada',
                            telefone=t.numero_fmt,
                            mensagem=f'[Follow-up {num_tentativa}] {msg[:500]}',
                            status='ok'
                        )
                        db.session.add(log)

                        logger.info(f"Follow-up {num_tentativa} enviado para {c.nome}")
                        break

                if enviado:
                    db.session.commit()
                    processados += 1
                    time.sleep(15)  # Intervalo entre envios

            logger.info(f"=== FOLLOW-UP CONCLUÍDO: {processados} mensagens enviadas ===")

        except Exception as e:
            logger.error(f"Erro no processamento de follow-up: {e}", exc_info=True)


def criar_faqs_padrao():
    """Cria FAQs padrão se não existirem"""
    try:
        if RespostaAutomatica.query.count() > 0:
            return

        faqs_padrao = [
            {
                'categoria': 'horario',
                'gatilhos': ['horário', 'horario', 'que horas', 'hora', 'quando'],
                'resposta': '📋 O agendamento será feito após sua confirmação. A equipe entrará em contato para definir data e horário.',
                'prioridade': 5
            },
            {
                'categoria': 'endereco',
                'gatilhos': ['endereço', 'endereco', 'onde fica', 'localização', 'local', 'chegar'],
                'resposta': '📍 *Hospital Universitário Walter Cantídio*\nRua Capitão Francisco Pedro, 1290 - Rodolfo Teófilo\nFortaleza - CE\nCEP: 60430-370',
                'prioridade': 5
            },
            {
                'categoria': 'documento',
                'gatilhos': ['documento', 'levar', 'precisar', 'necessário', 'necessario', 'precisa levar'],
                'resposta': '📄 *Documentos necessários:*\n• RG e CPF\n• Cartão do SUS\n• Encaminhamento médico\n• Exames anteriores (se houver)',
                'prioridade': 4
            },
            {
                'categoria': 'preparo',
                'gatilhos': ['jejum', 'preparo', 'preparar', 'antes da cirurgia', 'cuidados'],
                'resposta': '🏥 As orientações de preparo serão fornecidas pela equipe médica no momento do agendamento. Cada procedimento tem suas especificidades.',
                'prioridade': 3
            },
            {
                'categoria': 'acompanhante',
                'gatilhos': ['acompanhante', 'acompanhar', 'pode ir com', 'levar alguém', 'levar alguem'],
                'resposta': '👥 Sim, você pode e deve trazer um acompanhante maior de 18 anos. O acompanhante é essencial para o pós-operatório.',
                'prioridade': 3
            },
            {
                'categoria': 'agendamento',
                'gatilhos': ['prazo', 'quanto tempo', 'demora', 'demorar', 'tempo de espera'],
                'resposta': '⏱️ O prazo para contato varia conforme a fila de espera. Nossa equipe priorizará seu atendimento após sua confirmação.',
                'prioridade': 4
            },
            {
                'categoria': 'cancelamento',
                'gatilhos': ['cancelar', 'desmarcar', 'não posso', 'nao posso', 'remarcar'],
                'resposta': '📞 Para cancelar ou remarcar, entre em contato pelo telefone (85) 3366-8000 ou responda esta mensagem informando sua situação.',
                'prioridade': 5
            },
            {
                'categoria': 'convenio',
                'gatilhos': ['plano', 'convênio', 'convenio', 'particular', 'sus', 'pagar'],
                'resposta': '🏥 O Hospital Universitário Walter Cantídio atende pelo SUS (Sistema Único de Saúde). O atendimento é gratuito.',
                'prioridade': 4
            },
            {
                'categoria': 'resultado_exames',
                'gatilhos': ['resultado', 'exame', 'laudo', 'buscar resultado'],
                'resposta': '📋 Resultados de exames podem ser retirados na recepção do hospital com documento de identidade.',
                'prioridade': 3
            },
            {
                'categoria': 'telefone',
                'gatilhos': ['contato', 'falar', 'ligar', 'telefone', 'telefone hospital'],
                'resposta': '📱 *Telefones do HUWC:*\n• Central: (85) 3366-8000\n• Agendamento: (85) 3366-8001\n• Horário: Segunda a Sexta, 7h às 18h',
                'prioridade': 5
            },
            {
                'categoria': 'pos_operatorio',
                'gatilhos': ['depois', 'pós', 'pos', 'recuperação', 'recuperacao', 'repouso'],
                'resposta': '🏠 As orientações de pós-operatório serão fornecidas pela equipe médica. Geralmente inclui repouso, cuidados com a ferida e retorno ambulatorial.',
                'prioridade': 3
            },
            {
                'categoria': 'medicacao',
                'gatilhos': ['remédio', 'remedio', 'medicamento', 'comprar', 'farmácia', 'farmacia'],
                'resposta': '💊 As medicações necessárias serão prescritas pelo médico. Algumas são fornecidas pelo hospital, outras podem precisar ser adquiridas.',
                'prioridade': 3
            },
            {
                'categoria': 'estacionamento',
                'gatilhos': ['estacionar', 'carro', 'vaga', 'estacionamento', 'onde parar'],
                'resposta': '🚗 O hospital possui estacionamento próprio. Há também estacionamento rotativo nas ruas próximas.',
                'prioridade': 2
            },
            {
                'categoria': 'alimentacao',
                'gatilhos': ['comer', 'beber', 'alimento', 'café', 'lanche', 'alimentar'],
                'resposta': '🍽️ As orientações sobre alimentação pré-operatória serão passadas pela equipe. Geralmente é necessário jejum antes de cirurgias.',
                'prioridade': 3
            },
            {
                'categoria': 'covid',
                'gatilhos': ['covid', 'máscara', 'mascara', 'teste', 'vacina', 'coronavirus'],
                'resposta': '😷 *Protocolos COVID-19:*\n• Uso de máscara obrigatório\n• Evite aglomerações\n• Higienize as mãos\n• Um acompanhante por paciente',
                'prioridade': 4
            },
            {
                'categoria': 'transporte',
                'gatilhos': ['transporte', 'ônibus', 'onibus', 'como chegar', 'uber'],
                'resposta': '🚌 *Como chegar:*\n• Ônibus: Linhas 051, 072, 073\n• Endereço para apps: Rua Cap. Francisco Pedro, 1290\n• Hospital fica próximo à Av. da Universidade',
                'prioridade': 2
            }
        ]

        for faq_data in faqs_padrao:
            faq = RespostaAutomatica(
                categoria=faq_data['categoria'],
                resposta=faq_data['resposta'],
                prioridade=faq_data['prioridade'],
                global_faq=True,  # FAQs padrão são globais (todos veem)
                criador_id=None  # FAQs globais não tem criador
            )
            faq.set_gatilhos(faq_data['gatilhos'])
            db.session.add(faq)

        db.session.commit()
        logger.info("FAQs padrão globais criadas")

    except Exception as e:
        logger.error(f"Erro ao criar FAQs padrão: {e}")


def criar_tutoriais_padrao():
    """Cria tutoriais padrão se não existirem"""
    try:
        if Tutorial.query.count() > 0:
            return

        tutoriais = [
            {
                'titulo': 'Bem-vindo ao Sistema de Busca Ativa',
                'categoria': 'inicio',
                'ordem': 1,
                'descricao': 'Introdução completa ao sistema',
                'conteudo': '''
<h4>🎯 Bem-vindo ao Sistema de Busca Ativa - HUWC</h4>
<p>Este sistema foi desenvolvido especialmente para gerenciar <strong>campanhas de busca ativa de pacientes em lista de espera cirúrgica</strong>, automatizando o contato via WhatsApp e organizando o atendimento.</p>

<h5>📋 Principais funcionalidades:</h5>
<ul>
    <li>📊 <strong>Dashboard Executivo:</strong> Visão completa com estatísticas, gráficos e progresso em tempo real</li>
    <li>📋 <strong>Gestão de Campanhas:</strong> Criar, importar contatos via Excel, validar números e enviar mensagens automaticamente</li>
    <li>⏰ <strong>Agendamento Inteligente:</strong> Sistema de meta diária com cálculo automático de intervalos e controle de horários</li>
    <li>📞 <strong>Múltiplos Telefones:</strong> Suporte para vários números por paciente com validação individual</li>
    <li>🎂 <strong>Verificação de Nascimento:</strong> Aguarda aniversário antes de enviar (JIT - Just In Time)</li>
    <li>⚙️ <strong>Configurações:</strong> Integração com WhatsApp via Evolution API + sistema de follow-up automático</li>
    <li>👤 <strong>Atendimento Inteligente:</strong> Tickets automáticos para mensagens urgentes, com análise de sentimento</li>
    <li>💬 <strong>FAQ Automático:</strong> Respostas instantâneas para dúvidas frequentes com sistema de gatilhos</li>
    <li>📈 <strong>Relatórios Avançados:</strong> Gráficos interativos por campanha com exportação para Excel</li>
</ul>

<h5>🚀 Fluxo básico de uso:</h5>
<ol>
    <li><strong>Configure o WhatsApp</strong> nas Configurações (Evolution API + QR Code)</li>
    <li><strong>Crie FAQs automáticos</strong> para responder dúvidas comuns</li>
    <li><strong>Configure o follow-up</strong> para mensagens após envio inicial</li>
    <li><strong>Crie uma campanha</strong> importando planilha Excel com dados dos pacientes</li>
    <li><strong>Defina meta diária</strong> e horários de funcionamento (intervalo é calculado automaticamente!)</li>
    <li><strong>Valide números</strong> (opcional, mas recomendado para economizar tempo)</li>
    <li><strong>Inicie os envios</strong> e acompanhe em tempo real</li>
    <li><strong>Atenda tickets</strong> de dúvidas complexas no painel de atendimento</li>
    <li><strong>Analise relatórios</strong> com gráficos e estatísticas detalhadas</li>
</ol>

<div class="alert alert-success">
    <strong>💡 Dica Importante:</strong> O sistema utiliza <strong>validação JIT (Just In Time)</strong>, ou seja, só valida números quando realmente necessário, evitando validar 3000+ números de uma vez e sobrecarregar a API!
</div>

<div class="alert alert-info">
    <strong>🎯 Começando:</strong> Siga a ordem dos tutoriais para entender completamente cada funcionalidade. Tempo estimado: 15-20 minutos.
</div>
                '''
            },
            {
                'titulo': 'Como Criar uma Campanha',
                'categoria': 'campanhas',
                'ordem': 2,
                'descricao': 'Guia completo de criação e configuração',
                'conteudo': '''
<h4>📋 Criando sua primeira campanha</h4>

<h5>📊 Passo 1: Preparar a planilha Excel</h5>
<p>A planilha deve estar no formato <strong>.xlsx ou .xls</strong> com as seguintes colunas:</p>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Coluna</th>
            <th>Obrigatório?</th>
            <th>Formato</th>
            <th>Exemplo</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Nome</strong> ou <strong>Usuario</strong></td>
            <td>✅ Sim</td>
            <td>Texto</td>
            <td>João Silva</td>
        </tr>
        <tr>
            <td><strong>Telefone</strong></td>
            <td>✅ Sim</td>
            <td>Número com DDD (11 dígitos)</td>
            <td>85992231683</td>
        </tr>
        <tr>
            <td><strong>Nascimento</strong></td>
            <td>❌ Opcional</td>
            <td>DD/MM/AAAA ou AAAA-MM-DD</td>
            <td>15/08/1985</td>
        </tr>
        <tr>
            <td><strong>Procedimento</strong></td>
            <td>❌ Opcional</td>
            <td>Texto</td>
            <td>Cirurgia de Catarata</td>
        </tr>
    </tbody>
</table>

<div class="alert alert-info">
    <strong>💡 Múltiplos telefones:</strong> Você pode adicionar várias linhas para a mesma pessoa! O sistema agrupa automaticamente por nome e permite até 5 telefones por paciente.
</div>

<h5>➕ Passo 2: Criar a campanha no Dashboard</h5>
<ol>
    <li>Clique no botão <strong>"Nova Campanha"</strong> no Dashboard</li>
    <li>Preencha:
        <ul>
            <li><strong>Nome da Campanha:</strong> Ex: "Busca Ativa Novembro 2024"</li>
            <li><strong>Descrição:</strong> Opcional, para referência interna</li>
            <li><strong>Mensagem:</strong> Personalize usando variáveis:
                <ul>
                    <li><code>{nome}</code> - Nome do paciente</li>
                    <li><code>{procedimento}</code> - Procedimento cadastrado</li>
                </ul>
            </li>
        </ul>
    </li>
    <li>Faça <strong>upload da planilha Excel</strong></li>
</ol>

<h5>⏰ Passo 3: Configurar Agendamento Inteligente</h5>
<p>O sistema calcula <strong>automaticamente</strong> o intervalo ideal entre envios!</p>
<ul>
    <li><strong>Meta Diária:</strong> Quantas mensagens enviar por dia (ex: 50)</li>
    <li><strong>Horário Início:</strong> Quando começar os envios (ex: 08:00)</li>
    <li><strong>Horário Fim:</strong> Quando parar os envios (ex: 18:00)</li>
    <li><strong>Duração:</strong> Quantos dias a campanha vai durar (0 = até acabar)</li>
</ul>

<div class="alert alert-success">
    <strong>✨ Exemplo de cálculo:</strong><br>
    Meta: 50 mensagens/dia | Horário: 08:00 às 18:00 (10 horas)<br>
    <strong>Intervalo calculado:</strong> 1 envio a cada 12 minutos automaticamente!
</div>

<p>O sistema respeita os <strong>dias da semana</strong> configurados e <strong>não envia em finais de semana</strong> se desabilitado.</p>

<h5>✅ Passo 4: Validar números (Opcional mas recomendado)</h5>
<p>Após criar a campanha, clique em <strong>"Validar Números"</strong> para:</p>
<ul>
    <li>✅ Verificar quais números têm WhatsApp ativo</li>
    <li>❌ Marcar números inválidos automaticamente</li>
    <li>⏱️ Economizar tempo não enviando para números inexistentes</li>
</ul>

<div class="alert alert-warning">
    <strong>⚡ Validação JIT (Just In Time):</strong> O sistema valida apenas os números que ainda não foram validados. Se você tem 3000 contatos, ele valida em lotes conforme necessário, evitando sobrecarga da API!
</div>

<h5>🚀 Passo 5: Iniciar envios</h5>
<ol>
    <li>Certifique-se que o <strong>WhatsApp está conectado</strong> (indicador verde no topo)</li>
    <li>Clique em <strong>"Iniciar Envios"</strong> na página da campanha</li>
    <li>O sistema começará a enviar automaticamente seguindo:
        <ul>
            <li>✅ Intervalo calculado</li>
            <li>✅ Horários configurados</li>
            <li>✅ Dias da semana permitidos</li>
            <li>✅ Verificação de data de nascimento (se configurado)</li>
        </ul>
    </li>
</ol>

<h5>📊 Acompanhamento em tempo real</h5>
<p>Na página da campanha você verá:</p>
<ul>
    <li>📈 Gráfico de progresso</li>
    <li>📊 Estatísticas: Total, Enviados, Confirmados, Rejeitados, Pendentes</li>
    <li>📋 Lista de todos os contatos com status individual</li>
    <li>⏰ Próximo envio agendado</li>
</ul>

<div class="alert alert-danger">
    <strong>⚠️ Importante:</strong> O WhatsApp DEVE estar conectado antes de iniciar os envios! Caso contrário, os envios ficarão em fila e só serão processados quando conectar.
</div>
                '''
            },
            {
                'titulo': 'Configurando o WhatsApp',
                'categoria': 'configuracoes',
                'ordem': 3,
                'descricao': 'Guia completo de configuração da Evolution API',
                'conteudo': '''
<h4>📱 Conectando o WhatsApp via Evolution API</h4>

<h5>🔧 Requisitos:</h5>
<ul>
    <li>✅ <strong>Evolution API v2</strong> instalada e rodando em um servidor</li>
    <li>✅ <strong>URL da API:</strong> Ex: https://evolution.seudominio.com</li>
    <li>✅ <strong>Nome da instância:</strong> Identificador único (ex: huwc_busca_ativa)</li>
    <li>✅ <strong>API Key:</strong> Chave de autenticação da Evolution API</li>
    <li>✅ <strong>Número de WhatsApp:</strong> Um chip dedicado para o sistema</li>
</ul>

<div class="alert alert-info">
    <strong>💡 O que é Evolution API?</strong> É uma API open-source que permite integrar WhatsApp com sistemas externos de forma oficial e segura, sem riscos de ban.
</div>

<h5>⚙️ Passo a passo da configuração:</h5>
<ol>
    <li><strong>Acesse as Configurações:</strong> Clique em "Configurações" no menu lateral</li>
    <li><strong>Preencha os dados da Evolution API:</strong>
        <ul>
            <li><strong>API Base URL:</strong> URL completa (ex: https://evolution.seudominio.com)</li>
            <li><strong>Instance Name:</strong> Nome da instância (ex: huwc_busca)</li>
            <li><strong>API Key:</strong> Chave de autenticação</li>
        </ul>
    </li>
    <li><strong>Ative o WhatsApp:</strong> Marque o checkbox "WhatsApp Ativo"</li>
    <li><strong>Salve as configurações:</strong> Clique em "Salvar"</li>
    <li><strong>Gere o QR Code:</strong> Clique no botão "Gerar QR Code"</li>
    <li><strong>Conecte o WhatsApp:</strong>
        <ul>
            <li>Abra o WhatsApp no celular</li>
            <li>Vá em Configurações → Aparelhos Conectados</li>
            <li>Clique em "Conectar um aparelho"</li>
            <li>Escaneie o QR Code exibido na tela</li>
        </ul>
    </li>
</ol>

<div class="alert alert-success">
    <strong>✅ Pronto!</strong> Quando conectado, você verá um indicador <span class="badge bg-success">WhatsApp Conectado</span> no topo de todas as páginas.
</div>

<h5>🔄 Configuração de Follow-Up</h5>
<p>O sistema pode enviar mensagens automáticas de acompanhamento após o primeiro contato:</p>
<ul>
    <li><strong>Ativar Follow-up:</strong> Marque o checkbox na seção "Follow-up"</li>
    <li><strong>Mensagem:</strong> Digite a mensagem que será enviada (ex: "Olá {nome}, conseguiu confirmar sua disponibilidade?")</li>
    <li><strong>Dias de espera:</strong> Quantos dias aguardar antes de enviar (ex: 3 dias)</li>
</ul>

<div class="alert alert-warning">
    <strong>⚠️ Importante:</strong> O follow-up só é enviado para contatos que não responderam nem confirmaram após o primeiro envio!
</div>

<h5>📅 Configuração de Dias da Semana</h5>
<p>Escolha em quais dias da semana o sistema pode enviar mensagens:</p>
<ul>
    <li>✅ Marque os dias permitidos (ex: Segunda a Sexta)</li>
    <li>❌ Desmarque finais de semana se não quiser enviar nesses dias</li>
    <li>💡 O sistema respeitará automaticamente essa configuração</li>
</ul>

<h5>🔍 Testando a conexão:</h5>
<ol>
    <li>Após escanear o QR Code, aguarde alguns segundos</li>
    <li>Atualize a página (F5)</li>
    <li>Verifique se o indicador mudou para "Conectado" (verde)</li>
    <li>Se não conectar, clique novamente em "Gerar QR Code"</li>
</ol>

<h5>❓ Problemas comuns:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Problema</th>
            <th>Solução</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>QR Code não aparece</td>
            <td>Verifique se a URL da API está correta e acessível</td>
        </tr>
        <tr>
            <td>QR Code expira rápido</td>
            <td>Normal! Clique em "Gerar QR Code" novamente</td>
        </tr>
        <tr>
            <td>Não conecta após escanear</td>
            <td>Verifique a API Key e o nome da instância</td>
        </tr>
        <tr>
            <td>Desconecta sozinho</td>
            <td>Pode ser problema no servidor da Evolution API</td>
        </tr>
    </tbody>
</table>

<div class="alert alert-danger">
    <strong>🚨 Segurança:</strong> Use um chip dedicado apenas para o sistema! Não use seu WhatsApp pessoal ou compartilhado.
</div>
                '''
            },
            {
                'titulo': 'Sistema de Atendimento Inteligente',
                'categoria': 'atendimento',
                'ordem': 4,
                'descricao': 'Gestão completa de tickets e atendimento',
                'conteudo': '''
<h4>🎯 Sistema de Atendimento de Tickets</h4>

<p>O sistema possui <strong>inteligência artificial</strong> que analisa todas as mensagens recebidas e cria tickets automaticamente quando detecta situações que precisam de atenção humana.</p>

<h5>🤖 Quando um ticket é criado automaticamente:</h5>
<ul>
    <li>🚨 <strong>Mensagens urgentes:</strong> Palavras como "emergência", "urgente", "dor", "grave", "hospital"</li>
    <li>😠 <strong>Análise de sentimento negativo:</strong> Sistema detecta insatisfação, raiva ou frustração</li>
    <li>❓ <strong>Dúvidas complexas:</strong> Mensagens que não encontram resposta no FAQ automático</li>
    <li>📝 <strong>Mensagens longas:</strong> Textos com mais de 200 caracteres (indica situação complexa)</li>
    <li>❌ <strong>Rejeições:</strong> Paciente indica que não pode ou não quer participar</li>
</ul>

<h5>🎫 Tipos de tickets:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Tipo</th>
            <th>Prioridade</th>
            <th>Quando aparece</th>
        </tr>
    </thead>
    <tbody>
        <tr class="table-danger">
            <td><strong>🚨 URGENTE</strong></td>
            <td>Alta</td>
            <td>Palavras de emergência, sentimento muito negativo</td>
        </tr>
        <tr class="table-warning">
            <td><strong>⚠️ IMPORTANTE</strong></td>
            <td>Média</td>
            <td>Rejeições, dúvidas não respondidas pelo FAQ</td>
        </tr>
        <tr class="table-info">
            <td><strong>ℹ️ NORMAL</strong></td>
            <td>Baixa</td>
            <td>Mensagens longas, perguntas específicas</td>
        </tr>
    </tbody>
</table>

<h5>👨‍💼 Como atender um ticket:</h5>
<ol>
    <li><strong>Acesse o painel:</strong> Clique em "Atendimento" no menu lateral</li>
    <li><strong>Visualize os tickets:</strong> Veja lista ordenada por prioridade (urgentes primeiro)</li>
    <li><strong>Filtre se necessário:</strong> Use os filtros para ver apenas urgentes, pendentes, ou em atendimento</li>
    <li><strong>Abra o ticket:</strong> Clique no ticket para ver todos os detalhes:
        <ul>
            <li>Nome do paciente</li>
            <li>Campanha relacionada</li>
            <li>Mensagem completa recebida</li>
            <li>Histórico de interações</li>
            <li>Análise de sentimento</li>
        </ul>
    </li>
    <li><strong>Assuma o ticket:</strong> Clique em "Assumir Ticket" para marcar que você está atendendo</li>
    <li><strong>Responda:</strong> Digite sua resposta personalizada na caixa de texto</li>
    <li><strong>Envie:</strong> Clique em "Enviar Resposta" - a mensagem vai direto para o WhatsApp do paciente!</li>
    <li><strong>Finalize:</strong> Após resolver, clique em "Resolver" para fechar o ticket</li>
</ol>

<div class="alert alert-success">
    <strong>✅ Automação:</strong> A resposta é enviada automaticamente via WhatsApp sem você precisar abrir o aplicativo! O sistema já registra tudo no histórico.
</div>

<h5>📊 Dashboard de tickets:</h5>
<p>No topo da página de Atendimento você vê:</p>
<ul>
    <li>🔴 <strong>Tickets Urgentes:</strong> Contador em tempo real</li>
    <li>🟡 <strong>Tickets Pendentes:</strong> Aguardando atendimento</li>
    <li>🟢 <strong>Em Atendimento:</strong> Que você já assumiu</li>
    <li>⚫ <strong>Resolvidos:</strong> Finalizados nas últimas 24h</li>
</ul>

<h5>💬 Sistema de FAQ Automático:</h5>
<p>Para reduzir a quantidade de tickets, configure respostas automáticas!</p>
<ol>
    <li>Vá em <strong>FAQ</strong> no menu</li>
    <li>Clique em "Nova Resposta Automática"</li>
    <li>Configure:
        <ul>
            <li><strong>Categoria:</strong> Ex: horário, endereço, documentos</li>
            <li><strong>Gatilhos:</strong> Palavras-chave que ativam a resposta (ex: "que horas", "horário", "quando")</li>
            <li><strong>Resposta:</strong> Mensagem que será enviada automaticamente</li>
            <li><strong>Prioridade:</strong> 1 (baixa) a 10 (alta)</li>
        </ul>
    </li>
    <li>Salve e pronto! O sistema responderá automaticamente quando detectar os gatilhos</li>
</ol>

<div class="alert alert-warning">
    <strong>⚡ Importante:</strong> O FAQ só responde se a mensagem NÃO for urgente. Mensagens urgentes sempre viram ticket, mesmo que tenham gatilhos de FAQ!
</div>

<h5>📈 Estatísticas de atendimento:</h5>
<p>O sistema registra automaticamente:</p>
<ul>
    <li>⏱️ Tempo médio de resposta</li>
    <li>✅ Taxa de resolução</li>
    <li>📊 Tickets por categoria</li>
    <li>👤 Atendimentos por operador</li>
    <li>😊 Análise de satisfação (baseada em respostas)</li>
</ul>

<div class="alert alert-info">
    <strong>💡 Dica Pro:</strong> Tickets urgentes aparecem em VERMELHO no topo da lista. Atenda-os primeiro para evitar situações críticas!
</div>
                '''
            },
            {
                'titulo': 'Entendendo os Status dos Contatos',
                'categoria': 'campanhas',
                'ordem': 5,
                'descricao': 'Fluxo completo e significado de cada status',
                'conteudo': '''
<h4>📊 Fluxo de Status dos Contatos</h4>

<p>Cada contato passa por diferentes status durante a campanha. Entender cada um é essencial para acompanhar o progresso!</p>

<h5>🔄 Ciclo de vida de um contato:</h5>

<table class="table table-bordered">
    <thead>
        <tr>
            <th>Status</th>
            <th>Badge</th>
            <th>Significado</th>
            <th>Próxima ação</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>pendente</strong></td>
            <td><span class="badge bg-secondary">Pendente</span></td>
            <td>Contato importado, aguardando processamento</td>
            <td>Sistema validará e preparará para envio</td>
        </tr>
        <tr>
            <td><strong>pronto_envio</strong></td>
            <td><span class="badge bg-info">Pronto</span></td>
            <td>Número validado, aguardando vez na fila</td>
            <td>Aguarda horário agendado para envio</td>
        </tr>
        <tr class="table-warning">
            <td><strong>aguardando_nascimento</strong></td>
            <td><span class="badge bg-warning">Aguard. Aniversário</span></td>
            <td>Esperando data de nascimento chegar</td>
            <td>Sistema envia automaticamente no aniversário</td>
        </tr>
        <tr>
            <td><strong>enviado</strong></td>
            <td><span class="badge bg-primary">Enviado</span></td>
            <td>Mensagem enviada com sucesso</td>
            <td>Aguarda resposta do paciente</td>
        </tr>
        <tr class="table-success">
            <td><strong>concluido</strong></td>
            <td><span class="badge bg-success">Concluído</span></td>
            <td>Paciente confirmou ou rejeitou</td>
            <td>Processo finalizado para este contato</td>
        </tr>
        <tr class="table-danger">
            <td><strong>erro</strong></td>
            <td><span class="badge bg-danger">Erro</span></td>
            <td>Falha no envio (número inválido, etc)</td>
            <td>Verificar erro e reenviar se possível</td>
        </tr>
    </tbody>
</table>

<h5>🎂 Status especial: aguardando_nascimento</h5>
<div class="alert alert-warning">
    <strong>⚡ Validação JIT (Just In Time):</strong><br>
    Quando um contato tem data de nascimento no futuro, o sistema <strong>NÃO envia imediatamente</strong>.
    Ele espera a data de nascimento chegar e só então envia automaticamente!<br><br>
    <strong>Por que?</strong> Para evitar contatar pacientes antes do aniversário deles, respeitando regras específicas de alguns procedimentos.
</div>

<h5>✅ Confirmações e Rejeições:</h5>
<p>Além dos status principais, cada contato pode ter flags adicionais:</p>
<ul>
    <li>✅ <strong>confirmado = True:</strong> Paciente disse "SIM", quer participar
        <ul>
            <li>Palavras detectadas: "sim", "confirmo", "quero", "aceito", "ok"</li>
        </ul>
    </li>
    <li>❌ <strong>rejeitado = True:</strong> Paciente disse "NÃO", não quer participar
        <ul>
            <li>Palavras detectadas: "não", "nao", "recuso", "desisto", "cancelar"</li>
        </ul>
    </li>
    <li>❓ <strong>duvida = True:</strong> Paciente tem dúvidas (cria ticket automaticamente)
        <ul>
            <li>Mensagens que não são sim/não claros</li>
        </ul>
    </li>
</ul>

<h5>🔄 Transições automáticas:</h5>
<p>O sistema muda os status automaticamente:</p>

<pre class="bg-light p-3">
1. IMPORTAÇÃO ──→ pendente
2. VALIDAÇÃO ───→ pronto_envio (se válido) ou erro (se inválido)
3. VERIFICAÇÃO ─→ aguardando_nascimento (se nascimento no futuro)
4. ENVIO ────────→ enviado (se sucesso) ou erro (se falha)
5. RESPOSTA ────→ concluido (após confirmação/rejeição)
</pre>

<h5>📞 Múltiplos telefones:</h5>
<p>Quando um contato tem vários telefones:</p>
<ul>
    <li>🔄 O sistema tenta o <strong>1º telefone</strong> primeiro</li>
    <li>⏱️ Se não houver resposta em <strong>X dias</strong>, tenta o próximo</li>
    <li>✅ Para ao receber confirmação ou rejeição</li>
    <li>📊 Cada telefone tem seu próprio status de validação</li>
</ul>

<div class="alert alert-info">
    <strong>💡 Dica:</strong> Na página da campanha, você pode filtrar contatos por status para focar em grupos específicos (ex: ver apenas os que erraram para reenviar).
</div>
                '''
            },
            {
                'titulo': 'Relatórios e Análise de Dados',
                'categoria': 'campanhas',
                'ordem': 6,
                'descricao': 'Gráficos interativos e exportação de dados',
                'conteudo': '''
<h4>📈 Sistema de Relatórios Avançados</h4>

<p>O sistema oferece análise completa de cada campanha com gráficos interativos e exportação para Excel!</p>

<h5>📊 Acessando relatórios:</h5>
<ol>
    <li>No <strong>Dashboard</strong>, clique no ícone 📊 ao lado de qualquer campanha</li>
    <li>Ou na página da campanha, clique em <strong>"Ver Relatórios"</strong></li>
    <li>Você verá uma página completa com gráficos e estatísticas</li>
</ol>

<h5>📉 Gráficos disponíveis:</h5>

<div class="row">
    <div class="col-md-6">
        <h6>1️⃣ Gráfico de Pizza - Distribuição de Status</h6>
        <ul>
            <li>Visualiza proporção de cada status</li>
            <li>Cores diferentes para cada categoria</li>
            <li>Clique nas legendas para ocultar/mostrar</li>
        </ul>
    </div>
    <div class="col-md-6">
        <h6>2️⃣ Gráfico de Barras - Respostas</h6>
        <ul>
            <li>Compara confirmados vs rejeitados vs pendentes</li>
            <li>Fácil visualização de taxa de sucesso</li>
            <li>Atualiza em tempo real</li>
        </ul>
    </div>
</div>

<div class="row mt-3">
    <div class="col-md-6">
        <h6>3️⃣ Gráfico de Linha - Progresso no Tempo</h6>
        <ul>
            <li>Mostra envios ao longo dos dias</li>
            <li>Identifica padrões e picos</li>
            <li>Ajuda a planejar próximas campanhas</li>
        </ul>
    </div>
    <div class="col-md-6">
        <h6>4️⃣ Taxa de Conversão</h6>
        <ul>
            <li>Percentual de confirmações sobre total</li>
            <li>Indicador de efetividade da campanha</li>
            <li>Comparação com meta estabelecida</li>
        </ul>
    </div>
</div>

<h5>📊 Estatísticas detalhadas:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Métrica</th>
            <th>Descrição</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Total de Contatos</strong></td>
            <td>Quantidade total importada da planilha</td>
        </tr>
        <tr>
            <td><strong>Enviados</strong></td>
            <td>Mensagens enviadas com sucesso</td>
        </tr>
        <tr>
            <td><strong>Confirmados</strong></td>
            <td>Pacientes que disseram SIM</td>
        </tr>
        <tr>
            <td><strong>Rejeitados</strong></td>
            <td>Pacientes que disseram NÃO</td>
        </tr>
        <tr>
            <td><strong>Pendentes</strong></td>
            <td>Ainda não receberam ou não responderam</td>
        </tr>
        <tr>
            <td><strong>Erros</strong></td>
            <td>Falhas no envio (números inválidos, etc)</td>
        </tr>
        <tr>
            <td><strong>Taxa de Resposta</strong></td>
            <td>(Confirmados + Rejeitados) / Enviados × 100</td>
        </tr>
        <tr>
            <td><strong>Taxa de Sucesso</strong></td>
            <td>Confirmados / Enviados × 100</td>
        </tr>
    </tbody>
</table>

<h5>📥 Exportação para Excel:</h5>
<p>Exporte todos os dados da campanha em formato Excel:</p>
<ol>
    <li>Na página da campanha, clique no botão <strong>"Exportar Excel"</strong> (ícone de download)</li>
    <li>O arquivo será baixado automaticamente com nome: <code>campanha_[nome]_[data].xlsx</code></li>
    <li>Contém todas as informações:
        <ul>
            <li>Nome, telefone(s), data de nascimento</li>
            <li>Procedimento</li>
            <li>Status atual</li>
            <li>Data de envio</li>
            <li>Confirmado/Rejeitado</li>
            <li>Resposta recebida</li>
            <li>Data de resposta</li>
        </ul>
    </li>
</ol>

<div class="alert alert-success">
    <strong>✅ Use o Excel para:</strong>
    <ul class="mb-0">
        <li>Análises customizadas com tabelas dinâmicas</li>
        <li>Compartilhar resultados com gestores</li>
        <li>Criar apresentações de resultados</li>
        <li>Backup dos dados da campanha</li>
    </ul>
</div>

<h5>🔄 Atualização em tempo real:</h5>
<p>Os gráficos são gerados dinamicamente! Sempre que:</p>
<ul>
    <li>✉️ Uma nova mensagem é enviada</li>
    <li>💬 Um paciente responde</li>
    <li>✅ Um contato confirma ou rejeita</li>
</ul>
<p>Os relatórios são atualizados automaticamente. Basta <strong>recarregar a página</strong> (F5) para ver os dados mais recentes!</p>

<div class="alert alert-info">
    <strong>💡 Dica Pro:</strong> Compare relatórios de diferentes campanhas para identificar qual tipo de mensagem ou horário tem melhor taxa de conversão!
</div>
                '''
            },
            {
                'titulo': 'Solução de Problemas Comuns',
                'categoria': 'inicio',
                'ordem': 7,
                'descricao': 'Troubleshooting e perguntas frequentes',
                'conteudo': '''
<h4>🔧 Solução de Problemas</h4>

<p>Encontrou algum problema? Aqui estão as soluções para os erros mais comuns!</p>

<h5>❌ Problemas com WhatsApp:</h5>

<div class="card mb-3">
    <div class="card-header bg-danger text-white">
        <strong>WhatsApp não conecta</strong>
    </div>
    <div class="card-body">
        <p><strong>Sintomas:</strong> QR Code não aparece ou não conecta após escanear</p>
        <p><strong>Soluções:</strong></p>
        <ol>
            <li>Verifique se a URL da Evolution API está correta e acessível</li>
            <li>Confirme que a API Key está correta</li>
            <li>Verifique se o nome da instância não tem espaços ou caracteres especiais</li>
            <li>Teste acessar a URL da API diretamente no navegador</li>
            <li>Reinicie o servidor da Evolution API se tiver acesso</li>
        </ol>
    </div>
</div>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>WhatsApp desconecta sozinho</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas comuns:</strong></p>
        <ul>
            <li>Servidor da Evolution API reiniciou ou caiu</li>
            <li>WhatsApp foi desconectado manualmente no celular</li>
            <li>Problema de conectividade do servidor</li>
        </ul>
        <p><strong>Solução:</strong> Reconecte usando "Gerar QR Code" novamente</p>
    </div>
</div>

<h5>📊 Problemas com Campanhas:</h5>

<div class="card mb-3">
    <div class="card-header bg-info text-white">
        <strong>Envios não estão saindo</strong>
    </div>
    <div class="card-body">
        <p><strong>Verifique:</strong></p>
        <ol>
            <li>✅ WhatsApp está conectado? (indicador verde no topo)</li>
            <li>✅ Campanha está com status "Em andamento"?</li>
            <li>✅ Está dentro do horário configurado? (ex: 08:00 às 18:00)</li>
            <li>✅ Hoje é um dia da semana permitido?</li>
            <li>✅ Há contatos com status "pronto_envio"?</li>
            <li>✅ O intervalo entre envios não está muito longo?</li>
        </ol>
    </div>
</div>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>Planilha não é importada</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas comuns:</strong></p>
        <ul>
            <li>Arquivo não está em formato .xlsx ou .xls</li>
            <li>Faltam colunas obrigatórias (Nome e Telefone)</li>
            <li>Nomes das colunas estão errados (use: Nome ou Usuario, Telefone)</li>
            <li>Planilha está vazia ou sem dados na primeira linha</li>
        </ul>
        <p><strong>Solução:</strong> Use o modelo correto com colunas: Nome, Telefone, Nascimento, Procedimento</p>
    </div>
</div>

<h5>📞 Problemas com Telefones:</h5>

<div class="card mb-3">
    <div class="card-header bg-danger text-white">
        <strong>Muitos números inválidos</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas:</strong></p>
        <ul>
            <li>Números sem DDD ou com formato incorreto</li>
            <li>Números antigos (8 dígitos em vez de 9)</li>
            <li>Números de telefone fixo sem WhatsApp</li>
        </ul>
        <p><strong>Solução:</strong></p>
        <ol>
            <li>Certifique-se que os números têm 11 dígitos (DDD + 9 dígitos)</li>
            <li>Formato: 85992231683 (sem espaços, traços ou parênteses)</li>
            <li>Use a validação automática antes de enviar</li>
        </ol>
    </div>
</div>

<h5>⏰ Problemas com Agendamento:</h5>

<div class="card mb-3">
    <div class="card-header bg-info text-white">
        <strong>Envios muito lentos ou muito rápidos</strong>
    </div>
    <div class="card-body">
        <p><strong>O intervalo é calculado automaticamente!</strong></p>
        <p>Fórmula: <code>Intervalo = (Horas disponíveis × 3600) / Meta diária</code></p>
        <p><strong>Exemplo:</strong></p>
        <ul>
            <li>Meta: 50 mensagens/dia</li>
            <li>Horário: 08:00 às 18:00 (10 horas = 36000 segundos)</li>
            <li>Intervalo: 36000 ÷ 50 = <strong>720 segundos (12 minutos)</strong></li>
        </ul>
        <p><strong>Para ajustar:</strong></p>
        <ul>
            <li>Aumente a meta diária = envios mais rápidos</li>
            <li>Diminua a meta diária = envios mais lentos</li>
            <li>Amplie o horário = mais tempo para distribuir os envios</li>
        </ul>
    </div>
</div>

<h5>🎂 Status aguardando_nascimento:</h5>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>Contatos ficam muito tempo aguardando</strong>
    </div>
    <div class="card-body">
        <p><strong>Isso é NORMAL!</strong></p>
        <p>O sistema usa <strong>validação JIT (Just In Time)</strong>:</p>
        <ul>
            <li>Se a data de nascimento está no futuro, o contato fica em "aguardando_nascimento"</li>
            <li>No dia do aniversário, o sistema envia automaticamente</li>
            <li>Isso evita contatar pacientes antes do momento certo</li>
        </ul>
        <p><strong>Para enviar imediatamente:</strong> Edite o contato e remova a data de nascimento, ou altere para uma data passada</p>
    </div>
</div>

<h5>❓ Perguntas Frequentes:</h5>

<div class="card mb-2">
    <div class="card-header"><strong>Posso pausar uma campanha?</strong></div>
    <div class="card-body">Sim! Clique em "Pausar Envios" na página da campanha. Para retomar, clique em "Retomar Envios".</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Como adicionar mais contatos a uma campanha existente?</strong></div>
    <div class="card-body">Atualmente não é possível. Crie uma nova campanha com os novos contatos ou edite manualmente usando "Adicionar Contato".</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>O sistema envia em finais de semana?</strong></div>
    <div class="card-body">Depende da configuração! Vá em Configurações e marque/desmarque os dias da semana permitidos. Se sábado e domingo estiverem desmarcados, não enviará.</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Posso usar o mesmo número para várias pessoas?</strong></div>
    <div class="card-body">Sim! O sistema agrupa automaticamente contatos com o mesmo nome, permitindo até 5 telefones por pessoa.</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Como reenviar para quem não respondeu?</strong></div>
    <div class="card-body">Na página da campanha, use o botão "Reenviar" ao lado de cada contato. Ou configure o follow-up automático nas Configurações!</div>
</div>

<div class="alert alert-success mt-4">
    <strong>💚 Ainda com dúvidas?</strong><br>
    Entre em contato com o suporte técnico ou consulte a documentação completa da Evolution API em:
    <a href="https://doc.evolution-api.com" target="_blank">doc.evolution-api.com</a>
</div>
                '''
            },
        ]

        for tut_data in tutoriais:
            tut = Tutorial(
                titulo=tut_data['titulo'],
                categoria=tut_data['categoria'],
                ordem=tut_data['ordem'],
                descricao=tut_data['descricao'],
                conteudo=tut_data['conteudo']
            )
            db.session.add(tut)

        db.session.commit()
        logger.info("Tutoriais padrão criados")

    except Exception as e:
        logger.error(f"Erro ao criar tutoriais: {e}")


def criar_admin():
    try:
        admin = Usuario.query.filter_by(email=ADMIN_EMAIL).first()
        if not admin:
            u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL, is_admin=True)
            u.set_password(ADMIN_SENHA)
            db.session.add(u)
            db.session.commit()
            logger.info(f"Admin criado: {ADMIN_EMAIL}")
        else:
            # Garantir que o admin existente tenha is_admin=True
            if not admin.is_admin:
                admin.is_admin = True
                db.session.commit()
                logger.info(f"Admin atualizado com flag is_admin: {ADMIN_EMAIL}")
    except Exception as e:
        logger.warning(f"Erro ao criar admin (banco desatualizado?): {e}")
        # Tentar recriar tabelas
        db.session.rollback()
        db.drop_all()
        db.create_all()
        u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL, is_admin=True)
        u.set_password(ADMIN_SENHA)
        db.session.add(u)
        db.session.commit()
        logger.info(f"Banco recriado e admin criado: {ADMIN_EMAIL}")


# =============================================================================
# FLASK-LOGIN
# =============================================================================

@login_manager.user_loader
def load_user(uid):
    return db.session.get(Usuario, int(uid))


# Decorator para rotas que exigem permissão de administrador
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('login'))
        if not current_user.is_admin:
            flash('❌ Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
            return redirect(url_for('dashboard'))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# ROTAS
# =============================================================================

@app.route('/')
def index():
    return redirect(url_for('dashboard') if current_user.is_authenticated else url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        u = Usuario.query.filter_by(email=email).first()

        if u and u.check_password(senha) and u.ativo:
            login_user(u)
            u.ultimo_acesso = datetime.utcnow()
            db.session.commit()
            return redirect(url_for('dashboard'))
        flash('Email ou senha incorretos', 'danger')

    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))


@app.route('/dashboard')
@login_required
def dashboard():
    # Filtrar apenas campanhas do usuario atual
    camps = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()
    for c in camps:
        c.atualizar_stats()

    ws = WhatsApp(current_user.id)
    ws_ativo = ws.ok()
    ws_conn = False
    if ws_ativo:
        ws_conn, _ = ws.conectado()

    # Estatisticas apenas das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in camps]
    stats = {
        'campanhas': len(camps),
        'contatos': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids)).count() if user_campanhas_ids else 0,
        'confirmados': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids), Contato.confirmado == True).count() if user_campanhas_ids else 0,
        'rejeitados': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids), Contato.rejeitado == True).count() if user_campanhas_ids else 0
    }

    return render_template('dashboard.html', campanhas=camps, whatsapp_ativo=ws_ativo,
                           whatsapp_conectado=ws_conn, mensagem_padrao=MENSAGEM_PADRAO, stats=stats)


@app.route('/campanha/criar', methods=['POST'])
@login_required
def criar_campanha():
    nome = request.form.get('nome', '').strip()
    msg = request.form.get('mensagem', MENSAGEM_PADRAO).strip()
    tempo = int(request.form.get('tempo_entre_envios', 15))

    # Novos campos de agendamento
    meta_diaria = int(request.form.get('meta_diaria', 50))
    horario_inicio = request.form.get('horario_inicio', '08:00')
    horario_fim = request.form.get('horario_fim', '18:00')
    dias_duracao = int(request.form.get('dias_duracao', 0))

    # Extrair hora dos horários (formato HH:MM)
    hora_inicio = int(horario_inicio.split(':')[0]) if horario_inicio else 8
    hora_fim = int(horario_fim.split(':')[0]) if horario_fim else 18

    if not nome:
        flash('Nome obrigatorio', 'danger')
        return redirect(url_for('dashboard'))

    if 'arquivo' not in request.files or not request.files['arquivo'].filename:
        flash('Selecione arquivo Excel', 'danger')
        return redirect(url_for('dashboard'))

    arq = request.files['arquivo']
    if not arq.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Arquivo deve ser Excel', 'danger')
        return redirect(url_for('dashboard'))

    camp = Campanha(
        nome=nome,
        descricao=request.form.get('descricao', ''),
        mensagem=msg,
        limite_diario=meta_diaria,  # Usar meta_diaria como limite_diario
        tempo_entre_envios=tempo,
        meta_diaria=meta_diaria,
        hora_inicio=hora_inicio,
        hora_fim=hora_fim,
        dias_duracao=dias_duracao,
        criador_id=current_user.id,
        arquivo=arq.filename
    )
    db.session.add(camp)
    db.session.commit()

    ok, erro, qtd = processar_planilha(arq, camp.id)

    if ok:
        flash(f'Campanha criada! {qtd} contatos importados.', 'success')
        # Validacao sera feita sob demanda durante o envio
    else:
        flash(f'Erro: {erro}', 'danger')
        db.session.delete(camp)
        db.session.commit()
        return redirect(url_for('dashboard'))

    return redirect(url_for('campanha_detalhe', id=camp.id))


@app.route('/campanha/<int:id>')
@login_required
def campanha_detalhe(id):
    camp = verificar_acesso_campanha(id)
    camp.atualizar_stats()

    filtro = request.args.get('filtro', 'todos')
    busca = request.args.get('busca', '').strip()
    page = request.args.get('page', 1, type=int)

    q = camp.contatos

    if filtro == 'validos':
        q = q.join(Telefone).filter(Telefone.whatsapp_valido == True).distinct()
    elif filtro == 'invalidos':
        # Contatos onde TODOS os telefones sao invalidos ou nao tem telefone
        # Dificil fazer em uma query simples, vamos filtrar por status se possivel
        # Ou usar status 'sem_whatsapp'
        q = q.filter(Contato.status == 'sem_whatsapp')
    elif filtro == 'confirmados':
        q = q.filter_by(confirmado=True)
    elif filtro == 'rejeitados':
        q = q.filter_by(rejeitado=True)
    elif filtro == 'pendentes':
        q = q.filter(Contato.status.in_(['pendente', 'pronto_envio']))
    elif filtro == 'aguardando':
        q = q.filter(Contato.status == 'enviado', Contato.confirmado == False, Contato.rejeitado == False)
    elif filtro == 'erros':
        q = q.filter(Contato.erro.isnot(None))
    elif filtro == 'nao_validados':
        q = q.join(Telefone).filter(Telefone.whatsapp_valido == None).distinct()

    if busca:
        q = q.join(Telefone).filter((Contato.nome.ilike(f'%{busca}%')) | (Telefone.numero.ilike(f'%{busca}%'))).distinct()

    contatos = q.order_by(Contato.id).paginate(page=page, per_page=50)

    return render_template('campanha.html', campanha=camp, contatos=contatos, filtro=filtro, busca=busca)


@app.route('/campanha/<int:id>/validar', methods=['POST'])
@login_required
def validar_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status in ['validando', 'em_andamento']:
        return jsonify({'erro': 'Ja em processamento'}), 400

    ws = WhatsApp(camp.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    t = threading.Thread(target=validar_campanha_bg, args=(id,))
    t.daemon = True
    t.start()

    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/iniciar', methods=['POST'])
@login_required
def iniciar_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status == 'em_andamento':
        return jsonify({'erro': 'Ja em andamento'}), 400

    # Verifica se tem pendentes ou prontos
    pendentes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhum contato para enviar'}), 400

    ws = WhatsApp(camp.criador_id)
    conn, _ = ws.conectado()
    if not conn:
        return jsonify({'erro': 'WhatsApp desconectado'}), 400

    t = threading.Thread(target=enviar_campanha_bg, args=(id,))
    t.daemon = True
    t.start()

    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/pausar', methods=['POST'])
@login_required
def pausar_campanha(id):
    camp = verificar_acesso_campanha(id)
    camp.status = 'pausada'
    camp.status_msg = 'Pausada'
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/retomar', methods=['POST'])
@login_required
def retomar_campanha(id):
    camp = verificar_acesso_campanha(id)
    # Verifica se tem pendentes ou prontos
    pendentes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhum contato pendente'}), 400

    t = threading.Thread(target=enviar_campanha_bg, args=(id,))
    t.daemon = True
    t.start()

    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar_campanha(id):
    camp = verificar_acesso_campanha(id)
    camp.status = 'cancelada'
    camp.status_msg = 'Cancelada'
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status in ['em_andamento', 'validando']:
        flash('Nao pode excluir em andamento', 'danger')
        return redirect(url_for('campanha_detalhe', id=id))

    db.session.delete(camp)
    db.session.commit()
    flash('Excluida', 'success')
    return redirect(url_for('dashboard'))


@app.route('/campanha/<int:id>/exportar')
@login_required
def exportar_campanha(id):
    camp = verificar_acesso_campanha(id)

    dados = []
    for c in camp.contatos.order_by(Contato.id).all():
        dados.append({
            'Nome': c.nome,
            'Nascimento': c.data_nascimento.strftime('%d/%m/%Y') if c.data_nascimento else '',
            'Telefones': c.telefones_str(),
            'Procedimento': c.procedimento,
            'Status': c.status_texto(),
            'Enviado': 'Sim' if c.status in ['enviado', 'aguardando_nascimento', 'concluido'] or c.confirmado or c.rejeitado else 'Nao',
            'Data Envio': max([t.data_envio for t in c.telefones if t.data_envio], default=None).strftime('%d/%m/%Y %H:%M') if any(t.data_envio for t in c.telefones) else '',
            'Confirmado': 'SIM' if c.confirmado else '',
            'Rejeitado': 'SIM' if c.rejeitado else '',
            'Resposta': c.resposta or '',
            'Data Resposta': c.data_resposta.strftime('%d/%m/%Y %H:%M') if c.data_resposta else '',
            'Erro': c.erro or ''
        })

    df = pd.DataFrame(dados)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='Contatos', index=False)
    out.seek(0)

    return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'campanha_{id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')


# API
@app.route('/api/dashboard/tickets')
@login_required
def api_dashboard_tickets():
    """Retorna estatísticas de tickets para o dashboard"""
    # Filtrar apenas tickets das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]
    if user_campanhas_ids:
        urgentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente', TicketAtendimento.prioridade == 'urgente').count()
        pendentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente').count()
    else:
        urgentes = 0
        pendentes = 0
    return jsonify({'urgentes': urgentes, 'pendentes': pendentes})


@app.route('/api/campanha/<int:id>/status')
@login_required
def api_status(id):
    camp = verificar_acesso_campanha(id)
    camp.atualizar_stats()
    return jsonify({
        'status': camp.status,
        'status_msg': camp.status_msg,
        'total_contatos': camp.total_contatos,
        'total_validos': camp.total_validos,
        'total_invalidos': camp.total_invalidos,
        'total_enviados': camp.total_enviados,
        'total_confirmados': camp.total_confirmados,
        'total_rejeitados': camp.total_rejeitados,
        'total_erros': camp.total_erros,
        'pct_validacao': camp.pct_validacao(),
        'pct_envio': camp.pct_envio(),
        'pct_confirmacao': camp.pct_confirmacao(),
        'percentual_validacao': camp.percentual_validacao(),
        'percentual_envio': camp.percentual_envio(),
        'percentual_confirmacao': camp.percentual_confirmacao(),
        'percentual_conclusao': camp.percentual_conclusao(),
        'pendentes_validar': camp.pendentes_validar(),
        'pendentes_enviar': camp.pendentes_enviar()
    })


@app.route('/api/contato/<int:id>/confirmar', methods=['POST'])
@login_required
def api_confirmar(id):
    c = verificar_acesso_contato(id)
    c.confirmado = True
    c.rejeitado = False
    c.data_resposta = datetime.utcnow()
    c.resposta = f"[Manual: {current_user.nome}]"
    c.status = 'concluido'
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/api/contato/<int:id>/rejeitar', methods=['POST'])
@login_required
def api_rejeitar(id):
    c = verificar_acesso_contato(id)
    c.rejeitado = True
    c.confirmado = False
    c.data_resposta = datetime.utcnow()
    c.resposta = f"[Manual: {current_user.nome}]"
    c.status = 'concluido'
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/api/contato/<int:id>/reenviar', methods=['POST'])
@login_required
def api_reenviar(id):
    c = verificar_acesso_contato(id)
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    c.erro = None
    msg = c.campanha.mensagem.replace('{nome}', c.nome).replace('{procedimento}', c.procedimento or 'o procedimento')

    # Enviar para TODOS os numeros validos
    tels = c.telefones.filter_by(whatsapp_valido=True).all()
    if not tels:
        return jsonify({'erro': 'Nenhum numero valido'}), 400
        
    sucesso = False
    erros = []
    
    for t in tels:
        ok, result = ws.enviar(t.numero_fmt, msg)
        if ok:
            t.enviado = True
            t.data_envio = datetime.utcnow()
            t.msg_id = result
            sucesso = True
        else:
            erros.append(result)
            
    if sucesso:
        c.status = 'enviado'
        c.erro = None
        db.session.commit()
        return jsonify({'sucesso': True})
    else:
        c.erro = "; ".join(erros)
        db.session.commit()
        return jsonify({'erro': c.erro}), 400


@app.route('/api/contato/<int:id>/revalidar', methods=['POST'])
@login_required
def api_revalidar(id):
    c = verificar_acesso_contato(id)
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    tels = c.telefones.all()
    if not tels:
        return jsonify({'erro': 'Sem telefones'}), 400
        
    nums = [t.numero_fmt for t in tels]
    result = ws.verificar_numeros(nums)
    
    tem_valido = False
    for t in tels:
        info = result.get(t.numero_fmt, {})
        t.whatsapp_valido = info.get('exists', False)
        t.jid = info.get('jid', '')
        t.data_validacao = datetime.utcnow()
        if t.whatsapp_valido:
            tem_valido = True
            
    c.erro = None
    if tem_valido:
        if c.status == 'sem_whatsapp':
            c.status = 'pendente' # ou pronto_envio
    else:
        c.status = 'sem_whatsapp'
        
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()

    return jsonify({'sucesso': True, 'valido': tem_valido})


@app.route('/contato/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_contato(id):
    c = verificar_acesso_contato(id)
    
    if request.method == 'POST':
        c.nome = request.form.get('nome', '').strip()[:200]
        c.procedimento = request.form.get('procedimento', '').strip()[:500]
        
        # Data de nascimento
        dt_nasc_str = request.form.get('data_nascimento', '').strip()
        if dt_nasc_str:
            try:
                c.data_nascimento = datetime.strptime(dt_nasc_str, '%Y-%m-%d').date()
            except:
                flash('Data de nascimento inválida', 'danger')
                return redirect(url_for('editar_contato', id=id))
        
        # Telefones - remover todos e recriar
        for t in c.telefones.all():
            db.session.delete(t)
        
        telefones_input = request.form.getlist('telefones[]')
        for i, tel_raw in enumerate(telefones_input):
            tel = tel_raw.strip()
            if not tel:
                continue
            fmt = formatar_numero(tel)
            if fmt:
                t = Telefone(
                    contato_id=c.id,
                    numero=tel[:20],
                    numero_fmt=fmt,
                    prioridade=i+1
                )
                db.session.add(t)
        
        db.session.commit()
        c.campanha.atualizar_stats()
        db.session.commit()
        
        flash('Contato atualizado com sucesso!', 'success')
        return redirect(url_for('campanha_detalhe', id=c.campanha_id))
    
    return render_template('editar_contato.html', contato=c)


# Configuracoes
@app.route('/configuracoes')
@login_required
def configuracoes():
    """
    Tela de configurações WhatsApp
    - ADMIN: Pode configurar API global (URL e Key)
    - USUÁRIO: Apenas conecta seu WhatsApp (instância criada automaticamente)
    """
    cfg_global = ConfigGlobal.get()
    cfg_user = ConfigWhatsApp.get(current_user.id)

    # Verificar status de conexão
    conectado = False
    status_msg = "Não configurado"

    if cfg_global.ativo:
        try:
            ws = WhatsApp(current_user.id)
            if ws.ok():
                conectado, status_msg = ws.conectado()
        except Exception as e:
            status_msg = f"Erro: {str(e)}"

    return render_template('configuracoes.html',
                         config_global=cfg_global,
                         config_user=cfg_user,
                         conectado=conectado,
                         status_msg=status_msg,
                         is_admin=current_user.is_admin)


@app.route('/configuracoes/global', methods=['POST'])
@login_required
@admin_required
def configuracoes_global():
    """Admin atualiza configuração global da Evolution API"""
    cfg = ConfigGlobal.get()

    cfg.evolution_api_url = request.form.get('api_url', '').strip().rstrip('/')
    cfg.evolution_api_key = request.form.get('api_key', '').strip()
    cfg.ativo = request.form.get('ativo') == 'on'
    cfg.atualizado_em = datetime.utcnow()
    cfg.atualizado_por = current_user.id
    db.session.commit()

    flash('✅ Configuração global salva com sucesso!', 'success')
    return redirect(url_for('configuracoes'))


@app.route('/api/whatsapp/conectar', methods=['POST'])
@login_required
def api_conectar_whatsapp():
    """
    Conectar WhatsApp automaticamente:
    1. Verifica config global
    2. Cria instância se necessário
    3. Retorna QR code
    """
    try:
        # Verificar se admin configurou API global
        cfg_global = ConfigGlobal.get()
        if not cfg_global.ativo or not cfg_global.evolution_api_url or not cfg_global.evolution_api_key:
            return jsonify({
                'erro': 'Sistema não configurado. Entre em contato com o administrador.'
            }), 400

        # Inicializar WhatsApp com config do usuário
        ws = WhatsApp(current_user.id)

        if not ws.ok():
            return jsonify({'erro': 'Erro ao inicializar WhatsApp'}), 500

        # Tentar criar instância (se já existir, retorna sucesso)
        sucesso_criar, msg_criar = ws.criar_instancia()

        if not sucesso_criar and 'ja existe' not in msg_criar.lower():
            return jsonify({'erro': f'Erro ao criar instância: {msg_criar}'}), 500

        # Obter QR code
        ok, result = ws.qrcode()
        if ok:
            # Atualizar status no banco
            ws.cfg_user.conectado = False  # Ainda não conectou, apenas obteve QR
            ws.cfg_user.atualizado_em = datetime.utcnow()
            db.session.commit()

            return jsonify({
                'sucesso': True,
                'qrcode': result,
                'instance_name': ws.instance
            })
        else:
            if 'conectado' in result.lower() or 'open' in result.lower():
                # Já está conectado!
                ws.cfg_user.conectado = True
                ws.cfg_user.data_conexao = datetime.utcnow()
                db.session.commit()

                return jsonify({
                    'conectado': True,
                    'mensagem': 'WhatsApp já está conectado!',
                    'instance_name': ws.instance
                })
            return jsonify({'erro': result}), 400

    except Exception as e:
        logger.error(f"Erro ao conectar WhatsApp: {str(e)}")
        return jsonify({'erro': str(e)}), 500


@app.route('/api/whatsapp/qrcode')
@login_required
def api_qrcode():
    """Obter QR code (mantido por compatibilidade, mas use /conectar)"""
    ws = WhatsApp(current_user.id)
    if not ws.ok():
        return jsonify({'erro': 'Sistema não configurado'}), 400

    ok, result = ws.qrcode()
    if ok:
        return jsonify({'qrcode': result})
    else:
        if 'conectado' in result.lower():
            return jsonify({'conectado': True, 'mensagem': result})
        return jsonify({'erro': result}), 400


@app.route('/api/whatsapp/status')
@login_required
def api_ws_status():
    ws = WhatsApp(current_user.id)
    if not ws.ok():
        return jsonify({'conectado': False, 'mensagem': 'Nao configurado'})
    conn, msg = ws.conectado()
    return jsonify({'conectado': conn, 'mensagem': msg})


# Webhook
@app.route('/webhook/whatsapp', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'ok'}), 200

        if data.get('event') != 'messages.upsert':
            return jsonify({'status': 'ok'}), 200

        msg_data = data.get('data', {})
        key = msg_data.get('key', {})
        if key.get('fromMe'):
            return jsonify({'status': 'ok'}), 200

        # Extrair o número real do WhatsApp
        # O número correto sempre termina com @s.whatsapp.net
        # O LID (Local ID) termina com @lid e deve ser ignorado
        remote_jid = key.get('remoteJid', '')
        remote_jid_alt = key.get('remoteJidAlt', '')

        # Priorizar o JID que termina com @s.whatsapp.net (número real)
        if remote_jid.endswith('@s.whatsapp.net'):
            jid = remote_jid
        elif remote_jid_alt.endswith('@s.whatsapp.net'):
            jid = remote_jid_alt
        else:
            # Fallback: se nenhum termina com @s.whatsapp.net, usa o que não é LID
            if not remote_jid.endswith('@lid'):
                jid = remote_jid
            elif not remote_jid_alt.endswith('@lid'):
                jid = remote_jid_alt
            else:
                jid = remote_jid  # Último recurso

        numero = ''.join(filter(str.isdigit, jid.replace('@s.whatsapp.net', '').replace('@lid', '')))

        # Validar se conseguiu extrair um numero valido
        if not numero:
            logger.warning(f"Webhook: Numero de telefone invalido ou vazio. JID: {jid}")
            return jsonify({'status': 'ok'}), 200

        message = msg_data.get('message', {})
        texto = (message.get('conversation') or message.get('extendedTextMessage', {}).get('text') or '').strip()

        if not texto:
            return jsonify({'status': 'ok'}), 200

        texto_up = texto.upper()
        
        # Buscar Telefone e Contato
        # Prioriza contatos NAO concluidos, depois os mais recentes
        # Tenta encontrar o telefone exato ou variacoes
        telefones = Telefone.query.filter_by(numero_fmt=numero).all()
        
        if not telefones:
            # Tenta variacao 9o digito
            if len(numero) == 12:
                num9 = numero[:4] + '9' + numero[4:]
                telefones = Telefone.query.filter_by(numero_fmt=num9).all()
            elif len(numero) == 13:
                num_sem9 = numero[:4] + numero[5:]
                telefones = Telefone.query.filter_by(numero_fmt=num_sem9).all()
        
        if not telefones:
            logger.warning(f"Webhook: Telefone nao encontrado para {numero}")
            return jsonify({'status': 'ok'}), 200
        
        # Priorizar o contato com interação mais recente
        # Isso evita loops infinitos quando há múltiplos contatos para o mesmo telefone
        c = None
        contatos_validos = [t.contato for t in telefones if t.contato]

        if contatos_validos:
            # Priorizar contatos não concluídos, mas pegar o MAIS RECENTE entre eles
            contatos_nao_concluidos = [ct for ct in contatos_validos if ct.status != 'concluido']

            if contatos_nao_concluidos:
                # Ordenar por data_resposta (mais recente primeiro), depois por id (mais novo primeiro)
                c = max(contatos_nao_concluidos, key=lambda ct: (ct.data_resposta or datetime.min, ct.id))
            else:
                # Se todos concluídos, pegar o mais recente
                c = max(contatos_validos, key=lambda ct: (ct.data_resposta or datetime.min, ct.id))
            
        if not c:
            logger.warning(f"Webhook: Contato nao encontrado")
            return jsonify({'status': 'ok'}), 200

        logger.info(f"Webhook: Mensagem de {c.nome} ({numero}). Campanha: {c.campanha_id}. Status atual: {c.status}. Texto: {texto}")

        # Análise de sentimento
        analise = AnaliseSentimento.analisar(texto)

        # Log da mensagem recebida com sentimento
        log = LogMsg(
            campanha_id=c.campanha_id,
            contato_id=c.id,
            direcao='recebida',
            telefone=numero,
            mensagem=texto[:500],
            status='ok',
            sentimento=analise['sentimento'],
            sentimento_score=analise['score']
        )
        db.session.add(log)
        db.session.commit()

        ws = WhatsApp(c.campanha.criador_id)

        # Verificar primeiro se é uma resposta válida da campanha (1, 2, 3)
        # Isso impede que respostas válidas sejam tratadas como FAQ ou tickets
        respostas_validas = (any(r in texto_up for r in RESPOSTAS_SIM) or
                            any(r in texto_up for r in RESPOSTAS_NAO) or
                            any(r in texto_up for r in RESPOSTAS_DESCONHECO))

        # Primeiro, tentar responder com FAQ automático
        # IMPORTANTE: NÃO processar FAQ se contato está em fluxo ativo da campanha
        # (status enviado/pronto_envio/aguardando_nascimento devem ir direto para a máquina de estados)
        # EXCEÇÃO: Se status é 'concluido', SEMPRE permitir FAQ (mesmo para respostas válidas como 1, 2, 3)
        resposta_faq = None
        if c.status == 'concluido' or (c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio'] and not respostas_validas):
            # Buscar FAQs globais + FAQs do criador da campanha
            usuario_id = c.campanha.criador_id if c.campanha else None
            resposta_faq = SistemaFAQ.buscar_resposta(texto, usuario_id)

        # Verificar se precisa criar ticket para atendimento humano
        # IMPORTANTE: NÃO criar ticket se está em fluxo ativo da campanha
        # EXCEÇÃO: Se status é 'concluido', permitir tickets (usuário pode ter dúvidas após confirmação)
        prioridade_ticket = None
        if c.status == 'concluido' or (c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio'] and not respostas_validas):
            prioridade_ticket = SistemaFAQ.requer_atendimento_humano(texto, c)

        # Se tem FAQ e NÃO é urgente, responde com FAQ (FAQ não responde mensagens urgentes)
        if resposta_faq and not prioridade_ticket:
            ws.enviar(numero, resposta_faq)
            logger.info(f"FAQ automático enviado para {c.nome}")
            return jsonify({'status': 'ok'}), 200

        # Se é urgente/importante mas tem FAQ, ainda assim cria ticket mas envia FAQ primeiro
        # IMPORTANTE: Não cria ticket se contato está em fluxo ativo da campanha
        # (status enviado/pronto_envio/aguardando_nascimento devem ser processados pela máquina de estados)
        if prioridade_ticket and c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio']:
            # Se tem FAQ, envia como resposta imediata antes de criar o ticket
            if resposta_faq:
                ws.enviar(numero, resposta_faq)
                logger.info(f"FAQ automático enviado antes de criar ticket para {c.nome}")

            ticket = TicketAtendimento(
                contato_id=c.id,
                campanha_id=c.campanha_id,
                mensagem_usuario=texto,
                status='pendente',
                prioridade=prioridade_ticket
            )
            db.session.add(ticket)
            db.session.commit()

            # Notificar usuário (apenas se não tinha FAQ, senão fica redundante)
            if not resposta_faq:
                if prioridade_ticket == 'urgente':
                    ws.enviar(numero, "🚨 Sua mensagem foi encaminhada com URGÊNCIA para nossa equipe. "
                                     "Um atendente entrará em contato em breve.")
                else:
                    ws.enviar(numero, "👤 Sua mensagem foi encaminhada para um atendente. "
                                     "Aguarde o retorno em até 24h úteis.")

            logger.info(f"Ticket criado para {c.nome} - Prioridade: {prioridade_ticket}")
            return jsonify({'status': 'ok'}), 200

        # Maquina de Estados
        # Aceita 'pronto_envio' tambem pois pode haver race condition (usuario responde antes do loop de envio terminar)
        # Aceita 'pendente' se a resposta é válida (1, 2, 3) - útil para testes e recuperação de erros
        if c.status in ['enviado', 'pronto_envio'] or (c.status == 'pendente' and respostas_validas):
            # Se era pendente e recebeu resposta válida, atualiza para enviado automaticamente
            if c.status == 'pendente' and respostas_validas:
                c.status = 'enviado'
                db.session.commit()
                logger.info(f"Status de {c.nome} atualizado de 'pendente' para 'enviado' após receber resposta válida")

            if any(r in texto_up for r in RESPOSTAS_SIM) or any(r in texto_up for r in RESPOSTAS_NAO):
                # Verificar se contato TEM data de nascimento cadastrada
                if c.data_nascimento:
                    # Pedir Data de Nascimento para validação
                    c.status = 'aguardando_nascimento'
                    c.resposta = texto # Guarda a intencao original (1 ou 2)
                    c.data_resposta = datetime.utcnow()
                    db.session.commit()

                    ws.enviar(numero, "🔒 Por segurança, por favor digite sua *Data de Nascimento* (ex: 03/09/1954).")
                else:
                    # NÃO tem data de nascimento - confirma/rejeita imediatamente
                    msg_final = "✅ Obrigado."

                    if any(r in texto_up for r in RESPOSTAS_SIM):
                        c.confirmado = True
                        c.rejeitado = False
                        msg_final = """✅ *Confirmação Registrada com Sucesso!*

Obrigado por confirmar seu interesse no procedimento.

📞 *Próximos Passos:*
• Nossa equipe entrará em contato em breve
• Mantenha seu telefone com notificações ativas
• Fique atento às ligações do hospital

❓ *Tem dúvidas?*
Digite sua pergunta a qualquer momento que responderemos!

_Hospital Universitário Walter Cantídio_"""
                    elif any(r in texto_up for r in RESPOSTAS_NAO):
                        c.confirmado = False
                        c.rejeitado = True
                        msg_final = """✅ *Registro Atualizado*

Obrigado por sua resposta.

Registramos que você não tem mais interesse no procedimento. Seus dados serão atualizados em nosso sistema.

Se mudar de ideia ou tiver alguma dúvida, pode entrar em contato conosco.

_Hospital Universitário Walter Cantídio_"""

                    c.status = 'concluido'
                    c.resposta = texto
                    c.data_resposta = datetime.utcnow()
                    db.session.commit()
                    c.campanha.atualizar_stats()
                    db.session.commit()

                    ws.enviar(numero, msg_final)
                
            elif any(r in texto_up for r in RESPOSTAS_DESCONHECO):
                c.rejeitado = True
                c.confirmado = False
                c.erro = "Desconhecido pelo portador"
                c.status = 'concluido'
                c.resposta = texto
                c.data_resposta = datetime.utcnow()
                db.session.commit()
                c.campanha.atualizar_stats()
                db.session.commit()

                ws.enviar(numero, """✅ *Obrigado pela informação!*

Vamos atualizar nossos registros e remover seu contato da nossa lista.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""")
                
        elif c.status == 'aguardando_nascimento':
            # Verificar Data
            dt_input = None
            try:
                # Tentar varios formatos
                for fmt in ['%d/%m/%Y', '%d-%m-%Y', '%d.%m.%Y', '%d%m%Y']:
                    try:
                        dt_input = datetime.strptime(texto.strip(), fmt).date()
                        break
                    except:
                        pass
            except:
                pass
            
            if dt_input:
                if c.data_nascimento and dt_input == c.data_nascimento:
                    # Data Correta - Verificar intencao original
                    intent_up = (c.resposta or '').upper()
                    msg_final = "✅ Obrigado."
                    
                    if any(r in intent_up for r in RESPOSTAS_SIM):
                        c.confirmado = True
                        c.rejeitado = False
                        msg_final = """✅ *Confirmação Registrada com Sucesso!*

Obrigado por confirmar seu interesse no procedimento.

📞 *Próximos Passos:*
• Nossa equipe entrará em contato em breve
• Mantenha seu telefone com notificações ativas
• Fique atento às ligações do hospital

❓ *Tem dúvidas?*
Digite sua pergunta a qualquer momento que responderemos!

_Hospital Universitário Walter Cantídio_"""
                    elif any(r in intent_up for r in RESPOSTAS_NAO):
                        c.confirmado = False
                        c.rejeitado = True
                        msg_final = """✅ *Registro Atualizado*

Obrigado por sua resposta.

Registramos que você não tem mais interesse no procedimento. Seus dados serão atualizados em nosso sistema.

Se mudar de ideia ou tiver alguma dúvida, pode entrar em contato conosco.

_Hospital Universitário Walter Cantídio_"""
                    
                    c.status = 'concluido'
                    c.data_resposta = datetime.utcnow()
                    db.session.commit()
                    c.campanha.atualizar_stats()
                    db.session.commit()
                    
                    ws.enviar(numero, msg_final)
                else:
                    # Data incorreta
                    ws.enviar(numero, "❌ Data de nascimento incorreta. Por favor, tente novamente (DD/MM/AAAA).")
            else:
                ws.enviar(numero, "⚠️ Formato inválido. Por favor, digite a data no formato DD/MM/AAAA (ex: 03/09/1954).")

        elif c.status == 'concluido':
            # Se o usuario mandar mensagem depois de concluido, reforcar o status
            # (FAQ já foi verificado no início do webhook)
            if c.confirmado:
                ws.enviar(numero, "✅ Você já confirmou seu interesse. Obrigado!")
            elif c.rejeitado:
                ws.enviar(numero, "✅ Você já informou que não tem interesse. Obrigado!")
            else:
                ws.enviar(numero, "✅ Seu atendimento já foi concluído. Obrigado!")

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        logger.error(f"Webhook erro: {e}")
        return jsonify({'status': 'error'}), 500


@app.route('/webhook/whatsapp', methods=['GET'])
def webhook_check():
    return jsonify({'status': 'ok', 'app': 'Busca Ativa HUWC'}), 200


# =============================================================================
# ROTAS - FAQ (RESPOSTAS AUTOMATICAS)
# =============================================================================

@app.route('/faq')
@login_required
def gerenciar_faq():
    # Mostrar FAQs globais + FAQs do usuário
    faqs = RespostaAutomatica.query.filter(
        db.or_(
            RespostaAutomatica.global_faq == True,
            RespostaAutomatica.criador_id == current_user.id
        )
    ).order_by(RespostaAutomatica.prioridade.desc()).all()
    return render_template('faq.html', faqs=faqs)


@app.route('/faq/criar', methods=['POST'])
@login_required
def criar_faq():
    categoria = request.form.get('categoria', '').strip()
    resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    prioridade = int(request.form.get('prioridade', 1))
    global_faq = request.form.get('global_faq') == 'on'  # Checkbox

    if not categoria or not resposta or not gatilhos_str:
        flash('Preencha todos os campos', 'danger')
        return redirect(url_for('gerenciar_faq'))

    # Apenas admin pode criar FAQs globais
    if global_faq and not current_user.is_admin:
        flash('❌ Apenas administradores podem criar FAQs globais', 'danger')
        return redirect(url_for('gerenciar_faq'))

    # Converter gatilhos de string para lista
    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]

    faq = RespostaAutomatica(
        categoria=categoria,
        resposta=resposta,
        prioridade=prioridade,
        global_faq=global_faq,
        criador_id=None if global_faq else current_user.id  # Global não tem criador
    )
    faq.set_gatilhos(gatilhos)
    db.session.add(faq)
    db.session.commit()

    tipo = 'global' if global_faq else 'privado'
    flash(f'✅ FAQ {tipo} criado com sucesso!', 'success')
    return redirect(url_for('gerenciar_faq'))


@app.route('/faq/<int:id>/editar', methods=['POST'])
@login_required
def editar_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)

    # Verificar permissões: só pode editar se for o criador OU se for global e for admin
    if faq.global_faq:
        if not current_user.is_admin:
            flash('❌ Apenas administradores podem editar FAQs globais', 'danger')
            return redirect(url_for('gerenciar_faq'))
    else:
        if faq.criador_id != current_user.id:
            flash('❌ Você não pode editar FAQs de outros usuários', 'danger')
            return redirect(url_for('gerenciar_faq'))

    faq.categoria = request.form.get('categoria', '').strip()
    faq.resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    faq.prioridade = int(request.form.get('prioridade', 1))
    faq.ativa = request.form.get('ativa') == 'on'

    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]
    faq.set_gatilhos(gatilhos)

    db.session.commit()
    flash('✅ FAQ atualizado!', 'success')
    return redirect(url_for('gerenciar_faq'))


@app.route('/faq/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)

    # Verificar permissões: só pode excluir se for o criador OU se for global e for admin
    if faq.global_faq:
        if not current_user.is_admin:
            flash('❌ Apenas administradores podem excluir FAQs globais', 'danger')
            return redirect(url_for('gerenciar_faq'))
    else:
        if faq.criador_id != current_user.id:
            flash('❌ Você não pode excluir FAQs de outros usuários', 'danger')
            return redirect(url_for('gerenciar_faq'))

    db.session.delete(faq)
    db.session.commit()
    flash('✅ FAQ excluído!', 'success')
    return redirect(url_for('gerenciar_faq'))


# =============================================================================
# ROTAS - ATENDIMENTO (TICKETS)
# =============================================================================

@app.route('/atendimento')
@login_required
def painel_atendimento():
    filtro = request.args.get('filtro', 'pendente')
    page = request.args.get('page', 1, type=int)

    # Filtrar apenas tickets das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]

    q = TicketAtendimento.query
    if user_campanhas_ids:
        q = q.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids))
    else:
        # Se nao tem campanhas, nao tem tickets
        q = q.filter(TicketAtendimento.id == None)

    if filtro == 'pendente':
        q = q.filter_by(status='pendente')
    elif filtro == 'em_atendimento':
        q = q.filter_by(status='em_atendimento')
    elif filtro == 'resolvido':
        q = q.filter_by(status='resolvido')
    elif filtro == 'meus':
        q = q.filter_by(atendente_id=current_user.id, status='em_atendimento')
    elif filtro == 'urgente':
        q = q.filter_by(prioridade='urgente', status='pendente')

    tickets = q.order_by(
        TicketAtendimento.prioridade.desc(),
        TicketAtendimento.data_criacao.asc()
    ).paginate(page=page, per_page=20)

    # Estatísticas apenas dos tickets das campanhas do usuario
    if user_campanhas_ids:
        stats = {
            'pendente': TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente').count(),
            'em_atendimento': TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'em_atendimento').count(),
            'urgente': TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.prioridade == 'urgente', TicketAtendimento.status == 'pendente').count(),
            'resolvido_hoje': TicketAtendimento.query.filter(
                TicketAtendimento.campanha_id.in_(user_campanhas_ids),
                TicketAtendimento.status == 'resolvido',
                TicketAtendimento.data_resolucao >= datetime.utcnow().replace(hour=0, minute=0, second=0)
            ).count()
        }
    else:
        stats = {'pendente': 0, 'em_atendimento': 0, 'urgente': 0, 'resolvido_hoje': 0}

    return render_template('atendimento.html', tickets=tickets, filtro=filtro, stats=stats)


@app.route('/atendimento/<int:id>')
@login_required
def detalhe_ticket(id):
    ticket = verificar_acesso_ticket(id)
    # Buscar histórico de mensagens do contato
    logs = LogMsg.query.filter_by(contato_id=ticket.contato_id).order_by(LogMsg.data.desc()).limit(20).all()
    return render_template('ticket_detalhe.html', ticket=ticket, logs=logs)


@app.route('/atendimento/<int:id>/assumir', methods=['POST'])
@login_required
def assumir_ticket(id):
    ticket = verificar_acesso_ticket(id)

    if ticket.status != 'pendente':
        flash('Ticket já está em atendimento', 'warning')
        return redirect(url_for('detalhe_ticket', id=id))

    ticket.status = 'em_atendimento'
    ticket.atendente_id = current_user.id
    ticket.data_atendimento = datetime.utcnow()
    db.session.commit()

    flash('Ticket assumido!', 'success')
    return redirect(url_for('detalhe_ticket', id=id))


@app.route('/atendimento/<int:id>/responder', methods=['POST'])
@login_required
def responder_ticket(id):
    ticket = verificar_acesso_ticket(id)
    resposta = request.form.get('resposta', '').strip()

    if not resposta:
        flash('Digite uma resposta', 'danger')
        return redirect(url_for('detalhe_ticket', id=id))

    # Enviar via WhatsApp usando a instância do criador da campanha
    ws = WhatsApp(ticket.campanha.criador_id)

    # Priorizar telefones validados, mas aceitar todos se não houver validados
    telefones_validados = ticket.contato.telefones.filter_by(whatsapp_valido=True).all()
    telefones_todos = ticket.contato.telefones.all()

    # Usar validados se houver, senão usar todos
    telefones = telefones_validados if telefones_validados else telefones_todos

    if not telefones:
        flash('Nenhum telefone cadastrado para este contato', 'danger')
        return redirect(url_for('detalhe_ticket', id=id))

    enviado = False
    erro_msg = None
    for tel in telefones:
        ok, resultado = ws.enviar(tel.numero_fmt, f"👤 *Resposta do atendente {current_user.nome}:*\n\n{resposta}")
        if ok:
            enviado = True

            # Registrar log
            log = LogMsg(
                campanha_id=ticket.campanha_id,
                contato_id=ticket.contato_id,
                direcao='enviada',
                telefone=tel.numero_fmt,
                mensagem=f'[Atendimento] {resposta}',
                status='ok'
            )
            db.session.add(log)
            break
        else:
            erro_msg = resultado

    if enviado:
        # Resolver ticket
        ticket.status = 'resolvido'
        ticket.data_resolucao = datetime.utcnow()
        ticket.resposta = resposta
        db.session.commit()

        flash('✅ Resposta enviada e ticket resolvido com sucesso!', 'success')
    else:
        msg_erro = f'❌ Erro ao enviar resposta via WhatsApp'
        if erro_msg:
            msg_erro += f': {erro_msg}'
        flash(msg_erro, 'danger')

    return redirect(url_for('painel_atendimento'))


@app.route('/atendimento/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar_ticket(id):
    ticket = verificar_acesso_ticket(id)
    ticket.status = 'cancelado'
    db.session.commit()
    flash('Ticket cancelado', 'info')
    return redirect(url_for('painel_atendimento'))


# =============================================================================
# ROTAS - CADASTRO PUBLICO
# =============================================================================

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro_publico():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        senha_confirm = request.form.get('senha_confirm', '')

        # Validações
        if not nome or not email or not senha:
            flash('Preencha todos os campos', 'danger')
            return render_template('cadastro.html')

        if len(senha) < 6:
            flash('Senha deve ter no mínimo 6 caracteres', 'danger')
            return render_template('cadastro.html')

        if senha != senha_confirm:
            flash('As senhas não coincidem', 'danger')
            return render_template('cadastro.html')

        # Verificar se email já existe
        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado', 'danger')
            return render_template('cadastro.html')

        # Criar usuário
        usuario = Usuario(nome=nome, email=email, ativo=True)
        usuario.set_password(senha)
        db.session.add(usuario)
        db.session.commit()

        flash('Cadastro realizado com sucesso! Faça login.', 'success')
        return redirect(url_for('login'))

    return render_template('cadastro.html')


# =============================================================================
# ROTAS - TUTORIAL
# =============================================================================

@app.route('/tutorial')
@login_required
def tutorial():
    categoria = request.args.get('categoria', 'inicio')
    tutoriais = Tutorial.query.filter_by(ativo=True, categoria=categoria).order_by(Tutorial.ordem).all()

    # Se não encontrou, pegar todos
    if not tutoriais:
        tutoriais = Tutorial.query.filter_by(ativo=True).order_by(Tutorial.categoria, Tutorial.ordem).all()

    return render_template('tutorial.html', tutoriais=tutoriais, categoria=categoria)


@app.route('/tutorial/<int:id>')
@login_required
def tutorial_detalhe(id):
    tutorial = Tutorial.query.get_or_404(id)
    return render_template('tutorial_detalhe.html', tutorial=tutorial)


# =============================================================================
# ROTAS - FOLLOW-UP (JOB)
# =============================================================================

@app.route('/followup/configurar', methods=['GET', 'POST'])
@login_required
def configurar_followup():
    config = ConfigTentativas.get()

    if request.method == 'POST':
        config.max_tentativas = int(request.form.get('max_tentativas', 3))
        config.intervalo_dias = int(request.form.get('intervalo_dias', 3))
        config.ativo = request.form.get('ativo') == 'on'
        db.session.commit()
        flash('Configuração salva!', 'success')
        return redirect(url_for('configurar_followup'))

    return render_template('followup_config.html', config=config)


@app.route('/followup/processar', methods=['POST'])
@login_required
def processar_followup_manual():
    """Executar follow-up manualmente (para testes)"""
    threading.Thread(target=processar_followup_bg).start()
    flash('Follow-up iniciado em background', 'info')
    return redirect(url_for('dashboard'))


# =============================================================================
# ROTAS - DASHBOARD DE SENTIMENTOS
# =============================================================================

@app.route('/sentimentos')
@login_required
def dashboard_sentimentos():
    # Estatísticas gerais
    stats_sentimento = db.session.query(
        LogMsg.sentimento,
        db.func.count(LogMsg.id)
    ).filter(
        LogMsg.direcao == 'recebida',
        LogMsg.sentimento.isnot(None)
    ).group_by(LogMsg.sentimento).all()

    # Tickets por prioridade
    stats_tickets = db.session.query(
        TicketAtendimento.prioridade,
        db.func.count(TicketAtendimento.id)
    ).filter_by(status='pendente').group_by(TicketAtendimento.prioridade).all()

    # FAQs mais usadas
    faqs_top = RespostaAutomatica.query.filter(
        RespostaAutomatica.contador_uso > 0
    ).order_by(RespostaAutomatica.contador_uso.desc()).limit(10).all()

    return render_template('sentimentos.html',
                         stats_sentimento=dict(stats_sentimento),
                         stats_tickets=dict(stats_tickets),
                         faqs_top=faqs_top)


# Logs
@app.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)
    camp_id = request.args.get('campanha_id', type=int)
    direcao = request.args.get('direcao')

    q = LogMsg.query
    if camp_id:
        q = q.filter_by(campanha_id=camp_id)
    if direcao:
        q = q.filter_by(direcao=direcao)

    logs = q.order_by(LogMsg.data.desc()).paginate(page=page, per_page=100)
    # Filtrar apenas campanhas do usuario atual
    camps = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()

    return render_template('logs.html', logs=logs, campanhas=camps, campanha_id=camp_id, direcao=direcao)


@app.route('/relatorios')
@login_required
def relatorios():
    """Página de relatórios com dashboard executivo"""
    # Filtrar apenas campanhas do usuario atual
    campanhas = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()

    # Se houver uma campanha selecionada via query param
    campanha_id = request.args.get('campanha_id', type=int)
    campanha_selecionada = None
    if campanha_id:
        # Verificar se a campanha pertence ao usuario
        campanha_selecionada = Campanha.query.filter_by(id=campanha_id, criador_id=current_user.id).first()

    return render_template('relatorios.html',
                          campanhas=campanhas,
                          campanha_selecionada=campanha_selecionada)


@app.route('/api/relatorios/<int:campanha_id>')
@login_required
def api_relatorios(campanha_id):
    """API para retornar dados de relatórios de uma campanha específica"""
    campanha = verificar_acesso_campanha(campanha_id)

    # Atualizar estatísticas
    campanha.atualizar_stats()
    db.session.commit()

    # Buscar contatos da campanha
    contatos = Contato.query.filter_by(campanha_id=campanha_id).all()

    # Preparar dados dos contatos para a tabela
    contatos_data = []
    for contato in contatos:
        # Buscar o primeiro telefone do contato
        telefone_obj = Telefone.query.filter_by(contato_id=contato.id).first()
        telefone_str = telefone_obj.numero if telefone_obj else None
        data_envio = telefone_obj.data_envio if telefone_obj and telefone_obj.data_envio else None

        contatos_data.append({
            'id': contato.id,
            'nome': contato.nome,
            'telefone': telefone_str,
            'procedimento': contato.procedimento,
            'status': contato.status,
            'confirmado': contato.confirmado,
            'rejeitado': contato.rejeitado,
            'erro': contato.erro,
            'data_envio': data_envio.isoformat() if data_envio else None,
            'resposta': contato.resposta
        })

    return jsonify({
        'campanha_id': campanha.id,
        'campanha_nome': campanha.nome,
        'total_contatos': campanha.total_contatos,
        'total_enviados': campanha.total_enviados,
        'total_confirmados': campanha.total_confirmados,
        'total_rejeitados': campanha.total_rejeitados,
        'total_erros': campanha.total_erros,
        'contatos': contatos_data
    })


# CLI
@app.cli.command('init-db')
def init_db():
    db.create_all()
    criar_admin()
    print(f"DB criado! Admin: {ADMIN_EMAIL} / {ADMIN_SENHA}")


# Init
with app.app_context():
    db.create_all()
    criar_admin()
    criar_faqs_padrao()
    criar_tutoriais_padrao()


if __name__ == '__main__':
    debug = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)
