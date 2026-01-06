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
from sqlalchemy.exc import IntegrityError
import pandas as pd
import os
import threading
import time
import logging
import requests
import json
from io import BytesIO
import pytz

# Timezone de Fortaleza (UTC-3)
TZ_FORTALEZA = pytz.timezone('America/Fortaleza')

def obter_agora_fortaleza():
    """Retorna datetime atual no fuso horário de Fortaleza"""
    return datetime.now(TZ_FORTALEZA)

def obter_hora_fortaleza():
    """Retorna apenas a hora atual no fuso horário de Fortaleza (0-23)"""
    return datetime.now(TZ_FORTALEZA).hour

def obter_hoje_fortaleza():
    """Retorna a data de hoje no fuso horário de Fortaleza"""
    return datetime.now(TZ_FORTALEZA).date()

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

from flask_wtf.csrf import CSRFProtect

# Importar Celery app configurado com backend Redis
try:
    from celery_app import celery as celery_app
    from celery.result import AsyncResult
except ImportError as e:
    celery_app = None
    AsyncResult = None
    logger.warning(f"Celery não disponível - funcionalidades assíncronas desabilitadas: {e}")

app = Flask(__name__)
csrf = CSRFProtect(app)
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

# RESPOSTAS VÁLIDAS - DEVEM SER EXATAS (não aceita palavras soltas em frases)
RESPOSTAS_SIM = [
    'SIM', 'S', '1',
    'CONFIRMO', 'CONFIRMADO',
    'TENHO INTERESSE', 'ACEITO', 'OK'
]
RESPOSTAS_NAO = [
    'NAO', 'NÃO', 'N', '2',
    'NAO QUERO', 'NÃO QUERO',
    'NAO TENHO INTERESSE', 'NÃO TENHO INTERESSE'
]
RESPOSTAS_DESCONHECO = [
    '3', 'DESCONHECO', 'DESCONHEÇO',
    'NAO SOU', 'NÃO SOU',
    'ENGANO', 'NUMERO ERRADO', 'NÚMERO ERRADO'
]

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
    tipo_sistema = db.Column(db.String(50), default='BUSCA_ATIVA')  # BUSCA_ATIVA ou AGENDAMENTO_CONSULTA
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

    # Response tracking per phone number
    resposta = db.Column(db.Text)
    data_resposta = db.Column(db.DateTime)
    tipo_resposta = db.Column(db.String(20))  # 'confirmado', 'rejeitado', 'desconheco', null
    validacao_pendente = db.Column(db.Boolean, default=False)  # waiting for birth date validation

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


class RespostaAutomatica(db.Model):
    __tablename__ = 'respostas_automaticas'
    id = db.Column(db.Integer, primary_key=True)
    categoria = db.Column(db.String(50), nullable=False)
    gatilhos = db.Column(db.Text)  # JSON string com lista de palavras
    resposta = db.Column(db.Text, nullable=False)
    ativa = db.Column(db.Boolean, default=True)
    prioridade = db.Column(db.Integer, default=1)
    contador_uso = db.Column(db.Integer, default=0)
    criador_id = db.Column(db.Integer, db.ForeignKey('usuarios.id', ondelete='SET NULL'))  # NOVO - FAQ privado do usuário
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
        termo_original_upper = termo_original.upper().strip()

        try:
            # Verificar se já existe um registro com este termo_original
            proc = cls.query.filter_by(termo_original=termo_original_upper).first()

            if proc:
                # Atualizar registro existente
                proc.termo_normalizado = termo_normalizado
                proc.termo_simples = termo_simples
                proc.explicacao = explicacao
                proc.fonte = fonte
                proc.atualizado_em = datetime.utcnow()
            else:
                # Criar novo registro
                proc = cls(
                    termo_original=termo_original_upper,
                    termo_normalizado=termo_normalizado,
                    termo_simples=termo_simples,
                    explicacao=explicacao,
                    fonte=fonte
                )
                db.session.add(proc)

            db.session.commit()
            return proc

        except IntegrityError:
            # Em caso de erro de integridade (ex: duplicate key), fazer rollback e tentar atualizar
            db.session.rollback()
            proc = cls.query.filter_by(termo_original=termo_original_upper).first()
            if proc:
                proc.termo_normalizado = termo_normalizado
                proc.termo_simples = termo_simples
                proc.explicacao = explicacao
                proc.fonte = fonte
                proc.atualizado_em = datetime.utcnow()
                db.session.commit()
                return proc
            else:
                raise
        except Exception as e:
            # Para qualquer outro erro, fazer rollback
            db.session.rollback()
            logging.error(f"Erro ao salvar normalização: {str(e)}")
            raise


# =============================================================================
# MODELOS - MODO CONSULTA (Agendamento de Consultas)
# =============================================================================

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

# =============================================================================
# FUNÇÕES DE OCR - EXTRAÇÃO DE DADOS DO COMPROVANTE
# =============================================================================

def extrair_dados_comprovante(filepath):
    """
    Extrai dados do comprovante de consulta usando OCR.
    Suporta PDF, JPG e PNG.

    Retorna dict com:
    - paciente: nome do paciente
    - data: data da consulta (ex: "16/01/2026")
    - hora: horário da consulta (ex: "07:00")
    - medico: nome do médico
    - especialidade: especialidade médica
    - raw_text: texto completo extraído
    """
    import re

    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.warning("pytesseract ou PIL não disponível para OCR")
        return None

    dados = {
        'paciente': None,
        'data': None,
        'hora': None,
        'medico': None,
        'especialidade': None,
        'raw_text': ''
    }

    try:
        ext = os.path.splitext(filepath)[1].lower()
        images = []

        # Converter PDF para imagens se necessário
        if ext == '.pdf':
            try:
                from pdf2image import convert_from_path
                images = convert_from_path(filepath, dpi=300)
            except ImportError:
                logger.warning("pdf2image não disponível para processar PDF")
                return None
            except Exception as e:
                logger.error(f"Erro ao converter PDF para imagem: {e}")
                return None
        else:
            # Carregar imagem diretamente
            images = [Image.open(filepath)]

        # Extrair texto de todas as páginas/imagens
        full_text = ''
        for img in images:
            # Configurar pytesseract para português
            text = pytesseract.image_to_string(img, lang='por')
            full_text += text + '\n'

        dados['raw_text'] = full_text
        logger.info(f"OCR extraído ({len(full_text)} chars): {full_text[:200]}...")

        # Padrões de regex para extrair campos
        # Paciente: procura por "Paciente:" ou "Nome:" seguido do nome
        paciente_patterns = [
            r'Paciente[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|Data)',
            r'Nome[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|Data)',
            r'PACIENTE[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
        ]
        for pattern in paciente_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                dados['paciente'] = match.group(1).strip()
                break

        # Data: procura por padrão DD/MM/YYYY
        data_patterns = [
            r'Data[:\s]+(\d{2}/\d{2}/\d{4})',
            r'(\d{2}/\d{2}/\d{4})',
        ]
        for pattern in data_patterns:
            match = re.search(pattern, full_text)
            if match:
                dados['data'] = match.group(1)
                break

        # Hora: procura por padrão HH:MM
        # Padrões específicos primeiro (maior prioridade) para evitar capturar horário de impressão
        hora_patterns = [
            r'Hora[:\s]+(\d{2}:\d{2})',                    # "Hora: 07:00"
            r'Horário[:\s]+(\d{2}:\d{2})',                 # "Horário: 14:42"
            r'(?:às|as)[:\s]+(\d{2}:\d{2})',              # "às 07:00"
            # Padrão genérico apenas como último recurso
            # Evita capturar horários de cabeçalho (que geralmente têm data antes)
            r'(?<![\d/])\s+(\d{2}:\d{2})(?:h|hs|hrs)?(?!\s*[\d/])',  # Evita "11/12/2025 14:52"
        ]
        for pattern in hora_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                dados['hora'] = match.group(1)
                break

        # Médico/Profissional
        medico_patterns = [
            r'Profissional[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|Unidade)',
            r'Médico[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
            r'Dr\.?\s*([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
            r'Dra\.?\s*([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
        ]
        for pattern in medico_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                dados['medico'] = match.group(1).strip()
                break

        # Especialidade/Unidade Funcional
        especialidade_patterns = [
            r'Unidade\s+Funcional[:\s]+(?:AMBULATÓRIO\s+)?([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|\.|,)',
            r'Especialidade[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
            r'AMBULATÓRIO\s+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|\.|,)',
        ]
        for pattern in especialidade_patterns:
            match = re.search(pattern, full_text, re.IGNORECASE)
            if match:
                dados['especialidade'] = match.group(1).strip()
                break

        logger.info(f"Dados extraídos do comprovante: {dados}")
        return dados

    except Exception as e:
        logger.exception(f"Erro ao extrair dados do comprovante via OCR: {e}")
        return None


# =============================================================================
# FUNÇÕES DE MENSAGENS - MODO CONSULTA
# =============================================================================

def formatar_data_consulta(data_str):
    """
    Formata a data da consulta para exibição na mensagem.
    Remove timestamps como "00:00:00" e formata no padrão DD/MM/YYYY.
    
    Exemplos de entrada:
    - "2024-05-20 00:00:00" -> "20/05/2024"
    - "5/20/2024" -> "20/05/2024"
    - "20/05/2024" -> "20/05/2024"
    """
    if not data_str or not str(data_str).strip():
        return "-"
    
    data_str = str(data_str).strip()
    
    # Remover timestamp se existir (ex: "2024-05-20 00:00:00")
    if ' ' in data_str:
        data_str = data_str.split(' ')[0]
    
    try:
        from datetime import datetime
        
        # Tentar diferentes formatos de entrada
        formatos = [
            '%Y-%m-%d',      # 2024-05-20
            '%d/%m/%Y',      # 20/05/2024
            '%m/%d/%Y',      # 5/20/2024
            '%d-%m-%Y',      # 20-05-2024
        ]
        
        for fmt in formatos:
            try:
                data_obj = datetime.strptime(data_str, fmt)
                # Retorna no formato brasileiro DD/MM/YYYY
                return data_obj.strftime('%d/%m/%Y')
            except ValueError:
                continue
        
        # Se nenhum formato funcionou, retorna o original
        return data_str
        
    except Exception:
        return data_str

def enviar_e_registrar_consulta(ws, telefone, mensagem, consulta):
    """
    Envia mensagem via WhatsApp e registra no log automaticamente.
    Isso garante que todas as mensagens enviadas apareçam no chat.
    """
    ok, result = ws.enviar(telefone, mensagem)
    
    # Registrar no log independente do resultado
    log = LogMsgConsulta(
        campanha_id=consulta.campanha_id,
        consulta_id=consulta.id,
        direcao='enviada',
        telefone=telefone,
        mensagem=mensagem[:500],
        status='sucesso' if ok else 'erro',
        msg_id=result if ok else None,
        erro=str(result)[:200] if not ok else None
    )
    db.session.add(log)
    db.session.commit()
    
    return ok, result

def obter_saudacao_dinamica():
    """
    Retorna saudação apropriada baseada na hora atual (fuso de Fortaleza/Brasil UTC-3).
    - Bom dia! (6h - 11h59)
    - Boa tarde! (12h - 17h59)
    - Boa noite! (18h - 5h59)
    """
    hora_atual = obter_hora_fortaleza()

    if 6 <= hora_atual < 12:
        return "Bom dia!"
    elif 12 <= hora_atual < 18:
        return "Boa tarde!"
    else:
        return "Boa noite!"


def formatar_mensagem_consulta_inicial(consulta):
    """
    MSG 1: Mensagem inicial de confirmação de consulta (enviada automaticamente)
    Enviada para: TODOS (RETORNO e INTERCONSULTA)
    Status: AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO
    """
    saudacao = obter_saudacao_dinamica()
    return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.
Estamos informando que a *CONSULTA* do paciente *{consulta.paciente}*, foi *MARCADA* para o dia *{formatar_data_consulta(consulta.data_aghu)}*, com *{consulta.medico_solicitante}*, com especialidade em *{consulta.especialidade}*.

Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_consulta_retry1(consulta):
    """
    MSG 1 RETRY: Primeira tentativa de recontato (8h após envio inicial)
    """
    saudacao = obter_saudacao_dinamica()
    return f"""{saudacao}

📋 *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*

Ainda não recebemos sua confirmação para a consulta de *{consulta.paciente}*.

*Dados da consulta:*
📅 Data: *{formatar_data_consulta(consulta.data_aghu)}*
👨‍⚕️ Médico: *{consulta.medico_solicitante}*
🏥 Especialidade: *{consulta.especialidade}*

⚠️ *IMPORTANTE:* Caso não haja confirmação em até 1 dia útil, sua consulta será cancelada!

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_consulta_retry2(consulta):
    """
    MSG 1 RETRY FINAL: Segunda e última tentativa de recontato (16h após envio inicial)
    """
    saudacao = obter_saudacao_dinamica()
    return f"""{saudacao}

🚨 *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*
⚠️ *ÚLTIMA TENTATIVA DE CONTATO*

Esta é nossa *ÚLTIMA TENTATIVA* antes do cancelamento automático da consulta de *{consulta.paciente}*.

*Dados da consulta:*
📅 Data: *{formatar_data_consulta(consulta.data_aghu)}*
👨‍⚕️ Médico: *{consulta.medico_solicitante}*
🏥 Especialidade: *{consulta.especialidade}*

❌ *Se não recebermos sua resposta, a consulta será CANCELADA automaticamente.*

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""



def formatar_mensagem_comprovante(consulta=None, dados_ocr=None):
    """
    MSG 2: Mensagem de comprovante (enviada manualmente com arquivo anexo)
    Enviada para: Consultas com status AGUARDANDO_COMPROVANTE
    Status: AGUARDANDO_COMPROVANTE → CONFIRMADO

    Args:
        consulta: Objeto AgendamentoConsulta (opcional, para fallback)
        dados_ocr: Dict com dados extraídos do comprovante via OCR (opcional)
                   Keys: paciente, data, hora, medico, especialidade
    """
    # Prioriza dados do OCR, com fallback para dados da consulta
    paciente = None
    data = None
    hora = None
    medico = None
    especialidade = None

    if dados_ocr:
        paciente = dados_ocr.get('paciente')
        data = dados_ocr.get('data')
        hora = dados_ocr.get('hora')
        medico = dados_ocr.get('medico')
        especialidade = dados_ocr.get('especialidade')

    # Fallback para dados da consulta se OCR não extraiu
    if consulta:
        if not paciente:
            paciente = consulta.paciente
        if not data:
            data = consulta.data_aghu
        if not medico:
            medico = consulta.medico_solicitante or consulta.grade_aghu
        if not especialidade:
            especialidade = consulta.especialidade

    # Formata dados para exibição
    paciente_str = paciente if paciente else 'Paciente'
    data_str = data if data else '-'
    hora_str = hora if hora else '-'
    medico_str = medico if medico else '-'
    especialidade_str = especialidade if especialidade else '-'

    return f"""O Hospital Walter Cantídio agradece seu contato. *CONSULTA CONFIRMADA!*

*Paciente:* *{paciente_str}*
*Data:* *{data_str}*
*Horário:* *{hora_str}*
*Médico(a):* *{medico_str}*
*Especialidade:* *{especialidade_str}*

O hospital entra em contato através do: (85) 992081534 / (85)996700783 / (85)991565903 / (85) 992614237 / (85) 992726080. É importante que atenda as ligações e responda as mensagens desses números. Por tanto, salve-os!

Confira seu comprovante: data, horário e nome do(a) médico(a).

Não fazemos marcação de exames, apenas consultas.

Caso falte, procurar o ambulatório para ser colocado novamente no pré-agendamento.

Você sabia que pode verificar sua consulta no app HU Digital? https://play.google.com/store/apps/details?id=br.gov.ebserh.hudigital&pcampaignid=web_share . Após 5 horas dessa mensagem, verifique sua consulta agendada no app.

Reagendamentos estarão presentes no app HU Digital. Verifique sempre o app HU Digital."""


def formatar_mensagem_perguntar_motivo():
    """
    MSG 3A: Pergunta motivo da rejeição (enviada automaticamente)
    Enviada para: TODOS que respondem NÃO na MSG 1
    Status: AGUARDANDO_CONFIRMACAO → AGUARDANDO_MOTIVO_REJEICAO
    """
    return """Entendemos sua decisão.

Poderia nos informar o *motivo* da recusa? Isso nos ajuda a melhorar nosso atendimento.

(Pode responder livremente com o motivo)"""


def formatar_mensagem_voltar_posto(consulta):
    """
    MSG 3B: Orientação para voltar ao posto (enviada automaticamente)
    Enviada para: INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = SIM
    Status: AGUARDANDO_MOTIVO_REJEICAO → REJEITADO
    """
    return f"""HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com {consulta.paciente}? Sua consulta para o serviço de {consulta.especialidade} foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!"""


def formatar_mensagem_interconsulta_aprovada(consulta):
    """
    MSG INTERCONSULTA APROVADA: Mensagem de aprovação para interconsulta (sem necessidade de ir ao posto)
    Enviada para: INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = NÃO (quando paciente responde SIM)
    Status: AGUARDANDO_CONFIRMACAO → CONFIRMADO
    """
    return f"""✅ *HOSPITAL WALTER CANTÍDIO*

Olá, {consulta.paciente}!

Solicitação de interconsulta avaliada e aprovada para marcação no HUWC, em breve entraremos em contato informando a data da consulta.

Especialidade: *{consulta.especialidade}*

_Hospital Universitário Walter Cantídio_"""


def formatar_mensagem_confirmacao_rejeicao(consulta):
    """
    MSG CONFIRMAÇÃO REJEIÇÃO: Mensagem de confirmação após paciente informar motivo
    Enviada para: Consultas que foram rejeitadas pelo paciente (após informar motivo)
    Status: AGUARDANDO_MOTIVO_REJEICAO → REJEITADO
    """
    return f"""✅ *HOSPITAL WALTER CANTÍDIO*

Entendido, {consulta.paciente}.

Sua consulta de *{consulta.especialidade}* foi cancelada conforme solicitado.

Caso precise reagendar, entre em contato com o seu ambulatório para ser inserida novamente e aguardar nova data.

Obrigado!

_Hospital Universitário Walter Cantídio_"""


def formatar_mensagem_cancelamento_sem_resposta(consulta):
    """
    MSG CANCELAMENTO: Mensagem de cancelamento por falta de resposta
    Enviada para: Consultas que não responderam após 24h e 2 tentativas adicionais
    Status: AGUARDANDO_CONFIRMACAO → CANCELADO
    """
    return f"""❌ *HOSPITAL WALTER CANTÍDIO*

Olá, {consulta.paciente}.

Não recebemos sua confirmação para a consulta de *{consulta.especialidade}* marcada para *{formatar_data_consulta(consulta.data_aghu)}*.

Sua consulta foi *CANCELADA* por falta de resposta.

Caso ainda tenha interesse, procure o posto de saúde para reagendar.

_Hospital Universitário Walter Cantídio_"""


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
        prompt = f"""Você é um assistente médico especializado em comunicação com pacientes de um hospital de referência.

TAREFA: Simplifique o seguinte termo médico técnico para uma linguagem clara e profissional que pacientes possam entender.

TERMO MÉDICO: {procedimento}

DIRETRIZES OBRIGATÓRIAS:
- Use linguagem FORMAL e PROFISSIONAL apropriada para hospital de referência
- Prefira estruturas DIRETAS: "CIRURGIA NO/NA/NOS/NAS [ÓRGÃO]"
- Mantenha SIMPLICIDADE sem perder o profissionalismo
- Evite termos coloquiais ou infantilizados ("tubinho", "machucado", "ferida")
- Use nomes anatômicos simples (rim, joelho, bexiga, coração)

RETORNE UM JSON com:
1. "termo_normalizado": Nome profissional simplificado (máximo 70 caracteres)
2. "termo_simples": Versão DIRETA e PROFISSIONAL (máximo 50 caracteres)
3. "explicacao": Breve explicação em 1 linha do que é o procedimento

EXEMPLOS DE FORMATO CORRETO:
{{
  "termo_normalizado": "Cirurgia para correção de hérnia inguinal",
  "termo_simples": "CIRURGIA DE HÉRNIA",
  "explicacao": "Procedimento cirúrgico para reparar hérnia na região da virilha"
}}

{{
  "termo_normalizado": "Cirurgia para colocação de cateter urinário duplo",
  "termo_simples": "CIRURGIA NA BEXIGA",
  "explicacao": "Procedimento para instalar cateter especial que drena a urina"
}}

{{
  "termo_normalizado": "Cirurgia para retirada de pedras do rim",
  "termo_simples": "RETIRADA DE PEDRAS DO RIM",
  "explicacao": "Procedimento para retirar pedras (cálculos) do rim"
}}

{{
  "termo_normalizado": "Artroplastia total do joelho",
  "termo_simples": "CIRURGIA NO JOELHO",
  "explicacao": "Substituição cirúrgica da articulação do joelho"
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

    def _chamar_api_batch(self, procedimentos_list):
        """Chama a API DeepSeek para normalizar múltiplos procedimentos de uma vez"""
        if not procedimentos_list:
            return {}

        procedimentos_numerados = "\n".join([f"{i+1}. {proc}" for i, proc in enumerate(procedimentos_list)])

        prompt = f"""Você é um assistente médico especializado em comunicação com pacientes de um hospital de referência.

TAREFA: Simplifique os seguintes termos médicos técnicos para uma linguagem clara e profissional que pacientes possam entender.

TERMOS MÉDICOS:
{procedimentos_numerados}

DIRETRIZES OBRIGATÓRIAS:
- Use linguagem FORMAL e PROFISSIONAL apropriada para hospital de referência
- Prefira estruturas DIRETAS: "CIRURGIA NO/NA/NOS/NAS [ÓRGÃO]"
- Mantenha SIMPLICIDADE sem perder o profissionalismo
- Evite termos coloquiais ou infantilizados ("tubinho", "machucado", "ferida")
- Use nomes anatômicos simples (rim, joelho, bexiga, coração)

RETORNE UM JSON ARRAY onde cada objeto contém:
1. "termo_original": O termo médico original (EXATAMENTE como fornecido)
2. "termo_normalizado": Nome profissional simplificado (máximo 70 caracteres)
3. "termo_simples": Versão DIRETA e PROFISSIONAL (máximo 50 caracteres)
4. "explicacao": Breve explicação em 1 linha do que é o procedimento

EXEMPLOS DE FORMATO CORRETO:
[
  {{
    "termo_original": "INSTALACAO ENDOSCOPICA DE CATETER DUPLO J",
    "termo_normalizado": "Cirurgia para colocação de cateter urinário duplo",
    "termo_simples": "CIRURGIA NA BEXIGA",
    "explicacao": "Procedimento para instalar cateter especial que drena a urina"
  }},
  {{
    "termo_original": "NEFROLITOTOMIA PERCUTANEA",
    "termo_normalizado": "Cirurgia para remoção de cálculo renal",
    "termo_simples": "CIRURGIA NO RIM",
    "explicacao": "Procedimento para retirar pedras do rim"
  }},
  {{
    "termo_original": "ARTROPLASTIA TOTAL PRIMARIA DO JOELHO",
    "termo_normalizado": "Artroplastia total do joelho",
    "termo_simples": "CIRURGIA NO JOELHO",
    "explicacao": "Substituição cirúrgica da articulação do joelho"
  }}
]

Responda APENAS com o JSON ARRAY, sem texto adicional. Normalize TODOS os {len(procedimentos_list)} procedimentos fornecidos."""

        headers = {
            'Authorization': f'Bearer {self.api_key}',
            'Content-Type': 'application/json'
        }

        payload = {
            'model': self.model,
            'messages': [
                {'role': 'user', 'content': prompt}
            ],
            'temperature': 0.3,
            'max_tokens': 8000  # Aumentado para acomodar múltiplos procedimentos
        }

        try:
            logger.info(f"[BATCH API] Enviando requisição para {len(procedimentos_list)} procedimentos...")
            inicio = time.time()

            response = requests.post(
                f'{self.base_url}/chat/completions',
                headers=headers,
                json=payload,
                timeout=60  # Timeout maior para batch
            )

            tempo_resposta = time.time() - inicio
            logger.info(f"[BATCH API] Resposta recebida em {tempo_resposta:.2f}s - Status: {response.status_code}")

            if response.status_code == 200:
                data = response.json()
                content = data['choices'][0]['message']['content'].strip()
                logger.info(f"[BATCH API] Tamanho da resposta: {len(content)} caracteres")

                # Tentar extrair JSON da resposta
                if '```json' in content:
                    content = content.split('```json')[1].split('```')[0].strip()
                elif '```' in content:
                    content = content.split('```')[1].split('```')[0].strip()

                logger.info(f"[BATCH API] Fazendo parse do JSON...")
                resultado_array = json.loads(content)
                logger.info(f"[BATCH API] Parse OK - {len(resultado_array)} itens no array")

                # Converter array para dict {termo_original: {resultado}}
                resultado_dict = {}
                for item in resultado_array:
                    termo_orig = item.get('termo_original', '').upper().strip()
                    if termo_orig:
                        resultado_dict[termo_orig] = {
                            'termo_normalizado': item.get('termo_normalizado', ''),
                            'termo_simples': item.get('termo_simples', ''),
                            'explicacao': item.get('explicacao', '')
                        }

                logger.info(f"[BATCH API] Conversão concluída - {len(resultado_dict)} procedimentos normalizados")
                return resultado_dict
            else:
                logger.error(f"[BATCH API] Erro HTTP {response.status_code}: {response.text[:500]}")
                return {}

        except requests.exceptions.Timeout:
            logger.error(f"[BATCH API] TIMEOUT após 60 segundos para {len(procedimentos_list)} procedimentos")
            return {}
        except json.JSONDecodeError as e:
            logger.error(f"[BATCH API] Erro ao fazer parse do JSON: {e}")
            logger.error(f"[BATCH API] Conteúdo recebido (primeiros 500 chars): {content[:500] if 'content' in locals() else 'N/A'}")
            return {}
        except Exception as e:
            logger.error(f"[BATCH API] Exceção inesperada: {type(e).__name__}: {e}")
            return {}


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

            # Configurar webhook automaticamente
            time.sleep(1)  # Aguardar instância ser criada
            webhook_ok, webhook_msg = self.configurar_webhook()
            if webhook_ok:
                logger.info(f"Webhook configurado automaticamente: {webhook_msg}")
            else:
                logger.warning(f"Falha ao configurar webhook: {webhook_msg}")

            return True, "Instancia criada"
        elif ok and r.status_code == 403:
            # Pode ser que ja existe
            if 'already' in r.text.lower():
                return True, "Instancia ja existe"
        elif ok and r.status_code == 409:
            return True, "Instancia ja existe"

        return False, f"Erro ao criar: {r.status_code if ok else r}"

    def obter_webhook_config(self):
        """Obtém configuração atual do webhook"""
        if not self.ok():
            return False, "Nao configurado"

        ok, r = self._req('GET', f'/webhook/find/{self.instance}')
        if ok and r.status_code == 200:
            try:
                data = r.json()
                logger.info(f"Webhook atual: {data}")
                return True, data
            except:
                return False, "Erro ao parsear resposta"
        return False, f"Erro ao obter webhook: {r.status_code if ok else r}"

    def configurar_webhook(self):
        """Configura webhook para receber mensagens automaticamente"""
        if not self.ok():
            return False, "Nao configurado"

        # Determinar URL do webhook baseado no request atual ou configuração
        try:
            from flask import request
            if request:
                # Usar o domínio da requisição atual, mas sempre com HTTPS
                host = request.host
                webhook_url = f"https://{host}/webhook/whatsapp"
            else:
                raise Exception("Request context not available")
        except:
            # Fallback: tentar obter do ambiente ou usar padrão
            import os
            base_url = os.environ.get('BASE_URL', 'https://chsistemas.cloud')
            webhook_url = f"{base_url}/webhook/whatsapp"

        # Primeiro, tentar obter config atual para ver formato
        logger.info("Verificando webhook atual...")
        ok_get, current = self.obter_webhook_config()
        if ok_get:
            logger.info(f"Config webhook atual: {current}")

        # Lista completa de eventos
        all_events = [
            'APPLICATION_STARTUP',
            'CALL',
            'CHATS_DELETE',
            'CHATS_SET',
            'CHATS_UPDATE',
            'CHATS_UPSERT',
            'CONNECTION_UPDATE',
            'CONTACTS_SET',
            'CONTACTS_UPDATE',
            'CONTACTS_UPSERT',
            'GROUP_PARTICIPANTS_UPDATE',
            'GROUP_UPDATE',
            'GROUPS_UPSERT',
            'LABELS_ASSOCIATION',
            'LABELS_EDIT',
            'MESSAGES_DELETE',
            'MESSAGES_SET',
            'MESSAGES_UPDATE',
            'MESSAGES_UPSERT',
            'PRESENCE_UPDATE',
            'QRCODE_UPDATED',
            'SEND_MESSAGE'
        ]

        # Eventos essenciais para mensagens (fallback)
        essential_events = [
            'MESSAGES_UPSERT',
            'MESSAGES_UPDATE',
            'SEND_MESSAGE',
            'CONNECTION_UPDATE'
        ]

        # Tentar primeiro com configuração simplificada
        # A Evolution API espera o objeto dentro de "webhook"
        webhook_config = {
            'enabled': True,
            'url': webhook_url,
            'webhookByEvents': False,
            'webhookBase64': False,
            'events': essential_events
        }

        payload = {
            'webhook': webhook_config
        }

        logger.info(f"Configurando webhook com eventos essenciais: {essential_events}")
        logger.info(f"Payload: {payload}")
        ok, r = self._req('POST', f'/webhook/set/{self.instance}', payload)

        # Se funcionar com essenciais, tentar adicionar mais eventos
        if ok and r.status_code in [200, 201]:
            logger.info(f"Webhook configurado com eventos essenciais, tentando adicionar mais...")
            webhook_config['events'] = all_events
            payload['webhook'] = webhook_config
            ok2, r2 = self._req('POST', f'/webhook/set/{self.instance}', payload)
            if ok2 and r2.status_code in [200, 201]:
                logger.info(f"Webhook atualizado com todos os eventos")
                r = r2  # Use the successful response
            else:
                logger.warning(f"Não foi possível adicionar todos eventos, mantendo essenciais")
                # Manter a configuração com eventos essenciais que funcionou

        if ok and r.status_code in [200, 201]:
            logger.info(f"Webhook configurado para {self.instance}: {webhook_url}")
            return True, f"Webhook ativado: {webhook_url}"

        # Log detalhado do erro
        error_detail = ""
        if ok:
            try:
                error_detail = r.json() if hasattr(r, 'json') else r.text
                logger.error(f"Erro webhook {r.status_code}: {error_detail}")
            except:
                error_detail = r.text if hasattr(r, 'text') else str(r)
                logger.error(f"Erro webhook {r.status_code}: {error_detail}")
        else:
            logger.error(f"Erro webhook: {r}")
            error_detail = str(r)

        return False, f"Erro ao configurar webhook: {r.status_code if ok else 'conexão falhou'} - {error_detail}"

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
        ok, r = self._req('POST', f"/message/sendText/{self.instance}", {
            'number': num, 
            'text': texto,
            'linkPreview': False  # Desabilita preview de links
        })

        if ok and r.status_code in [200, 201]:
            try:
                mid = r.json().get('key', {}).get('id', '')
                return True, mid
            except:
                return True, ''
        return False, r.text[:100] if ok else r

    def enviar_arquivo(self, numero, caminho_arquivo):
        """
        Envia arquivo (PDF, imagem, etc) via WhatsApp

        Args:
            numero: Número do destinatário
            caminho_arquivo: Caminho completo do arquivo no servidor

        Returns:
            (sucesso: bool, mensagem_id ou erro: str)
        """
        if not self.ok():
            return False, "Nao configurado"

        import os
        import base64

        # Verificar se arquivo existe
        if not os.path.exists(caminho_arquivo):
            return False, f"Arquivo nao encontrado: {caminho_arquivo}"

        # Determinar tipo de mídia baseado na extensão
        ext = os.path.splitext(caminho_arquivo)[1].lower()
        tipo_map = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.mp4': 'video/mp4',
            '.mp3': 'audio/mpeg',
        }

        mimetype = tipo_map.get(ext, 'application/octet-stream')

        try:
            # Ler arquivo e converter para base64
            with open(caminho_arquivo, 'rb') as f:
                arquivo_base64 = base64.b64encode(f.read()).decode('utf-8')

            num = ''.join(filter(str.isdigit, str(numero)))
            nome_arquivo = os.path.basename(caminho_arquivo)

            # Montar payload dependendo do tipo
            if ext in ['.jpg', '.jpeg', '.png']:
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'image',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }
            elif ext == '.pdf':
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'document',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }
            else:
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'document',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }

            ok, r = self._req('POST', endpoint, payload)

            if ok and r.status_code in [200, 201]:
                try:
                    mid = r.json().get('key', {}).get('id', '')
                    return True, mid
                except:
                    return True, ''
            else:
                erro = r.text[:200] if ok else str(r)
                logger.error(f"Erro ao enviar arquivo: {erro}")
                return False, erro

        except Exception as e:
            logger.exception(f"Exceção ao enviar arquivo: {e}")
            return False, str(e)


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

def get_dashboard_route():
    """
    Retorna a rota correta do dashboard baseado no tipo_sistema do usuário
    IMPORTANTE: Use isso em TODOS os redirecionamentos para dashboard
    """
    if current_user.is_authenticated:
        tipo = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
        if tipo == 'AGENDAMENTO_CONSULTA':
            return 'consultas_dashboard'
        # Aceita tanto BUSCA_ATIVA quanto FILA_CIRURGICA (compatibilidade)
        return 'dashboard'
    return 'login'

@app.context_processor
def inject_dashboard_route():
    """Disponibiliza get_dashboard_route nos templates"""
    return dict(get_dashboard_route=get_dashboard_route)

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

        # Normalizar colunas: substituir múltiplos espaços por um único
        import re
        df.columns = [re.sub(r'\s+', ' ', c) for c in df.columns]

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
                            # Já é datetime do Excel
                            dt_nasc = val.date()
                        else:
                            # Converter para string e limpar
                            val_str = str(val).strip()

                            # Extrair apenas a parte da data com regex (DD/MM/YYYY ou DD-MM-YYYY ou DD.MM.YYYY)
                            import re
                            match = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})', val_str)
                            if match:
                                dia, mes, ano = match.groups()
                                # Criar data manualmente para garantir formato correto
                                dt_nasc = datetime(int(ano), int(mes), int(dia)).date()
                            else:
                                # Fallback: tentar parsear com pandas
                                dt_nasc = pd.to_datetime(val_str, dayfirst=True).date()

                        dt_nasc_str = dt_nasc.isoformat()
                        logger.info(f"Data importada: {val} -> {dt_nasc}")
                    except Exception as e:
                        logger.warning(f"Erro ao parsear data '{val}': {e}")
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

        # Separar procedimentos que já estão no cache vs que precisam normalizar
        procedimentos_para_normalizar = []
        for proc_original in procedimentos_unicos:
            cached = ProcedimentoNormalizado.obter_ou_criar(proc_original)
            if cached and cached.aprovado:
                # Usar do cache
                mapa_normalizacao[proc_original] = cached.termo_simples
                logger.info(f"[CACHE] '{proc_original}' -> '{cached.termo_simples}'")
                cached.incrementar_uso()
            else:
                # Adicionar para normalizar em batch
                procedimentos_para_normalizar.append(proc_original)

        # Normalizar em BATCH (dividir em chunks de 20 procedimentos)
        if procedimentos_para_normalizar:
            BATCH_SIZE = 20  # Processar 20 procedimentos por vez
            total = len(procedimentos_para_normalizar)
            logger.info(f"Normalizando {total} procedimentos em lotes de {BATCH_SIZE}...")

            # Dividir em chunks
            for i in range(0, total, BATCH_SIZE):
                chunk = procedimentos_para_normalizar[i:i+BATCH_SIZE]
                chunk_num = (i // BATCH_SIZE) + 1
                total_chunks = (total + BATCH_SIZE - 1) // BATCH_SIZE

                logger.info(f"[LOTE {chunk_num}/{total_chunks}] Processando {len(chunk)} procedimentos...")

                try:
                    resultados_batch = ai._chamar_api_batch(chunk)
                    logger.info(f"[LOTE {chunk_num}/{total_chunks}] API retornou {len(resultados_batch)} resultados")

                    for proc_original in chunk:
                        resultado = resultados_batch.get(proc_original.upper())
                        if resultado and resultado.get('termo_simples'):
                            # Salvar no cache
                            ProcedimentoNormalizado.salvar_normalizacao(
                                termo_original=proc_original,
                                termo_normalizado=resultado['termo_normalizado'],
                                termo_simples=resultado['termo_simples'],
                                explicacao=resultado.get('explicacao', ''),
                                fonte='deepseek'
                            )
                            mapa_normalizacao[proc_original] = resultado['termo_simples']
                            logger.info(f"[API] '{proc_original}' -> '{resultado['termo_simples']}'")
                        else:
                            # Fallback: usar o original
                            mapa_normalizacao[proc_original] = proc_original.title()
                            logger.warning(f"[FALLBACK] '{proc_original}' -> usando original")

                except Exception as e:
                    logger.error(f"[LOTE {chunk_num}/{total_chunks}] Erro ao processar batch: {e}")
                    # Em caso de erro, usar original para este chunk
                    for proc_original in chunk:
                        if proc_original not in mapa_normalizacao:
                            mapa_normalizacao[proc_original] = proc_original.title()
                            logger.warning(f"[ERRO-FALLBACK] '{proc_original}' -> usando original")

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
    """
    DEPRECATED: Esta função foi substituída pela task Celery validar_campanha_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.validar_campanha_task.delay(campanha_id) ao invés desta função.
    """
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
    """
    DEPRECATED: Esta função foi substituída pela task Celery enviar_campanha_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.enviar_campanha_task.delay(campanha_id) ao invés desta função.
    """
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
                        # Calcular intervalo automaticamente baseado no horário e meta diária
                        intervalo = camp.calcular_intervalo()
                        logger.info(f"Aguardando {intervalo}s até próximo envio (baseado em {camp.hora_inicio}h-{camp.hora_fim}h, meta: {camp.meta_diaria})")
                        time.sleep(intervalo)

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
    """
    DEPRECATED: Esta função foi substituída pela task Celery follow_up_automatico_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.follow_up_automatico_task.delay() ao invés desta função.
    """
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
                # Usar procedimento normalizado (mais simples) se disponível, senão usar original
                procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
                msg = msg_template.replace('{nome}', c.nome).replace(
                    '{procedimento}', procedimento_msg
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
            return redirect(url_for(get_dashboard_route()))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# ROTAS
# =============================================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        u = Usuario.query.filter_by(email=email).first()

        if u and u.check_password(senha) and u.ativo:
            login_user(u)
            u.ultimo_acesso = datetime.utcnow()
            db.session.commit()
            # Redirecionar para dashboard correto baseado no tipo_sistema
            return redirect(url_for(get_dashboard_route()))
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
        return redirect(url_for(get_dashboard_route()))

    if 'arquivo' not in request.files or not request.files['arquivo'].filename:
        flash('Selecione arquivo Excel', 'danger')
        return redirect(url_for(get_dashboard_route()))

    arq = request.files['arquivo']
    if not arq.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Arquivo deve ser Excel', 'danger')
        return redirect(url_for(get_dashboard_route()))

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
        arquivo=arq.filename,
        status='processando',
        status_msg='Aguardando processamento...'
    )
    db.session.add(camp)
    db.session.commit()

    # Salvar arquivo temporário para processamento assíncrono
    # Usar /app/uploads/temp que é compartilhado entre web e worker via volume
    import os
    temp_dir = '/app/uploads/temp'
    os.makedirs(temp_dir, exist_ok=True)

    # Nome único para o arquivo temporário
    temp_filename = f'upload_{camp.id}_{int(time.time() * 1000)}.xlsx'
    temp_path = os.path.join(temp_dir, temp_filename)

    # Salvar arquivo
    try:
        arq.save(temp_path)
        logger.info(f"Arquivo salvo em: {temp_path}")

        # Verificar se arquivo existe e tem conteúdo
        if not os.path.exists(temp_path):
            raise FileNotFoundError(f"Arquivo não foi salvo: {temp_path}")

        file_size = os.path.getsize(temp_path)
        logger.info(f"Arquivo salvo com sucesso: {file_size} bytes")

    except Exception as e:
        logger.error(f"Erro ao salvar arquivo: {e}")
        camp.status = 'erro'
        camp.status_msg = f'Erro ao salvar arquivo: {str(e)}'
        db.session.commit()
        flash(f'Erro ao salvar arquivo: {e}', 'danger')
        return redirect(url_for(get_dashboard_route()))

    # Processar planilha de forma ASSÍNCRONA com Celery
    from tasks import processar_planilha_task
    task = processar_planilha_task.delay(temp_path, camp.id)

    # Salvar task_id na campanha para polling
    camp.task_id = task.id
    db.session.commit()

    logger.info(f"Task {task.id} iniciada para campanha {camp.id}")

    # Redirecionar para página de progresso
    return redirect(url_for('progresso_campanha', id=camp.id, task_id=task.id))


@app.route('/campanha/<int:id>/progresso')
@login_required
def progresso_campanha(id):
    """Página de progresso do processamento da campanha"""
    camp = verificar_acesso_campanha(id)
    task_id = request.args.get('task_id') or camp.task_id

    if not task_id:
        flash('Task ID não encontrado', 'warning')
        return redirect(url_for(get_dashboard_route()))

    return render_template('progresso_campanha.html', campanha=camp, task_id=task_id)


@app.route('/api/campanha/status/<task_id>')
@login_required
def status_processamento(task_id):
    """API para polling do status da task de processamento"""
    if not AsyncResult or not celery_app:
        return jsonify({
            'state': 'FAILURE',
            'status': 'Celery não configurado',
            'percent': 0
        })

    task = AsyncResult(task_id, app=celery_app)

    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Aguardando processamento...',
            'percent': 0
        }
    elif task.state == 'PROGRESS':
        response = {
            'state': task.state,
            'status': task.info.get('status', ''),
            'percent': task.info.get('percent', 0),
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 100)
        }
    elif task.state == 'SUCCESS':
        result = task.info
        response = {
            'state': task.state,
            'status': 'Processamento concluído!',
            'percent': 100,
            'result': result
        }
    else:  # FAILURE ou outro estado
        response = {
            'state': task.state,
            'status': str(task.info) if task.info else 'Erro desconhecido',
            'percent': 0
        }

    return jsonify(response)


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

    # Iniciar task Celery em vez de thread
    from tasks import validar_campanha_task
    task = validar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('task_status', task_id=task.id)
    })


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

    # Iniciar task Celery em vez de thread
    from tasks import enviar_campanha_task
    task = enviar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('task_status', task_id=task.id)
    })


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

    # Iniciar task Celery em vez de thread
    from tasks import enviar_campanha_task
    task = enviar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('task_status', task_id=task.id)
    })


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
    return redirect(url_for(get_dashboard_route()))


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
# @app.route('/api/dashboard/tickets')
# @login_required
# def api_dashboard_tickets():
#     """Retorna estatísticas de tickets para o dashboard"""
#     # Filtrar apenas tickets das campanhas do usuario atual
#     user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]
#     if user_campanhas_ids:
#         urgentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente', TicketAtendimento.prioridade == 'urgente').count()
#         pendentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente').count()
#     else:
#         urgentes = 0
#         pendentes = 0
#     return jsonify({'urgentes': urgentes, 'pendentes': pendentes})


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

    # Usar procedimento normalizado (mais simples) se disponível, senão usar original
    procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
    msg = c.campanha.mensagem.replace('{nome}', c.nome).replace('{procedimento}', procedimento_msg)

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


@app.route('/api/contato/<int:id>/detalhes', methods=['GET'])
@login_required
def api_contato_detalhes(id):
    """
    Retorna informações detalhadas do contato incluindo:
    - Todas as respostas de cada telefone
    - Histórico de mensagens (enviadas e recebidas)
    - Status de conflito
    """
    try:
        c = verificar_acesso_contato(id)

        # Obter respostas detalhadas de todos os telefones
        respostas_telefones = []
        for telefone in c.telefones.all():
            tel_info = {
                'id': telefone.id,
                'numero': telefone.numero,
                'numero_formatado': telefone.numero_fmt,
                'prioridade': telefone.prioridade,
                'whatsapp_valido': telefone.whatsapp_valido,
                'enviado': telefone.enviado,
                'data_envio': telefone.data_envio.isoformat() if telefone.data_envio else None,
                'resposta': getattr(telefone, 'resposta', None),
                'data_resposta': getattr(telefone, 'data_resposta', None).isoformat() if getattr(telefone, 'data_resposta', None) else None,
                'tipo_resposta': getattr(telefone, 'tipo_resposta', None),
                'tipo_resposta_texto': {
                    'confirmado': 'Confirmado',
                    'rejeitado': 'Rejeitado',
                    'desconheco': 'Não conhece a pessoa'
                }.get(getattr(telefone, 'tipo_resposta', None), 'Sem resposta'),
                'validacao_pendente': getattr(telefone, 'validacao_pendente', False)
            }
            respostas_telefones.append(tel_info)

        # Obter histórico de mensagens do log
        logs = LogMsg.query.filter_by(contato_id=c.id).order_by(LogMsg.data).all()
        historico = []
        for log in logs:
            log_info = {
                'id': log.id,
                'direcao': log.direcao,
                'telefone': log.telefone,
                'mensagem': log.mensagem,
                'data': log.data.isoformat() if log.data else None,
                'status': log.status,
                'sentimento': log.sentimento,
                'sentimento_score': log.sentimento_score
            }
            historico.append(log_info)

        # Informações do contato
        # Usar try/except para métodos que podem não existir ainda
        try:
            tem_multiplas = c.tem_respostas_multiplas()
            tem_conflito = c.tem_conflito_real()
        except:
            tem_multiplas = False
            tem_conflito = False

        contato_info = {
            'id': c.id,
            'nome': c.nome,
            'data_nascimento': c.data_nascimento.isoformat() if c.data_nascimento else None,
            'procedimento': c.procedimento,
            'status': c.status,
            'status_texto': c.status_texto(),
            'confirmado': c.confirmado,
            'rejeitado': c.rejeitado,
            'erro': c.erro,
            'tem_respostas_multiplas': tem_multiplas,
            'tem_conflito_real': tem_conflito,
            'campanha_id': c.campanha_id
        }

        return jsonify({
            'contato': contato_info,
            'telefones': respostas_telefones,
            'historico': historico
        })
    except Exception as e:
        logger.error(f"Erro ao buscar detalhes do contato {id}: {str(e)}")
        return jsonify({'erro': 'Erro ao carregar detalhes. Banco de dados precisa ser atualizado.'}), 500


@app.route('/api/contato/<int:id>/enviar_mensagem', methods=['POST'])
@login_required
def api_enviar_mensagem_contato(id):
    """
    Envia uma mensagem para um telefone específico do contato
    """
    c = verificar_acesso_contato(id)

    data = request.get_json()
    telefone_id = data.get('telefone_id')
    mensagem = data.get('mensagem', '').strip()

    if not mensagem:
        return jsonify({'erro': 'Mensagem não pode estar vazia'}), 400

    # Encontrar o telefone
    telefone = None
    for t in c.telefones.all():
        if t.id == telefone_id:
            telefone = t
            break

    if not telefone:
        return jsonify({'erro': 'Telefone não encontrado'}), 404

    if not telefone.whatsapp_valido:
        return jsonify({'erro': 'Este número não possui WhatsApp válido'}), 400

    # Enviar mensagem
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp não configurado'}), 400

    sucesso, resultado = ws.enviar(telefone.numero_fmt, mensagem)

    if sucesso:
        # Registrar no log
        log = LogMsg(
            campanha_id=c.campanha_id,
            contato_id=c.id,
            direcao='enviada',
            telefone=telefone.numero_fmt,
            mensagem=mensagem,
            status='enviado'
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({
            'sucesso': True,
            'mensagem': 'Mensagem enviada com sucesso'
        })
    else:
        return jsonify({
            'erro': f'Erro ao enviar mensagem: {resultado}'
        }), 500


@app.route('/contato/<int:id>/detalhes')
@login_required
def contato_detalhes_pagina(id):
    """
    Página completa com detalhes do contato
    """
    c = verificar_acesso_contato(id)

    # Obter telefones com respostas
    telefones = c.telefones.all()

    # Obter histórico de mensagens
    logs = LogMsg.query.filter_by(contato_id=c.id).order_by(LogMsg.data).all()

    return render_template('contato_detalhes.html',
                         contato=c,
                         telefones=telefones,
                         logs=logs)


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


@app.route('/api/whatsapp/webhook/configurar', methods=['POST'])
@login_required
def configurar_webhook_whatsapp():
    """Configura webhook para a instância do usuário"""
    try:
        ws = WhatsApp(current_user.id)
        if not ws.ok():
            return jsonify({'erro': 'WhatsApp não configurado'}), 400

        ok, msg = ws.configurar_webhook()
        if ok:
            return jsonify({
                'sucesso': True,
                'mensagem': msg
            })
        else:
            return jsonify({'erro': msg}), 400

    except Exception as e:
        logger.error(f"Erro ao configurar webhook: {str(e)}")
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


# Funcao auxiliar para verificar respostas validas
def verificar_resposta_em_lista(texto_up, lista_respostas):
    """
    Verifica se o texto É EXATAMENTE uma resposta válida.
    MUDANÇA CRÍTICA: Agora aceita SOMENTE respostas exatas (mensagem completa).
    Exemplos:
    - "SIM" → ✅ aceito
    - "1" → ✅ aceito  
    - "TENHO INTERESSE" → ✅ aceito
    - "Boa tarde! Não sei quando posso ir" → ❌ rejeitado (não é resposta exata)
    - "Sim, quero" → ❌ rejeitado (não é resposta exata)
    """
    # Remove espaços extras e normaliza
    texto_normalizado = ' '.join(texto_up.split())
    
    # Verifica se a mensagem COMPLETA é exatamente uma das respostas válidas
    return texto_normalizado in lista_respostas


# Webhook
@app.route('/webhook/whatsapp', methods=['POST'])
@csrf.exempt
def webhook():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'ok'}), 200

        # Log do evento recebido (útil para debug)
        logger.debug(f"Webhook evento recebido: {data.get('event')}")

        # Normalizar nome do evento (aceita MESSAGES_UPSERT ou messages.upsert)
        event = data.get('event', '').upper().replace('.', '_')
        if event != 'MESSAGES_UPSERT':
            logger.debug(f"Evento ignorado: {event}")
            return jsonify({'status': 'ok'}), 200

        # CRÍTICO: Extrair nome da instância para filtrar por usuário
        # Isso evita que respostas sejam processadas no contexto errado quando
        # múltiplos usuários (com WhatsApps diferentes) contactam o mesmo paciente
        instance_name = data.get('instance')
        if not instance_name:
            logger.warning("Webhook sem informação de instância - ignorando por segurança")
            return jsonify({'status': 'ok'}), 200

        # Buscar usuário dono desta instância
        config_usuario = ConfigWhatsApp.query.filter_by(instance_name=instance_name).first()
        if not config_usuario:
            logger.warning(f"Instância {instance_name} não encontrada no sistema")
            return jsonify({'status': 'ok'}), 200

        usuario_id = config_usuario.usuario_id
        logger.debug(f"Webhook da instância {instance_name} (usuário ID: {usuario_id})")

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

        # =====================================================================
        # PROTEÇÃO GLOBAL: Evitar duplicação quando mesmo telefone está em múltiplos usuários
        # =====================================================================
        # Buscar TODAS as variações do número
        numeros_buscar = [numero]
        if len(numero) == 12:
            numeros_buscar.append(numero[:4] + '9' + numero[4:])  # Com 9º dígito
        elif len(numero) == 13:
            numeros_buscar.append(numero[:4] + numero[5:])  # Sem 9º dígito

        # Verificar se esta mensagem já foi processada por OUTRO webhook (outro usuário)
        from datetime import timedelta
        cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)

        # Buscar log global por telefone (qualquer consulta)
        log_global_consulta = LogMsgConsulta.query.filter(
            LogMsgConsulta.telefone.in_(numeros_buscar),
            LogMsgConsulta.direcao == 'recebida',
            LogMsgConsulta.mensagem == texto[:500],
            LogMsgConsulta.data >= cinco_segundos_atras
        ).first()

        if log_global_consulta:
            logger.debug(f"Webhook: Mensagem já processada por outro webhook de consulta. Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # Buscar log global por telefone (qualquer cirurgia/fila)
        log_global_fila = LogMsg.query.filter(
            LogMsg.telefone.in_(numeros_buscar),
            LogMsg.direcao == 'recebida',
            LogMsg.mensagem == texto[:500],
            LogMsg.data >= cinco_segundos_atras
        ).first()

        if log_global_fila:
            logger.debug(f"Webhook: Mensagem já processada por outro webhook de fila. Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # DETECÇÃO DE MÚLTIPLAS PENDÊNCIAS (Consultas + Cirurgias)
        # =====================================================================
        # Se é resposta de confirmação (1, SIM, etc), verificar se tem múltiplas pendências
        resposta_confirmacao = verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM)
        resposta_rejeicao = verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO)

        if resposta_confirmacao or resposta_rejeicao:
            # Buscar TODAS as consultas pendentes deste telefone (de QUALQUER usuário)
            consultas_pendentes = []
            for num in numeros_buscar:
                tels = TelefoneConsulta.query.filter_by(numero=num).all()
                for tel in tels:
                    if tel.consulta and tel.consulta.status == 'AGUARDANDO_CONFIRMACAO':
                        consultas_pendentes.append(tel.consulta)

            # Buscar TODAS as cirurgias pendentes deste telefone (de QUALQUER usuário)
            cirurgias_pendentes = []
            for num in numeros_buscar:
                tels_fila = Telefone.query.filter_by(numero_fmt=num).all()
                for tel in tels_fila:
                    if tel.contato and tel.contato.status in ['enviado', 'pronto_envio']:
                        cirurgias_pendentes.append(tel.contato)

            # Remover duplicados (mesmo ID)
            consultas_pendentes = list({c.id: c for c in consultas_pendentes}.values())
            cirurgias_pendentes = list({c.id: c for c in cirurgias_pendentes}.values())

            total_pendencias = len(consultas_pendentes) + len(cirurgias_pendentes)

            # Se tem múltiplas pendências E a resposta é de confirmação/rejeição
            if total_pendencias > 1:
                # Verificar se já enviamos menu nos últimos 2 minutos
                dois_minutos_atras = datetime.utcnow() - timedelta(minutes=2)
                menu_enviado = LogMsgConsulta.query.filter(
                    LogMsgConsulta.telefone.in_(numeros_buscar),
                    LogMsgConsulta.direcao == 'enviada',
                    LogMsgConsulta.mensagem.like('%Qual agendamento%'),
                    LogMsgConsulta.data >= dois_minutos_atras
                ).first()

                if not menu_enviado:
                    # Também verificar na tabela de logs da fila
                    menu_enviado = LogMsg.query.filter(
                        LogMsg.telefone.in_(numeros_buscar),
                        LogMsg.direcao == 'enviada',
                        LogMsg.mensagem.like('%Qual agendamento%'),
                        LogMsg.data >= dois_minutos_atras
                    ).first()

                if not menu_enviado:
                    # Enviar menu de escolha
                    ws = WhatsApp(usuario_id)

                    menu_texto = "📋 *Você tem múltiplos agendamentos pendentes:*\n\n"
                    opcao = 1

                    # Ordenar por data (mais próxima primeiro)
                    for consulta in sorted(consultas_pendentes, key=lambda c: c.data_aghu or ''):
                        data_str = formatar_data_consulta(consulta.data_aghu) if consulta.data_aghu else 'Data não informada'
                        menu_texto += f"{opcao}️⃣ *CONSULTA* - {consulta.especialidade or 'Especialidade'}\n"
                        menu_texto += f"   📅 {data_str}\n"
                        menu_texto += f"   👨‍⚕️ {consulta.medico_solicitante or consulta.grade_aghu or 'Médico não informado'}\n\n"
                        opcao += 1

                    for cirurgia in cirurgias_pendentes:
                        proc = cirurgia.procedimento_normalizado or cirurgia.procedimento or 'Procedimento'
                        menu_texto += f"{opcao}️⃣ *CIRURGIA* - {proc}\n"
                        menu_texto += f"   📅 Fila cirúrgica\n\n"
                        opcao += 1

                    menu_texto += f"*Qual agendamento deseja {'confirmar' if resposta_confirmacao else 'recusar'}?*\n"
                    menu_texto += f"Responda com o número (1 a {total_pendencias}) ou *TODOS* para confirmar todos."

                    ws.enviar(numero, menu_texto)

                    # Registrar que enviamos o menu (para não enviar de novo)
                    if consultas_pendentes:
                        log = LogMsgConsulta(
                            campanha_id=consultas_pendentes[0].campanha_id,
                            consulta_id=consultas_pendentes[0].id,
                            direcao='enviada',
                            telefone=numero,
                            mensagem=menu_texto[:500],
                            status='sucesso'
                        )
                        db.session.add(log)
                    elif cirurgias_pendentes:
                        log = LogMsg(
                            campanha_id=cirurgias_pendentes[0].campanha_id,
                            contato_id=cirurgias_pendentes[0].id,
                            direcao='enviada',
                            telefone=numero,
                            mensagem=menu_texto[:500],
                            status='ok'
                        )
                        db.session.add(log)

                    db.session.commit()
                    logger.info(f"Menu de múltiplas pendências enviado para {numero} ({total_pendencias} pendências)")
                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # PROCESSAR RESPOSTA DO MENU DE MÚLTIPLAS PENDÊNCIAS
        # =====================================================================
        # Verificar se paciente recebeu menu recentemente e está respondendo
        dois_minutos_atras = datetime.utcnow() - timedelta(minutes=2)

        # Verificar se existe menu enviado recentemente
        menu_recente_consulta = LogMsgConsulta.query.filter(
            LogMsgConsulta.telefone.in_(numeros_buscar),
            LogMsgConsulta.direcao == 'enviada',
            LogMsgConsulta.mensagem.like('%Qual agendamento%'),
            LogMsgConsulta.data >= dois_minutos_atras
        ).first()

        menu_recente_fila = None
        if not menu_recente_consulta:
            menu_recente_fila = LogMsg.query.filter(
                LogMsg.telefone.in_(numeros_buscar),
                LogMsg.direcao == 'enviada',
                LogMsg.mensagem.like('%Qual agendamento%'),
                LogMsg.data >= dois_minutos_atras
            ).first()

        if menu_recente_consulta or menu_recente_fila:
            # Paciente está respondendo ao menu - processar escolha
            escolha = texto_up.strip()

            # Buscar novamente as pendências (podem ter mudado)
            consultas_pendentes = []
            for num in numeros_buscar:
                tels = TelefoneConsulta.query.filter_by(numero=num).all()
                for tel in tels:
                    if tel.consulta and tel.consulta.status == 'AGUARDANDO_CONFIRMACAO':
                        consultas_pendentes.append((tel.consulta, tel.numero))

            cirurgias_pendentes = []
            for num in numeros_buscar:
                tels_fila = Telefone.query.filter_by(numero_fmt=num).all()
                for tel in tels_fila:
                    if tel.contato and tel.contato.status in ['enviado', 'pronto_envio']:
                        cirurgias_pendentes.append((tel.contato, tel.numero_fmt))

            # Remover duplicados
            consultas_pendentes = list({c[0].id: c for c in consultas_pendentes}.values())
            cirurgias_pendentes = list({c[0].id: c for c in cirurgias_pendentes}.values())

            # Ordenar igual ao menu
            consultas_pendentes = sorted(consultas_pendentes, key=lambda c: c[0].data_aghu or '')

            todas_pendencias = consultas_pendentes + cirurgias_pendentes

            if escolha == 'TODOS' or escolha == 'TODAS':
                # Confirmar/rejeitar TODAS as pendências
                ws = WhatsApp(usuario_id)
                confirmados = 0

                for item, tel_numero in todas_pendencias:
                    if hasattr(item, 'campanha_id') and hasattr(item, 'paciente'):
                        # É uma consulta
                        item.status = 'AGUARDANDO_COMPROVANTE'
                        item.data_confirmacao = datetime.utcnow()
                        db.session.commit()
                        item.campanha.atualizar_stats()
                        confirmados += 1
                    else:
                        # É uma cirurgia - iniciar fluxo de data de nascimento
                        item.status = 'aguardando_nascimento'
                        item.resposta = '1'
                        item.data_resposta = datetime.utcnow()
                        confirmados += 1

                db.session.commit()

                if confirmados > 0:
                    ws.enviar(numero, f"✅ *{confirmados} agendamento(s) confirmado(s)!*\n\nAguarde o envio dos comprovantes.")
                    logger.info(f"Múltiplas pendências confirmadas para {numero}: {confirmados} itens")

                return jsonify({'status': 'ok'}), 200

            elif escolha.isdigit():
                opcao_num = int(escolha)
                if 1 <= opcao_num <= len(todas_pendencias):
                    item, tel_numero = todas_pendencias[opcao_num - 1]
                    ws = WhatsApp(usuario_id)

                    if hasattr(item, 'campanha_id') and hasattr(item, 'paciente'):
                        # É uma consulta
                        item.status = 'AGUARDANDO_COMPROVANTE'
                        item.data_confirmacao = datetime.utcnow()
                        db.session.commit()
                        item.campanha.atualizar_stats()
                        db.session.commit()

                        ws.enviar(numero, f"✅ *Consulta confirmada!*\n\n📅 {formatar_data_consulta(item.data_aghu) if item.data_aghu else 'Data não informada'}\n👨‍⚕️ {item.especialidade or 'Especialidade'}\n\nAguarde o envio do comprovante.")
                        logger.info(f"Consulta {item.id} confirmada via menu por {item.paciente}")

                        # Log da mensagem recebida
                        log = LogMsgConsulta(
                            campanha_id=item.campanha_id,
                            consulta_id=item.id,
                            direcao='recebida',
                            telefone=numero,
                            mensagem=texto[:500],
                            status='sucesso'
                        )
                        db.session.add(log)
                        db.session.commit()

                    else:
                        # É uma cirurgia - iniciar fluxo de data de nascimento
                        item.status = 'aguardando_nascimento'
                        item.resposta = '1'
                        item.data_resposta = datetime.utcnow()
                        db.session.commit()

                        ws.enviar(numero, "🔒 Por segurança, por favor digite sua *Data de Nascimento* (ex: 03/09/1954).")
                        logger.info(f"Cirurgia selecionada via menu para {item.nome}, aguardando nascimento")

                        # Log da mensagem recebida
                        log = LogMsg(
                            campanha_id=item.campanha_id,
                            contato_id=item.id,
                            direcao='recebida',
                            telefone=numero,
                            mensagem=texto[:500],
                            status='ok'
                        )
                        db.session.add(log)
                        db.session.commit()

                    # Verificar se ainda há outras pendências
                    pendencias_restantes = len(todas_pendencias) - 1
                    if pendencias_restantes > 0:
                        ws.enviar(numero, f"📋 Você ainda tem *{pendencias_restantes}* agendamento(s) pendente(s). Responda *1* para confirmar ou *2* para recusar.")

                    return jsonify({'status': 'ok'}), 200

                else:
                    # Número inválido
                    ws = WhatsApp(usuario_id)
                    ws.enviar(numero, f"❌ Opção inválida. Por favor, responda com um número de 1 a {len(todas_pendencias)} ou *TODOS*.")
                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # MODO CONSULTA - Processar PRIMEIRO (tem prioridade)
        # =====================================================================
        # Verificar se é uma resposta de consulta ANTES de processar fila cirúrgica
        # Isso garante que ambos os sistemas (Consultas e Fila) funcionem independentemente
        # Busca por telefone do usuário correto (mesmo filtro de instância)
        # IMPORTANTE: Tentar variações do número (com/sem 9º dígito)
        consulta_telefones = TelefoneConsulta.query.filter_by(numero=numero).all()

        if not consulta_telefones:
            # Tenta variação 9º dígito (mesmo código usado para fila cirúrgica)
            if len(numero) == 12:
                # Número sem 9, tentar com 9
                num9 = numero[:4] + '9' + numero[4:]
                consulta_telefones = TelefoneConsulta.query.filter_by(numero=num9).all()
            elif len(numero) == 13:
                # Número com 9, tentar sem 9
                num_sem9 = numero[:4] + numero[5:]
                consulta_telefones = TelefoneConsulta.query.filter_by(numero=num_sem9).all()

        # Priorizar consulta mais apropriada quando há múltiplas consultas do mesmo telefone
        # PRIORIDADE:
        # 1. Consultas do usuário correto (filtro de instância)
        # 2. Consultas em fluxo ativo (AGUARDANDO_CONFIRMACAO, AGUARDANDO_MOTIVO_REJEICAO)
        # 3. Consultas da campanha mais recente (maior ID de campanha)
        # 4. Consultas mais recentes (maior ID de consulta)
        consulta_telefone = None
        if consulta_telefones:
            # Filtrar apenas consultas do usuário correto
            consultas_validas = [
                tel for tel in consulta_telefones
                if tel.consulta and tel.consulta.campanha and tel.consulta.campanha.criador_id == usuario_id
            ]

            if consultas_validas:
                # IMPORTANTE: Filtrar apenas consultas enviadas recentemente (últimas 24h)
                # Isso evita processar consultas antigas quando o mesmo telefone está em múltiplas campanhas/usuários
                from datetime import timedelta
                vinte_quatro_horas_atras = datetime.utcnow() - timedelta(hours=24)
                consultas_recentes = [
                    tel for tel in consultas_validas
                    if tel.consulta.data_envio_mensagem and tel.consulta.data_envio_mensagem >= vinte_quatro_horas_atras
                ]

                # Se não há consultas recentes, usar todas (fallback para casos onde data_envio não está setada)
                if not consultas_recentes:
                    consultas_recentes = consultas_validas

                # Separar por status
                em_fluxo = [
                    tel for tel in consultas_recentes
                    if tel.consulta.status in ['AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_MOTIVO_REJEICAO', 'AGUARDANDO_OPCAO_REJEICAO', 'REAGENDADO']
                ]
                outras = [
                    tel for tel in consultas_recentes
                    if tel.consulta.status not in ['AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_MOTIVO_REJEICAO', 'AGUARDANDO_OPCAO_REJEICAO', 'REAGENDADO']
                ]

                # Priorizar consultas em fluxo ativo, depois as mais recentes
                if em_fluxo:
                    # Pegar a mais recente em fluxo (maior ID de campanha, depois maior ID de consulta)
                    consulta_telefone = max(em_fluxo, key=lambda t: (t.consulta.campanha_id, t.consulta.id))
                elif outras:
                    # Pegar a mais recente das outras (maior ID de campanha, depois maior ID de consulta)
                    consulta_telefone = max(outras, key=lambda t: (t.consulta.campanha_id, t.consulta.id))

        if consulta_telefone:
            consulta = consulta_telefone.consulta
            # Verificar se pertence ao usuário correto (mesmo filtro de instância)
            if consulta and consulta.campanha and consulta.campanha.criador_id == usuario_id:
                logger.info(f"Webhook Consulta: [{instance_name}] Mensagem de {consulta.paciente} ({numero} → {consulta_telefone.numero}). "
                           f"Campanha: {consulta.campanha_id}. Status: {consulta.status}. Texto: {texto}")

                # PROTEÇÃO CONTRA DUPLICAÇÃO (múltiplos workers do Gunicorn)
                # IMPORTANTE: Criar log IMEDIATAMENTE com commit para bloquear outros workers
                from datetime import timedelta
                cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)

                # Usar with_for_update para lock otimista na consulta
                log_recente = LogMsgConsulta.query.filter(
                    LogMsgConsulta.consulta_id == consulta.id,
                    LogMsgConsulta.direcao == 'recebida',
                    LogMsgConsulta.mensagem == texto[:500],
                    LogMsgConsulta.data >= cinco_segundos_atras
                ).first()

                if log_recente:
                    logger.info(f"Mensagem duplicada detectada (já processada há {(datetime.utcnow() - log_recente.data).total_seconds():.1f}s). Ignorando.")
                    return jsonify({'status': 'ok'}), 200

                # IMPORTANTE: Usar o número cadastrado na consulta para garantir que respondemos no formato correto
                numero_resposta = consulta_telefone.numero

                # Criar log IMEDIATAMENTE e commitar ANTES de processar
                # Isso garante que outros workers vejam que já está sendo processado
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='recebida',
                    telefone=numero_resposta,
                    mensagem=texto[:500],
                    status='processando'  # Marca como processando primeiro
                )
                db.session.add(log)
                db.session.commit()  # COMMIT IMEDIATO para bloquear outros workers

                ws = WhatsApp(consulta.campanha.criador_id)

                # ESTADO 1: AGUARDANDO_CONFIRMACAO (resposta à MSG 1)
                if consulta.status == 'AGUARDANDO_CONFIRMACAO':
                    # Verificar se é SIM, NÃO ou DESCONHEÇO
                    if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM):
                        # Paciente confirmou!
                        consulta.data_confirmacao = datetime.utcnow()
                        
                        # Verificar se é INTERCONSULTA que NÃO precisa ir ao posto
                        if (consulta.tipo == 'INTERCONSULTA' and 
                            consulta.paciente_voltar_posto_sms and 
                            consulta.paciente_voltar_posto_sms.upper() == 'NÃO'):
                            # INTERCONSULTA aprovada sem necessidade de ir ao posto
                            # Pula o passo de aguardar comprovante e vai direto para CONFIRMADO
                            consulta.status = 'CONFIRMADO'
                            db.session.commit()
                            
                            consulta.campanha.atualizar_stats()
                            db.session.commit()
                            
                            # Enviar mensagem de aprovação da interconsulta
                            msg_aprovacao = formatar_mensagem_interconsulta_aprovada(consulta)
                            enviar_e_registrar_consulta(ws, numero_resposta, msg_aprovacao, consulta)
                            logger.info(f"Interconsulta {consulta.id} aprovada diretamente (não precisa ir ao posto) - {consulta.paciente}")
                        else:
                            # Fluxo normal: aguardar comprovante
                            consulta.status = 'AGUARDANDO_COMPROVANTE'
                            db.session.commit()

                            consulta.campanha.atualizar_stats()
                            db.session.commit()

                            enviar_e_registrar_consulta(ws, numero_resposta, "✅ Consulta confirmada! Aguarde o envio do comprovante.", consulta)
                            logger.info(f"Consulta {consulta.id} confirmada por {consulta.paciente}")

                        # Notificar OUTROS telefones que a consulta já foi confirmada
                        # (exceto os que responderam DESCONHEÇO)
                        for tel in consulta.telefones:
                            if tel.numero != numero_resposta and tel.enviado and not tel.invalido and not tel.nao_pertence:
                                try:
                                    ws.enviar(tel.numero, f"ℹ️ A consulta de *{consulta.paciente}* já foi confirmada em outro telefone.\n\nNão é necessário responder por este número.")
                                    logger.info(f"Notificação enviada para {tel.numero} sobre confirmação em {numero_resposta}")
                                except Exception as e:
                                    logger.warning(f"Erro ao notificar {tel.numero}: {e}")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                        # Paciente respondeu NÃO (Opção 2)
                        # Ir direto para perguntar motivo (reagendamento desativado)
                        consulta.status = 'AGUARDANDO_MOTIVO_REJEICAO'
                        db.session.commit()

                        msg_perguntar_motivo = formatar_mensagem_perguntar_motivo()
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_perguntar_motivo, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu opção 2 (NÃO), aguardando motivo da rejeição")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO):
                        # Paciente não conhece → Marcar APENAS este telefone como "não pertence"
                        # Só rejeita a consulta se TODOS os telefones forem marcados assim

                        # Marcar este telefone como "não pertence ao paciente"
                        consulta_telefone.nao_pertence = True
                        db.session.commit()

                        # Verificar se TODOS os telefones válidos (enviados e não inválidos) foram marcados como "não pertence"
                        telefones_validos = [t for t in consulta.telefones if t.enviado and not t.invalido]
                        telefones_nao_pertence = [t for t in telefones_validos if t.nao_pertence]

                        todos_nao_pertencem = len(telefones_validos) > 0 and len(telefones_nao_pertence) == len(telefones_validos)

                        if todos_nao_pertencem:
                            # TODOS os telefones responderam "DESCONHEÇO" → Rejeitar consulta
                            consulta.status = 'REJEITADO'
                            consulta.motivo_rejeicao = 'Paciente não localizado - todos os telefones responderam DESCONHEÇO'
                            consulta.data_rejeicao = datetime.utcnow()
                            db.session.commit()

                            consulta.campanha.atualizar_stats()
                            db.session.commit()

                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela informação!*

Vamos atualizar nossos registros.

_Hospital Universitário Walter Cantídio_""", consulta)
                            logger.info(f"Consulta {consulta.id} rejeitada - TODOS os telefones responderam DESCONHEÇO (paciente não localizado)")
                        else:
                            # Ainda há outros telefones que podem responder
                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela informação!*

Este número foi marcado como não pertencente ao paciente.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""", consulta)
                            logger.info(f"Consulta {consulta.id}: telefone {numero_resposta} marcado como 'não pertence ao paciente'. Aguardando outros telefones.")

                    else:
                        # Resposta não reconhecida
                        enviar_e_registrar_consulta(ws, numero_resposta, """Por favor, responda com uma das opções:

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa""", consulta)

                    return jsonify({'status': 'ok'}), 200

                # ESTADO 1.5: AGUARDANDO_OPCAO_REJEICAO (resposta se quer cancelar ou reagendar)
                elif consulta.status == 'AGUARDANDO_OPCAO_REJEICAO':
                    # Verificar resposta (deve ser EXATAMENTE: 1, UM ou CANCELAR como mensagem completa)
                    
                    if verificar_resposta_em_lista(texto_up, ['1', 'UM']):
                        # Quer CANCELAR → Perguntar motivo (fluxo antigo)
                        consulta.status = 'AGUARDANDO_MOTIVO_REJEICAO'
                        db.session.commit()

                        msg_perguntar_motivo = formatar_mensagem_perguntar_motivo()
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_perguntar_motivo, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu CANCELAR, aguardando motivo")
                        
                    elif verificar_resposta_em_lista(texto_up, ['2', 'DOIS']):
                        # Quer REAGENDAR → Status especial para equipe atuar
                        consulta.status = 'AGUARDANDO_REAGENDAMENTO'
                        db.session.commit()
                        
                        enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Entendido!*
                        
Nossa equipe foi notificada e entrará em contato em breve para verificar uma nova data disponível para você.

Por favor, aguarde nosso retorno.

_Hospital Universitário Walter Cantídio_""", consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu REAGENDAR (aguardando equipe)")
                        
                    else:
                        # Resposta inválida
                        enviar_e_registrar_consulta(ws, numero_resposta, """Por favor, digite o número da opção desejada:

1️⃣ *CANCELAR* - Não quero mais a consulta
2️⃣ *REAGENDAR* - Quero mudar a data/horário""", consulta)
                        
                    return jsonify({'status': 'ok'}), 200

                # ESTADO 2: AGUARDANDO_MOTIVO_REJEICAO (resposta à MSG 3A)
                elif consulta.status == 'AGUARDANDO_MOTIVO_REJEICAO':
                    # Armazenar motivo da rejeição
                    consulta.motivo_rejeicao = texto
                    consulta.status = 'REJEITADO'
                    consulta.data_rejeicao = datetime.utcnow()
                    db.session.commit()

                    logger.info(f"Consulta {consulta.id} rejeitada. Motivo: {texto}")

                    # Verificar se deve enviar MSG 3B (voltar ao posto)
                    # Só envia se: INTERCONSULTA + PACIENTE_VOLTAR_POSTO_SMS = SIM
                    if (consulta.tipo == 'INTERCONSULTA' and
                        consulta.paciente_voltar_posto_sms and
                        consulta.paciente_voltar_posto_sms.upper() == 'SIM'):

                        msg_voltar_posto = formatar_mensagem_voltar_posto(consulta)
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_voltar_posto, consulta)
                        logger.info(f"MSG 3B enviada para {consulta.paciente} (INTERCONSULTA + voltar posto)")
                    else:
                        # Outros casos: enviar mensagem de confirmação de cancelamento
                        msg_confirmacao = formatar_mensagem_confirmacao_rejeicao(consulta)
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_confirmacao, consulta)
                        logger.info(f"Consulta {consulta.id} cancelada - confirmação enviada")

                    consulta.campanha.atualizar_stats()
                    db.session.commit()

                    return jsonify({'status': 'ok'}), 200

                # ESTADO 3: REAGENDADO (resposta à mensagem de reagendamento)
                elif consulta.status == 'REAGENDADO':
                    # Paciente recebeu nova data e está confirmando
                    if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM):
                        # Paciente confirmou o reagendamento! → AGUARDANDO_COMPROVANTE
                        consulta.status = 'AGUARDANDO_COMPROVANTE'
                        consulta.data_confirmacao = datetime.utcnow()
                        db.session.commit()

                        consulta.campanha.atualizar_stats()
                        db.session.commit()

                        # Mensagem de confirmação com a nova data
                        nova_data = consulta.nova_data or consulta.data_aghu or 'data agendada'
                        nova_hora = consulta.nova_hora or ''
                        msg_confirmacao = f"""✅ *Reagendamento confirmado!*

📅 Data: {nova_data}
⏰ Horário: {nova_hora}
👨‍⚕️ Especialidade: {consulta.especialidade}

Aguarde o envio do comprovante.

_Hospital Universitário Walter Cantídio_"""
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_confirmacao, consulta)
                        logger.info(f"Consulta {consulta.id} reagendamento confirmado por {consulta.paciente}")

                        # Notificar OUTROS telefones que a consulta já foi confirmada
                        # (exceto os que responderam DESCONHEÇO)
                        for tel in consulta.telefones:
                            if tel.numero != numero_resposta and tel.enviado and not tel.invalido and not tel.nao_pertence:
                                try:
                                    ws.enviar(tel.numero, f"ℹ️ A consulta de *{consulta.paciente}* já foi confirmada em outro telefone.\n\nNão é necessário responder por este número.")
                                    logger.info(f"Notificação enviada para {tel.numero} sobre confirmação em {numero_resposta}")
                                except Exception as e:
                                    logger.warning(f"Erro ao notificar {tel.numero}: {e}")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                        # Paciente não pode ir na nova data → perguntar o que quer fazer
                        consulta.status = 'AGUARDANDO_OPCAO_REJEICAO'
                        db.session.commit()

                        msg_opcao = """Entendemos! O que você deseja fazer?

1️⃣ *CANCELAR* - Não quero mais a consulta
2️⃣ *REAGENDAR* - Quero outra data/horário"""

                        enviar_e_registrar_consulta(ws, numero_resposta, msg_opcao, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente não confirmou reagendamento, oferecendo opções")

                    else:
                        # Resposta não reconhecida
                        enviar_e_registrar_consulta(ws, numero_resposta, """Por favor, responda com uma das opções:

1️⃣ *SIM* - Confirmar a nova data
2️⃣ *NÃO* - Não posso ir nessa data""", consulta)

                    return jsonify({'status': 'ok'}), 200

                # Outros status (CONFIRMADO, REJEITADO, etc.)
                else:
                    # =========================================================
                    # PESQUISA DE SATISFAÇÃO - Processar se etapa_pesquisa ativa
                    # =========================================================
                    if consulta.status == 'CONFIRMADO' and consulta.etapa_pesquisa:
                        
                        # ETAPA 1: NOTA (1-10)
                        if consulta.etapa_pesquisa == 'NOTA':
                            texto_limpo = texto_up.strip()
                            
                            # Verificar se pulou
                            if texto_limpo in ['PULAR', 'NAO', 'NÃO', 'N', 'SKIP']:
                                consulta.etapa_pesquisa = 'CONCLUIDA'
                                # Salvar pesquisa como pulada
                                pesquisa = PesquisaSatisfacao(
                                    consulta_id=consulta.id,
                                    usuario_id=consulta.usuario_id,
                                    tipo_agendamento=consulta.tipo,
                                    especialidade=consulta.especialidade,
                                    pulou=True
                                )
                                db.session.add(pesquisa)
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, "✅ Obrigado! Pesquisa finalizada.", consulta)
                                return jsonify({'status': 'ok'}), 200
                            
                            # Tentar extrair nota
                            try:
                                nota = int(texto_limpo.replace('.', '').replace(',', '')[:2])
                                if 1 <= nota <= 10:
                                    # Salvar nota temporariamente (criar pesquisa)
                                    pesquisa = PesquisaSatisfacao(
                                        consulta_id=consulta.id,
                                        usuario_id=consulta.usuario_id,
                                        tipo_agendamento=consulta.tipo,
                                        especialidade=consulta.especialidade,
                                        nota_satisfacao=nota
                                    )
                                    db.session.add(pesquisa)
                                    consulta.etapa_pesquisa = 'ATENDIMENTO'
                                    db.session.commit()
                                    
                                    # Próxima pergunta
                                    enviar_e_registrar_consulta(ws, numero_resposta, """A equipe foi atenciosa e o processo foi ágil?

*1* - Sim ✅
*2* - Não ❌

_(ou "pular" para finalizar)_""", consulta)
                                    return jsonify({'status': 'ok'}), 200
                                else:
                                    enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, digite um número de *1 a 10*:", consulta)
                                    return jsonify({'status': 'ok'}), 200
                            except:
                                enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, digite um número de *1 a 10*:", consulta)
                                return jsonify({'status': 'ok'}), 200
                        
                        # ETAPA 2: ATENDIMENTO (Sim/Não)
                        elif consulta.etapa_pesquisa == 'ATENDIMENTO':
                            texto_limpo = texto_up.strip()
                            
                            # Buscar pesquisa existente
                            pesquisa = PesquisaSatisfacao.query.filter_by(consulta_id=consulta.id).first()
                            
                            if texto_limpo in ['PULAR', 'NAO', 'N', 'SKIP', 'FINALIZAR']:
                                consulta.etapa_pesquisa = 'CONCLUIDA'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, "✅ Obrigado pela sua avaliação! Sua opinião é muito importante para nós.", consulta)
                                return jsonify({'status': 'ok'}), 200
                            
                            if texto_limpo in ['1', 'SIM', 'S', 'YES']:
                                if pesquisa:
                                    pesquisa.equipe_atenciosa = True
                                consulta.etapa_pesquisa = 'COMENTARIO'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, """Tem algum comentário ou sugestão?

_(Digite sua mensagem ou "N" para finalizar)_""", consulta)
                                return jsonify({'status': 'ok'}), 200
                            
                            elif texto_limpo in ['2', 'NÃO', 'NAO']:
                                if pesquisa:
                                    pesquisa.equipe_atenciosa = False
                                consulta.etapa_pesquisa = 'COMENTARIO'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, """Tem algum comentário ou sugestão?

_(Digite sua mensagem ou "N" para finalizar)_""", consulta)
                                return jsonify({'status': 'ok'}), 200
                            
                            else:
                                enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, responda *1* (Sim) ou *2* (Não):", consulta)
                                return jsonify({'status': 'ok'}), 200
                        
                        # ETAPA 3: COMENTÁRIO
                        elif consulta.etapa_pesquisa == 'COMENTARIO':
                            texto_limpo = texto_up.strip()
                            
                            pesquisa = PesquisaSatisfacao.query.filter_by(consulta_id=consulta.id).first()
                            
                            if texto_limpo not in ['N', 'NAO', 'NÃO', 'PULAR', 'SKIP', 'FINALIZAR']:
                                if pesquisa:
                                    pesquisa.comentario = texto[:500]  # Limitar tamanho
                            
                            consulta.etapa_pesquisa = 'CONCLUIDA'
                            db.session.commit()
                            
                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela sua avaliação!*

Sua opinião é muito importante para continuarmos melhorando nosso atendimento.

_Hospital Universitário Walter Cantídio_""", consulta)
                            return jsonify({'status': 'ok'}), 200
                        
                        # Pesquisa já concluída - ignorar
                        elif consulta.etapa_pesquisa == 'CONCLUIDA':
                            # Não responde mais - fluxo totalmente encerrado
                            return jsonify({'status': 'ok'}), 200
                    
                    # CONFIRMADO sem pesquisa ativa
                    elif consulta.status == 'CONFIRMADO':
                        msg_ja_enviada = LogMsgConsulta.query.filter(
                            LogMsgConsulta.consulta_id == consulta.id,
                            LogMsgConsulta.direcao == 'enviada',
                            LogMsgConsulta.mensagem.like('%já foi confirmada%')
                        ).first()
                        
                        if not msg_ja_enviada:
                            enviar_e_registrar_consulta(ws, numero_resposta, "✅ Sua consulta já foi confirmada. Obrigado!", consulta)
                        # Se já enviou, ignora silenciosamente (fluxo encerrado)
                        
                    elif consulta.status == 'REJEITADO':
                        msg_ja_enviada = LogMsgConsulta.query.filter(
                            LogMsgConsulta.consulta_id == consulta.id,
                            LogMsgConsulta.direcao == 'enviada',
                            LogMsgConsulta.mensagem.like('%foi cancelada%')
                        ).first()
                        if not msg_ja_enviada:
                            enviar_e_registrar_consulta(ws, numero_resposta, """📋 *Registro atualizado!*

Nossa equipe analisará sua resposta e, se necessário, entrará em contato para verificar a melhor opção para você.

Obrigado pelo retorno!

_Hospital Universitário Walter Cantídio_""", consulta)
                        # Se já enviou, ignora silenciosamente (fluxo encerrado)
                        
                    elif consulta.status == 'AGUARDANDO_COMPROVANTE':
                        enviar_e_registrar_consulta(ws, numero_resposta, "✅ Sua consulta está confirmada! Aguarde o envio do comprovante.", consulta)
                    else:
                        enviar_e_registrar_consulta(ws, numero_resposta, "Recebemos sua mensagem. Obrigado!", consulta)

                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # FILA CIRÚRGICA - Processar apenas se NÃO for consulta
        # =====================================================================

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
        
        # Priorizar o contato mais apropriado para responder
        # PRIORIDADE:
        # 0. FILTRAR apenas campanhas do usuário dono da instância (CRÍTICO para multi-usuário)
        # 1. Se a mensagem NÃO é uma resposta válida (1, 2, 3), priorizar campanha concluída recentemente
        # 2. Contatos em fluxo ativo (enviado, aguardando_nascimento) da campanha mais recente
        # 3. Contatos com data_envio mais recente (último a receber mensagem)
        # 4. Contatos com data_resposta mais recente (última interação)
        # 5. Contato mais recente por ID
        c = None

        # CRÍTICO: Filtrar apenas contatos de campanhas do usuário correto
        # Isso evita processar respostas no contexto de outro usuário quando
        # dois usuários diferentes contactam o mesmo paciente
        contatos_validos = [
            t.contato for t in telefones
            if t.contato and t.contato.campanha and t.contato.campanha.criador_id == usuario_id
        ]

        if contatos_validos:
            # Buscar campanhas concluídas e em fluxo ativo
            contatos_concluidos = [ct for ct in contatos_validos if ct.status == 'concluido' and ct.data_resposta]
            contatos_em_fluxo = [ct for ct in contatos_validos if ct.status in ['enviado', 'aguardando_nascimento', 'pronto_envio']]

            # LÓGICA DE PRIORIZAÇÃO:
            # 1. Se há campanha concluída E campanha em fluxo ativo, comparar datas
            # 2. Prioriza a interação mais recente (data_resposta vs data_envio)
            # 3. Se só há uma ou outra, usa a disponível

            if contatos_concluidos and contatos_em_fluxo:
                # Pegar mais recente de cada tipo
                concluido_recente = max(contatos_concluidos, key=lambda ct: (ct.data_resposta, ct.id))

                def get_ultima_data_envio(contato):
                    datas = [t.data_envio for t in contato.telefones if t.data_envio]
                    return max(datas) if datas else datetime.min

                fluxo_recente = max(contatos_em_fluxo, key=lambda ct: (get_ultima_data_envio(ct), ct.id))

                # Comparar: se campanha concluída é mais recente, usar ela
                # Isso garante que "1" após conclusão responde "já confirmou"
                if concluido_recente.data_resposta > get_ultima_data_envio(fluxo_recente):
                    c = concluido_recente
                else:
                    c = fluxo_recente
            elif contatos_concluidos:
                # Só tem concluídas
                c = max(contatos_concluidos, key=lambda ct: (ct.data_resposta, ct.id))
            elif contatos_em_fluxo:
                # Só tem fluxo ativo
                def get_ultima_data_envio(contato):
                    datas = [t.data_envio for t in contato.telefones if t.data_envio]
                    return max(datas) if datas else datetime.min

                c = max(contatos_em_fluxo, key=lambda ct: (get_ultima_data_envio(ct), ct.id))
            else:
                # Nenhuma concluída nem em fluxo, pegar qualquer uma por data_resposta
                c = max(contatos_validos, key=lambda ct: (ct.data_resposta or datetime.min, ct.id))

        if not c:
            # Verificar se existem contatos de outros usuários (para debug)
            todos_contatos = [t.contato for t in telefones if t.contato]
            if todos_contatos:
                outros_usuarios = set(ct.campanha.criador_id for ct in todos_contatos if ct.campanha)
                logger.warning(f"Webhook: Telefone {numero} não tem campanhas do usuário {usuario_id}. "
                             f"Campanhas existem para usuários: {outros_usuarios}")
            else:
                logger.warning(f"Webhook: Telefone {numero} não encontrado em nenhuma campanha")
            return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # FILA CIRÚRGICA - Processar respostas (código original continua abaixo)
        # =====================================================================

        logger.info(f"Webhook: [{instance_name}] Mensagem de {c.nome} ({numero}). "
                   f"Campanha: {c.campanha_id} (User {usuario_id}). Status: {c.status}. Texto: {texto}")

        # PROTEÇÃO CONTRA DUPLICAÇÃO (múltiplos workers do Gunicorn)
        # IMPORTANTE: Criar log IMEDIATAMENTE com commit para bloquear outros workers
        from datetime import timedelta
        cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)
        log_recente = LogMsg.query.filter(
            LogMsg.contato_id == c.id,
            LogMsg.direcao == 'recebida',
            LogMsg.mensagem == texto[:500],
            LogMsg.data >= cinco_segundos_atras
        ).first()

        if log_recente:
            logger.info(f"Mensagem duplicada detectada (já processada há {(datetime.utcnow() - log_recente.data).total_seconds():.1f}s). Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # Análise de sentimento
        analise = AnaliseSentimento.analisar(texto)

        # Criar log IMEDIATAMENTE e commitar ANTES de processar
        # Isso garante que outros workers vejam que já está sendo processado
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
        db.session.commit()  # COMMIT IMEDIATO para bloquear outros workers

        ws = WhatsApp(c.campanha.criador_id)

        # Verificar primeiro se é uma resposta válida da campanha (1, 2, 3)
        # Isso impede que respostas válidas sejam tratadas como FAQ ou tickets
        respostas_validas = (verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM) or
                            verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO) or
                            verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO))

        # Primeiro, tentar responder com FAQ automático
        # IMPORTANTE: NÃO processar FAQ se contato está em fluxo ativo da campanha
        # (status enviado/pronto_envio/aguardando_nascimento devem ir direto para a máquina de estados)
        # EXCEÇÃO: Se status é 'concluido', SEMPRE permitir FAQ (mesmo para respostas válidas como 1, 2, 3)
        resposta_faq = None
        if c.status == 'concluido' or (c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio'] and not respostas_validas):
            # Buscar FAQs globais + FAQs do criador da campanha
            usuario_id = c.campanha.criador_id if c.campanha else None
            resposta_faq = SistemaFAQ.buscar_resposta(texto, usuario_id)

        # Detecção de urgência/prioridade (para badges visuais e notificações)
        # NÃO cria tickets no banco - apenas sinaliza visualmente e notifica usuário
        prioridade = None
        if c.status == 'concluido' or (c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio'] and not respostas_validas):
            prioridade = SistemaFAQ.requer_atendimento_humano(texto, c)

        # Se tem FAQ e NÃO é urgente, responde com FAQ
        if resposta_faq and not prioridade:
            ws.enviar(numero, resposta_faq)
            logger.info(f"FAQ automático enviado para {c.nome}")
            return jsonify({'status': 'ok'}), 200

        # Se é urgente/importante, notifica usuário mas NÃO cria ticket
        # Gestores veem badge visual na lista de contatos
        if prioridade and c.status not in ['aguardando_nascimento', 'enviado', 'pronto_envio']:
            # Se tem FAQ, envia antes da notificação
            if resposta_faq:
                ws.enviar(numero, resposta_faq)
                logger.info(f"FAQ automático enviado antes de notificar urgência para {c.nome}")

            # Notificar usuário sobre encaminhamento (apenas visual, sem ticket)
            if not resposta_faq:
                if prioridade == 'urgente':
                    ws.enviar(numero, "🚨 Sua mensagem foi encaminhada com URGÊNCIA para nossa equipe. "
                                     "Um atendente entrará em contato em breve.")
                else:
                    ws.enviar(numero, "👤 Sua mensagem foi encaminhada para um atendente. "
                                     "Aguarde o retorno em até 24h úteis.")

            logger.info(f"Mensagem urgente detectada de {c.nome} - Prioridade: {prioridade} (badge visual ativo)")
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

            # Encontrar o telefone específico que enviou esta resposta
            telefone_respondente = None
            for t in telefones:
                if t.contato_id == c.id:
                    telefone_respondente = t
                    break

            if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM) or verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                # Determinar tipo de resposta
                tipo_resp = 'confirmado' if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM) else 'rejeitado'

                # SEMPRE pedir Data de Nascimento para validação
                c.status = 'aguardando_nascimento'
                c.resposta = texto # Guarda a intencao original (1 ou 2)
                c.data_resposta = datetime.utcnow()

                # Salvar resposta no telefone específico (aguardando validação)
                if telefone_respondente:
                    telefone_respondente.resposta = texto
                    telefone_respondente.data_resposta = datetime.utcnow()
                    telefone_respondente.tipo_resposta = tipo_resp  # Guarda a intenção
                    telefone_respondente.validacao_pendente = True
                    # Se o telefone respondeu, marcar como WhatsApp válido
                    telefone_respondente.whatsapp_valido = True

                db.session.commit()

                ws.enviar(numero, "🔒 Por segurança, por favor digite sua *Data de Nascimento* (ex: 03/09/1954).")

            elif verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO):
                # Salvar resposta "desconheço" no telefone específico
                if telefone_respondente:
                    telefone_respondente.resposta = texto
                    telefone_respondente.data_resposta = datetime.utcnow()
                    telefone_respondente.tipo_resposta = 'desconheco'
                    telefone_respondente.validacao_pendente = False
                    # Se o telefone respondeu, marcar como WhatsApp válido
                    telefone_respondente.whatsapp_valido = True

                # Recalcular status final do contato baseado em todas as respostas
                # "Desconheço" não é conflito - pode ter outro número confirmado
                c.calcular_status_final()

                # Se não tem nenhuma confirmação/rejeição de outros números, marca erro
                if not c.confirmado and not c.rejeitado:
                    c.erro = "Desconhecido pelo portador"

                db.session.commit()
                c.campanha.atualizar_stats()
                db.session.commit()

                ws.enviar(numero, """✅ *Obrigado pela informação!*

Vamos atualizar nossos registros e remover seu contato da nossa lista.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""")
                
        elif c.status == 'aguardando_nascimento':
            # Encontrar o telefone que está aguardando validação
            telefone_validando = None
            for t in telefones:
                if t.contato_id == c.id and t.validacao_pendente:
                    telefone_validando = t
                    break

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
                    # Data Correta - Confirmar a resposta do telefone
                    if telefone_validando:
                        telefone_validando.validacao_pendente = False
                        # Telefone validado com sucesso, marcar como WhatsApp válido
                        telefone_validando.whatsapp_valido = True

                    # Verificar intencao original
                    intent_up = (c.resposta or '').upper()
                    msg_final = "✅ Obrigado."

                    if verificar_resposta_em_lista(intent_up, RESPOSTAS_SIM):
                        msg_final = """✅ *Confirmação Registrada com Sucesso!*

Obrigado por confirmar seu interesse no procedimento.

📞 *Próximos Passos:*
• Nossa equipe entrará em contato em breve
• Mantenha seu telefone com notificações ativas
• Fique atento às ligações do hospital

❓ *Tem dúvidas?*
Digite sua pergunta a qualquer momento que responderemos!

_Hospital Universitário Walter Cantídio_"""
                    elif verificar_resposta_em_lista(intent_up, RESPOSTAS_NAO):
                        msg_final = """✅ *Registro Atualizado*

Obrigado por sua resposta.

Registramos que você não tem mais interesse no procedimento. Seus dados serão atualizados em nosso sistema.

Se mudar de ideia ou tiver alguma dúvida, pode entrar em contato conosco.

_Hospital Universitário Walter Cantídio_"""

                    # Recalcular status final do contato baseado em todas as respostas validadas
                    c.calcular_status_final()
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


# # =============================================================================
# # ROTAS - ATENDIMENTO (TICKETS)
# # =============================================================================
# 
# @app.route('/atendimento')
# @login_required
# def painel_atendimento():
#     filtro = request.args.get('filtro', 'pendente')
#     page = request.args.get('page', 1, type=int)
# 
#     # Filtrar apenas tickets das campanhas do usuario atual
#     user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]
# 
#     q = TicketAtendimento.query
#     if user_campanhas_ids:
#         q = q.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids))
#     else:
#         # Se nao tem campanhas, nao tem tickets
#         q = q.filter(TicketAtendimento.id == None)
# 
#     if filtro == 'pendente':
#         q = q.filter_by(status='pendente')
#     elif filtro == 'em_atendimento':
#         q = q.filter_by(status='em_atendimento')
#     elif filtro == 'resolvido':
#         q = q.filter_by(status='resolvido')
#     elif filtro == 'meus':
#         q = q.filter_by(atendente_id=current_user.id, status='em_atendimento')
#     elif filtro == 'urgente':
#         q = q.filter_by(prioridade='urgente', status='pendente')
# 
#     # Buscar todos os tickets (nao paginados ainda)
#     all_tickets = q.order_by(
#         TicketAtendimento.prioridade.desc(),
#         TicketAtendimento.data_criacao.desc()
#     ).all()
# 
#     # Agrupar tickets por (contato_id, campanha_id)
#     from collections import defaultdict
#     grupos = defaultdict(list)
#     for ticket in all_tickets:
#         chave = (ticket.contato_id, ticket.campanha_id)
#         grupos[chave].append(ticket)
# 
#     # Criar lista de grupos com informacoes agregadas
#     grupos_lista = []
#     prioridade_ordem = {'urgente': 4, 'alta': 3, 'media': 2, 'baixa': 1}
# 
#     for (contato_id, campanha_id), tickets_grupo in grupos.items():
#         # Ordenar tickets do grupo por data (mais recente primeiro)
#         tickets_grupo.sort(key=lambda t: t.data_criacao, reverse=True)
# 
#         # Pegar a maior prioridade do grupo
#         maior_prioridade = max(tickets_grupo, key=lambda t: prioridade_ordem.get(t.prioridade, 0))
# 
#         grupo_obj = {
#             'tickets': tickets_grupo,
#             'ticket_principal': tickets_grupo[0],  # Mais recente
#             'contato': tickets_grupo[0].contato,
#             'campanha': tickets_grupo[0].campanha,
#             'prioridade': maior_prioridade.prioridade,
#             'status': tickets_grupo[0].status,
#             'data_criacao': tickets_grupo[0].data_criacao,
#             'count': len(tickets_grupo),
#             'atendente': tickets_grupo[0].atendente
#         }
#         grupos_lista.append(grupo_obj)
# 
#     # Ordenar grupos por prioridade e data
#     grupos_lista.sort(
#         key=lambda g: (prioridade_ordem.get(g['prioridade'], 0), g['data_criacao']),
#         reverse=True
#     )
# 
#     # Paginar os grupos
#     per_page = 20
#     total = len(grupos_lista)
#     total_pages = (total + per_page - 1) // per_page
#     start = (page - 1) * per_page
#     end = start + per_page
#     grupos_paginados = grupos_lista[start:end]
# 
#     # Criar objeto de paginacao simulado
#     class PaginacaoSimulada:
#         def __init__(self, items, page, per_page, total):
#             self.items = items
#             self.page = page
#             self.per_page = per_page
#             self.total = total
#             self.pages = (total + per_page - 1) // per_page
#             self.has_prev = page > 1
#             self.has_next = page < self.pages
#             self.prev_num = page - 1 if self.has_prev else None
#             self.next_num = page + 1 if self.has_next else None
# 
#         def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
#             last = 0
#             for num in range(1, self.pages + 1):
#                 if num <= left_edge or \
#                    (num > self.page - left_current - 1 and num < self.page + right_current) or \
#                    num > self.pages - right_edge:
#                     if last + 1 != num:
#                         yield None
#                     yield num
#                     last = num
# 
#     tickets_agrupados = PaginacaoSimulada(grupos_paginados, page, per_page, total)
# 
#     # Estatísticas apenas dos tickets das campanhas do usuario
#     # IMPORTANTE: Contar grupos (contato+campanha), não tickets individuais
#     if user_campanhas_ids:
#         # Buscar tickets pendentes e agrupar
#         tickets_pendentes = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'pendente'
#         ).all()
#         grupos_pendentes = set((t.contato_id, t.campanha_id) for t in tickets_pendentes)
# 
#         # Em atendimento
#         tickets_atendimento = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'em_atendimento'
#         ).all()
#         grupos_atendimento = set((t.contato_id, t.campanha_id) for t in tickets_atendimento)
# 
#         # Urgentes pendentes
#         tickets_urgentes = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.prioridade == 'urgente',
#             TicketAtendimento.status == 'pendente'
#         ).all()
#         grupos_urgentes = set((t.contato_id, t.campanha_id) for t in tickets_urgentes)
# 
#         # Resolvidos hoje
#         tickets_resolvidos = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'resolvido',
#             TicketAtendimento.data_resolucao >= datetime.utcnow().replace(hour=0, minute=0, second=0)
#         ).all()
#         grupos_resolvidos = set((t.contato_id, t.campanha_id) for t in tickets_resolvidos)
# 
#         stats = {
#             'pendente': len(grupos_pendentes),
#             'em_atendimento': len(grupos_atendimento),
#             'urgente': len(grupos_urgentes),
#             'resolvido_hoje': len(grupos_resolvidos)
#         }
#     else:
#         stats = {'pendente': 0, 'em_atendimento': 0, 'urgente': 0, 'resolvido_hoje': 0}
# 
#     return render_template('atendimento.html', tickets=tickets_agrupados, filtro=filtro, stats=stats)
# 
# 
# @app.route('/atendimento/<int:id>')
# @login_required
# def detalhe_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     # Buscar todos os tickets do mesmo grupo (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id
#     ).order_by(TicketAtendimento.data_criacao.desc()).all()
# 
#     # Buscar histórico de mensagens do contato
#     logs = LogMsg.query.filter_by(contato_id=ticket.contato_id).order_by(LogMsg.data.desc()).limit(20).all()
# 
#     return render_template('ticket_detalhe.html', ticket=ticket, tickets_relacionados=tickets_relacionados, logs=logs)
# 
# 
# @app.route('/atendimento/<int:id>/assumir', methods=['POST'])
# @login_required
# def assumir_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     if ticket.status != 'pendente':
#         flash('Ticket já está em atendimento', 'warning')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     # Assumir ticket atual
#     ticket.status = 'em_atendimento'
#     ticket.atendente_id = current_user.id
#     ticket.data_atendimento = datetime.utcnow()
# 
#     # Assumir TODOS os tickets relacionados (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id,
#         status='pendente'
#     ).all()
# 
#     for t in tickets_relacionados:
#         t.status = 'em_atendimento'
#         t.atendente_id = current_user.id
#         t.data_atendimento = datetime.utcnow()
# 
#     db.session.commit()
# 
#     flash(f'✅ {len(tickets_relacionados)} ticket(s) assumido(s)!', 'success')
#     return redirect(url_for('detalhe_ticket', id=id))
# 
# 
# @app.route('/atendimento/<int:id>/responder', methods=['POST'])
# @login_required
# def responder_ticket(id):
#     ticket = verificar_acesso_ticket(id)
#     resposta = request.form.get('resposta', '').strip()
# 
#     if not resposta:
#         flash('Digite uma resposta', 'danger')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     # Enviar via WhatsApp usando a instância do criador da campanha
#     ws = WhatsApp(ticket.campanha.criador_id)
# 
#     # Priorizar telefones validados, mas aceitar todos se não houver validados
#     telefones_validados = ticket.contato.telefones.filter_by(whatsapp_valido=True).all()
#     telefones_todos = ticket.contato.telefones.all()
# 
#     # Usar validados se houver, senão usar todos
#     telefones = telefones_validados if telefones_validados else telefones_todos
# 
#     if not telefones:
#         flash('Nenhum telefone cadastrado para este contato', 'danger')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     enviado = False
#     erro_msg = None
#     for tel in telefones:
#         ok, resultado = ws.enviar(tel.numero_fmt, f"👤 *Resposta do atendente {current_user.nome}:*\n\n{resposta}")
#         if ok:
#             enviado = True
# 
#             # Registrar log
#             log = LogMsg(
#                 campanha_id=ticket.campanha_id,
#                 contato_id=ticket.contato_id,
#                 direcao='enviada',
#                 telefone=tel.numero_fmt,
#                 mensagem=f'[Atendimento] {resposta}',
#                 status='ok'
#             )
#             db.session.add(log)
#             break
#         else:
#             erro_msg = resultado
# 
#     if enviado:
#         # Resolver ticket atual
#         ticket.status = 'resolvido'
#         ticket.data_resolucao = datetime.utcnow()
#         ticket.resposta = resposta
# 
#         # Resolver TODOS os tickets relacionados (mesmo contato e campanha)
#         tickets_relacionados = TicketAtendimento.query.filter_by(
#             contato_id=ticket.contato_id,
#             campanha_id=ticket.campanha_id
#         ).filter(TicketAtendimento.status != 'resolvido').all()
# 
#         for t in tickets_relacionados:
#             t.status = 'resolvido'
#             t.data_resolucao = datetime.utcnow()
#             t.resposta = resposta
# 
#         db.session.commit()
# 
#         flash(f'✅ Resposta enviada e {len(tickets_relacionados)} ticket(s) resolvido(s) com sucesso!', 'success')
#     else:
#         msg_erro = f'❌ Erro ao enviar resposta via WhatsApp'
#         if erro_msg:
#             msg_erro += f': {erro_msg}'
#         flash(msg_erro, 'danger')
# 
#     return redirect(url_for('painel_atendimento'))
# 
# 
# @app.route('/atendimento/<int:id>/cancelar', methods=['POST'])
# @login_required
# def cancelar_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     # Cancelar ticket atual
#     ticket.status = 'cancelado'
# 
#     # Cancelar TODOS os tickets relacionados (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id
#     ).filter(TicketAtendimento.status.in_(['pendente', 'em_atendimento'])).all()
# 
#     for t in tickets_relacionados:
#         t.status = 'cancelado'
# 
#     db.session.commit()
# 
#     flash(f'✅ {len(tickets_relacionados)} ticket(s) cancelado(s)', 'info')
#     return redirect(url_for('painel_atendimento'))
# 
# 
# =============================================================================
# ROTAS - CADASTRO PUBLICO
# =============================================================================

@app.route('/cadastro', methods=['GET', 'POST'])
def cadastro_publico():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        senha_confirm = request.form.get('senha_confirm', '')
        tipo_sistema = request.form.get('tipo_sistema', 'BUSCA_ATIVA').strip()

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

        # Validar tipo_sistema
        if tipo_sistema not in ['BUSCA_ATIVA', 'AGENDAMENTO_CONSULTA']:
            tipo_sistema = 'BUSCA_ATIVA'

        # Verificar se email já existe
        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado', 'danger')
            return render_template('cadastro.html')

        # Criar usuário
        usuario = Usuario(nome=nome, email=email, ativo=True, tipo_sistema=tipo_sistema)
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
    # Usar task Celery em vez de thread
    from tasks import follow_up_automatico_task
    task = follow_up_automatico_task.delay()
    flash(f'Follow-up iniciado (Task ID: {task.id})', 'info')
    return redirect(url_for(get_dashboard_route()))


# =============================================================================
# ROTAS - DASHBOARD DE SENTIMENTOS
# =============================================================================

@app.route('/sentimentos')
@login_required
def dashboard_sentimentos():
    # Filtrar apenas logs das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]

    # Estatísticas de sentimento
    query_sentimento = db.session.query(
        LogMsg.sentimento,
        db.func.count(LogMsg.id)
    ).filter(
        LogMsg.direcao == 'recebida',
        LogMsg.sentimento.isnot(None)
    )

    if user_campanhas_ids:
        query_sentimento = query_sentimento.filter(LogMsg.campanha_id.in_(user_campanhas_ids))

    stats_sentimento = query_sentimento.group_by(LogMsg.sentimento).all()

    # FAQs mais usadas (filtrar por criador ou globais)
    faqs_top = RespostaAutomatica.query.filter(
        RespostaAutomatica.contador_uso > 0,
        db.or_(
            RespostaAutomatica.global_faq == True,
            RespostaAutomatica.criador_id == current_user.id
        )
    ).order_by(RespostaAutomatica.contador_uso.desc()).limit(10).all()

    return render_template('sentimentos.html',
                         stats_sentimento=dict(stats_sentimento),
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
            'procedimento_normalizado': contato.procedimento_normalizado,
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
# =============================================================================
# CELERY TASK STATUS
# =============================================================================

@app.route('/api/task/<task_id>/status')
@login_required
def task_status(task_id):
    """
    Endpoint para verificar status de uma task Celery

    Retorna:
        - state: PENDING, PROGRESS, SUCCESS, FAILURE, RETRY
        - meta: Informações adicionais (progresso, erro, etc)
    """
    if not AsyncResult or not celery_app:
        return jsonify({
            'task_id': task_id,
            'state': 'FAILURE',
            'error': 'Celery não configurado'
        })

    task = AsyncResult(task_id, app=celery_app)

    response = {
        'task_id': task_id,
        'state': task.state,
        'ready': task.ready(),
        'successful': task.successful() if task.ready() else None,
        'failed': task.failed() if task.ready() else None
    }

    if task.state == 'PENDING':
        response['meta'] = {
            'status': 'Aguardando processamento...'
        }
    elif task.state == 'PROGRESS':
        response['meta'] = task.info
    elif task.state == 'SUCCESS':
        response['result'] = task.result
    elif task.state == 'FAILURE':
        response['error'] = str(task.info)
    elif task.state == 'RETRY':
        response['meta'] = task.info
    else:
        response['meta'] = task.info

    return jsonify(response)


@app.route('/api/task/<task_id>/cancel', methods=['POST'])
@login_required
def task_cancel(task_id):
    """
    Cancela uma task Celery em andamento
    """
    if not AsyncResult or not celery_app:
        return jsonify({
            'sucesso': False,
            'task_id': task_id,
            'message': 'Celery não configurado'
        })

    task = AsyncResult(task_id, app=celery_app)
    task.revoke(terminate=True)

    return jsonify({
        'sucesso': True,
        'task_id': task_id,
        'message': 'Task cancelada'
    })


# =============================================================================
# ROTAS - MODO CONSULTA
# =============================================================================

# Importar e inicializar rotas do modo consulta
from consultas_routes import init_consultas_routes
init_consultas_routes(app, db)


# =============================================================================
# INICIALIZACAO
# =============================================================================

with app.app_context():
    db.create_all()
    criar_admin()
    criar_faqs_padrao()
    criar_tutoriais_padrao()


if __name__ == '__main__':
    debug = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)
