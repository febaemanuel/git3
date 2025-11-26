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
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)
    ultimo_acesso = db.Column(db.DateTime)

    def set_password(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)


class ConfigWhatsApp(db.Model):
    __tablename__ = 'config_whatsapp'
    id = db.Column(db.Integer, primary_key=True)
    api_url = db.Column(db.String(200))
    instance_name = db.Column(db.String(100))
    api_key = db.Column(db.String(200))
    ativo = db.Column(db.Boolean, default=False)
    tempo_entre_envios = db.Column(db.Integer, default=15)
    limite_diario = db.Column(db.Integer, default=100)
    atualizado_em = db.Column(db.DateTime, default=datetime.utcnow)

    @classmethod
    def get(cls):
        c = cls.query.first()
        if not c:
            c = cls()
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
        
        self.total_enviados = self.contatos.filter_by(status='enviado').count() # Ou concluido/aguardando
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


class Contato(db.Model):
    __tablename__ = 'contatos'
    id = db.Column(db.Integer, primary_key=True)
    campanha_id = db.Column(db.Integer, db.ForeignKey('campanhas.id'), nullable=False)

    nome = db.Column(db.String(200), nullable=False)
    data_nascimento = db.Column(db.Date) # NOVO
    procedimento = db.Column(db.String(500))
    
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
    data_criacao = db.Column(db.DateTime, default=datetime.utcnow)

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
    def buscar_resposta(texto):
        """Busca resposta automática baseada no texto"""
        texto_lower = texto.lower()

        # Buscar no banco de dados
        faqs = RespostaAutomatica.query.filter_by(ativa=True).order_by(RespostaAutomatica.prioridade.desc()).all()

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
# SERVICO WHATSAPP
# =============================================================================

class WhatsApp:
    def __init__(self):
        c = ConfigWhatsApp.get()
        self.url = (c.api_url or '').rstrip('/')
        self.instance = c.instance_name or ''
        self.key = c.api_key or ''
        self.ativo = c.ativo

    def ok(self):
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

        # Salvar no Banco
        for chave, dados in pessoas.items():
            if not dados['telefones']:
                continue
                
            c = Contato(
                campanha_id=campanha_id,
                nome=dados['nome'][:200],
                data_nascimento=dados['nascimento'],
                procedimento=dados['procedimento'][:500],
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

            ws = WhatsApp()
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

            ws = WhatsApp()
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

                if enviados_pessoas >= camp.limite_diario:
                    camp.status = 'pausada'
                    camp.status_msg = f'Limite diario atingido ({camp.limite_diario} pessoas)'
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
                    msg = camp.mensagem.replace('{nome}', c.nome).replace('{procedimento}', c.procedimento or 'o procedimento')
                    
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

            ws = WhatsApp()
            if not ws.ok():
                logger.error("WhatsApp não configurado")
                return

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
            }
        ]

        for faq_data in faqs_padrao:
            faq = RespostaAutomatica(
                categoria=faq_data['categoria'],
                resposta=faq_data['resposta'],
                prioridade=faq_data['prioridade']
            )
            faq.set_gatilhos(faq_data['gatilhos'])
            db.session.add(faq)

        db.session.commit()
        logger.info("FAQs padrão criadas")

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
                'descricao': 'Introdução ao sistema',
                'conteudo': '''
<h4>Bem-vindo!</h4>
<p>Este sistema foi desenvolvido para gerenciar campanhas de busca ativa de pacientes em lista de espera cirúrgica.</p>

<h5>Principais funcionalidades:</h5>
<ul>
    <li>📊 <strong>Dashboard:</strong> Visão geral de todas as campanhas</li>
    <li>📋 <strong>Campanhas:</strong> Criar e gerenciar campanhas de contato</li>
    <li>⚙️ <strong>Configurações:</strong> Conectar WhatsApp via Evolution API</li>
    <li>👤 <strong>Atendimento:</strong> Responder dúvidas complexas</li>
    <li>💬 <strong>FAQ:</strong> Respostas automáticas para dúvidas frequentes</li>
</ul>

<div class="alert alert-info">
    <strong>Dica:</strong> Comece configurando o WhatsApp nas Configurações antes de criar sua primeira campanha.
</div>
                '''
            },
            {
                'titulo': 'Como Criar uma Campanha',
                'categoria': 'campanhas',
                'ordem': 2,
                'descricao': 'Passo a passo para criar campanhas',
                'conteudo': '''
<h4>Criando sua primeira campanha</h4>

<h5>Passo 1: Preparar a planilha</h5>
<p>A planilha Excel deve conter as seguintes colunas:</p>
<ul>
    <li><strong>Nome</strong> (obrigatório): Nome do paciente</li>
    <li><strong>Telefone</strong> (obrigatório): Número com DDD</li>
    <li><strong>Nascimento</strong> (opcional): Data de nascimento (DD/MM/AAAA)</li>
    <li><strong>Procedimento</strong> (opcional): Nome do procedimento</li>
</ul>

<h5>Passo 2: Upload e configuração</h5>
<ol>
    <li>Clique em "Nova Campanha" no Dashboard</li>
    <li>Preencha o nome e descrição</li>
    <li>Personalize a mensagem (use {nome} e {procedimento})</li>
    <li>Faça upload da planilha</li>
    <li>Configure limite diário e tempo entre envios</li>
</ol>

<h5>Passo 3: Iniciar envios</h5>
<p>Após criar a campanha, você pode:</p>
<ul>
    <li><strong>Validar números:</strong> Verifica quais têm WhatsApp (opcional)</li>
    <li><strong>Iniciar envios:</strong> Começa a enviar as mensagens</li>
</ul>

<div class="alert alert-warning">
    <strong>Atenção:</strong> O WhatsApp deve estar conectado antes de iniciar os envios!
</div>
                '''
            },
            {
                'titulo': 'Configurando o WhatsApp',
                'categoria': 'configuracoes',
                'ordem': 3,
                'descricao': 'Como conectar o WhatsApp',
                'conteudo': '''
<h4>Conectando o WhatsApp</h4>

<h5>Requisitos:</h5>
<ul>
    <li>Evolution API instalada e rodando</li>
    <li>URL da API</li>
    <li>Nome da instância</li>
    <li>API Key</li>
</ul>

<h5>Passo a passo:</h5>
<ol>
    <li>Vá em <strong>Configurações</strong> no menu</li>
    <li>Preencha os dados da Evolution API</li>
    <li>Ative o checkbox "WhatsApp Ativo"</li>
    <li>Clique em "Salvar"</li>
    <li>Clique em "Gerar QR Code"</li>
    <li>Escaneie o QR Code com o WhatsApp do celular</li>
</ol>

<div class="alert alert-success">
    <strong>Pronto!</strong> Quando conectado, você verá um indicador verde no topo da página.
</div>
                '''
            },
            {
                'titulo': 'Sistema de Atendimento',
                'categoria': 'atendimento',
                'ordem': 4,
                'descricao': 'Como usar o painel de atendimento',
                'conteudo': '''
<h4>Atendimento de Tickets</h4>

<p>O sistema cria tickets automaticamente quando detecta:</p>
<ul>
    <li>🚨 Mensagens urgentes (palavras como "emergência", "urgente", "dor")</li>
    <li>😠 Mensagens de insatisfação</li>
    <li>❓ Dúvidas complexas</li>
    <li>📝 Mensagens muito longas</li>
</ul>

<h5>Como atender um ticket:</h5>
<ol>
    <li>Vá em <strong>Atendimento</strong> no menu</li>
    <li>Veja a lista de tickets pendentes</li>
    <li>Clique em um ticket para ver detalhes</li>
    <li>Clique em "Assumir Ticket"</li>
    <li>Digite sua resposta e clique em "Enviar"</li>
</ol>

<p>A resposta será enviada automaticamente via WhatsApp para o paciente!</p>

<div class="alert alert-info">
    <strong>Dica:</strong> Tickets urgentes aparecem em vermelho e devem ser atendidos primeiro.
</div>
                '''
            }
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
        if not Usuario.query.filter_by(email=ADMIN_EMAIL).first():
            u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL)
            u.set_password(ADMIN_SENHA)
            db.session.add(u)
            db.session.commit()
            logger.info(f"Admin criado: {ADMIN_EMAIL}")
    except Exception as e:
        logger.warning(f"Erro ao criar admin (banco desatualizado?): {e}")
        # Tentar recriar tabelas
        db.session.rollback()
        db.drop_all()
        db.create_all()
        u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL)
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
    camps = Campanha.query.order_by(Campanha.data_criacao.desc()).all()
    for c in camps:
        c.atualizar_stats()

    ws = WhatsApp()
    ws_ativo = ws.ok()
    ws_conn = False
    if ws_ativo:
        ws_conn, _ = ws.conectado()

    stats = {
        'campanhas': Campanha.query.count(),
        'contatos': Contato.query.count(),
        'confirmados': Contato.query.filter_by(confirmado=True).count(),
        'rejeitados': Contato.query.filter_by(rejeitado=True).count()
    }

    return render_template('dashboard.html', campanhas=camps, whatsapp_ativo=ws_ativo,
                           whatsapp_conectado=ws_conn, mensagem_padrao=MENSAGEM_PADRAO, stats=stats)


@app.route('/campanha/criar', methods=['POST'])
@login_required
def criar_campanha():
    nome = request.form.get('nome', '').strip()
    msg = request.form.get('mensagem', MENSAGEM_PADRAO).strip()
    limite = int(request.form.get('limite_diario', 50))
    tempo = int(request.form.get('tempo_entre_envios', 15))

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
        limite_diario=limite,
        tempo_entre_envios=tempo,
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
    camp = Campanha.query.get_or_404(id)
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
    camp = Campanha.query.get_or_404(id)
    if camp.status in ['validando', 'em_andamento']:
        return jsonify({'erro': 'Ja em processamento'}), 400

    ws = WhatsApp()
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    t = threading.Thread(target=validar_campanha_bg, args=(id,))
    t.daemon = True
    t.start()

    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/iniciar', methods=['POST'])
@login_required
def iniciar_campanha(id):
    camp = Campanha.query.get_or_404(id)
    if camp.status == 'em_andamento':
        return jsonify({'erro': 'Ja em andamento'}), 400
    
    # Verifica se tem pendentes ou prontos
    pendentes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhum contato para enviar'}), 400

    ws = WhatsApp()
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
    camp = Campanha.query.get_or_404(id)
    camp.status = 'pausada'
    camp.status_msg = 'Pausada'
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/retomar', methods=['POST'])
@login_required
def retomar_campanha(id):
    camp = Campanha.query.get_or_404(id)
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
    camp = Campanha.query.get_or_404(id)
    camp.status = 'cancelada'
    camp.status_msg = 'Cancelada'
    db.session.commit()
    return jsonify({'sucesso': True})


@app.route('/campanha/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_campanha(id):
    camp = Campanha.query.get_or_404(id)
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
    camp = Campanha.query.get_or_404(id)

    dados = []
    for c in camp.contatos.order_by(Contato.id).all():
        dados.append({
            'Nome': c.nome,
            'Nascimento': c.data_nascimento.strftime('%d/%m/%Y') if c.data_nascimento else '',
            'Telefones': c.telefones_str(),
            'Procedimento': c.procedimento,
            'Status': c.status_texto(),
            'Enviado': 'Sim' if c.status == 'enviado' or c.confirmado or c.rejeitado else 'Nao',
            'Data Envio': c.data_envio.strftime('%d/%m/%Y %H:%M') if c.data_envio else '',
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
    urgentes = TicketAtendimento.query.filter_by(status='pendente', prioridade='urgente').count()
    pendentes = TicketAtendimento.query.filter_by(status='pendente').count()
    return jsonify({'urgentes': urgentes, 'pendentes': pendentes})


@app.route('/api/campanha/<int:id>/status')
@login_required
def api_status(id):
    camp = Campanha.query.get_or_404(id)
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
    c = Contato.query.get_or_404(id)
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
    c = Contato.query.get_or_404(id)
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
    c = Contato.query.get_or_404(id)
    ws = WhatsApp()
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
        c.data_envio = datetime.utcnow()
        db.session.commit()
        return jsonify({'sucesso': True})
    else:
        c.erro = "; ".join(erros)
        db.session.commit()
        return jsonify({'erro': c.erro}), 400


@app.route('/api/contato/<int:id>/revalidar', methods=['POST'])
@login_required
def api_revalidar(id):
    c = Contato.query.get_or_404(id)
    ws = WhatsApp()
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
    c = Contato.query.get_or_404(id)
    
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
@app.route('/configuracoes', methods=['GET', 'POST'])
@login_required
def configuracoes():
    cfg = ConfigWhatsApp.get()

    if request.method == 'POST':
        cfg.api_url = request.form.get('api_url', '').strip().rstrip('/')
        cfg.instance_name = request.form.get('instance_name', '').strip()
        cfg.api_key = request.form.get('api_key', '').strip()
        cfg.ativo = request.form.get('ativo') == 'on'
        cfg.tempo_entre_envios = int(request.form.get('tempo_entre_envios', 15))
        cfg.limite_diario = int(request.form.get('limite_diario', 100))
        cfg.atualizado_em = datetime.utcnow()
        db.session.commit()
        flash('Salvo!', 'success')
        return redirect(url_for('configuracoes'))

    ws = WhatsApp()
    conn, msg = ws.conectado() if ws.ok() else (False, 'Nao configurado')

    return render_template('configuracoes.html', config=cfg, conectado=conn, status_msg=msg)


@app.route('/api/whatsapp/qrcode')
@login_required
def api_qrcode():
    ws = WhatsApp()
    if not ws.ok():
        return jsonify({'erro': 'Nao configurado'}), 400

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
    ws = WhatsApp()
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

        numero = ''.join(filter(str.isdigit, key.get('remoteJid', '').replace('@s.whatsapp.net', '')))
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
        
        # Priorizar contatos nao concluidos
        c = None
        for t in telefones:
            if t.contato and t.contato.status != 'concluido':
                c = t.contato
                break
        
        # Se todos concluidos, pega o mais recente
        if not c and telefones:
            t = telefones[-1]  # Ultimo (mais recente)
            c = t.contato
            
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

        ws = WhatsApp()

        # Verificar se precisa criar ticket para atendimento humano
        prioridade_ticket = SistemaFAQ.requer_atendimento_humano(texto, c)
        if prioridade_ticket and c.status not in ['aguardando_nascimento']:
            ticket = TicketAtendimento(
                contato_id=c.id,
                campanha_id=c.campanha_id,
                mensagem_usuario=texto,
                status='pendente',
                prioridade=prioridade_ticket
            )
            db.session.add(ticket)
            db.session.commit()

            # Notificar usuário
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
        if c.status in ['enviado', 'pronto_envio']:
            if any(r in texto_up for r in RESPOSTAS_SIM) or any(r in texto_up for r in RESPOSTAS_NAO):
                # Pedir Data de Nascimento para AMBOS
                c.status = 'aguardando_nascimento'
                c.resposta = texto # Guarda a intencao original (1 ou 2)
                c.data_resposta = datetime.utcnow()
                db.session.commit()
                
                ws.enviar(numero, "🔒 Por segurança, por favor digite sua *Data de Nascimento* (ex: 03/09/1954).")
                
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
                
                ws.enviar(numero, "✅ Obrigado. Vamos atualizar nossos registros.")
                
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
                        msg_final = "✅ *Confirmado*! Obrigado por confirmar seu interesse."
                    elif any(r in intent_up for r in RESPOSTAS_NAO):
                        c.confirmado = False
                        c.rejeitado = True
                        msg_final = "✅ Obrigado. Registramos que você não tem interesse."
                    
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
            # Tentar resposta automática (FAQ) primeiro
            resposta_faq = SistemaFAQ.buscar_resposta(texto)
            if resposta_faq:
                ws.enviar(numero, resposta_faq)
            else:
                # Se o usuario mandar mensagem depois de concluido, reforcar o status
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
    faqs = RespostaAutomatica.query.order_by(RespostaAutomatica.prioridade.desc()).all()
    return render_template('faq.html', faqs=faqs)


@app.route('/faq/criar', methods=['POST'])
@login_required
def criar_faq():
    categoria = request.form.get('categoria', '').strip()
    resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    prioridade = int(request.form.get('prioridade', 1))

    if not categoria or not resposta or not gatilhos_str:
        flash('Preencha todos os campos', 'danger')
        return redirect(url_for('gerenciar_faq'))

    # Converter gatilhos de string para lista
    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]

    faq = RespostaAutomatica(
        categoria=categoria,
        resposta=resposta,
        prioridade=prioridade
    )
    faq.set_gatilhos(gatilhos)
    db.session.add(faq)
    db.session.commit()

    flash('FAQ criado com sucesso!', 'success')
    return redirect(url_for('gerenciar_faq'))


@app.route('/faq/<int:id>/editar', methods=['POST'])
@login_required
def editar_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)

    faq.categoria = request.form.get('categoria', '').strip()
    faq.resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    faq.prioridade = int(request.form.get('prioridade', 1))
    faq.ativa = request.form.get('ativa') == 'on'

    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]
    faq.set_gatilhos(gatilhos)

    db.session.commit()
    flash('FAQ atualizado!', 'success')
    return redirect(url_for('gerenciar_faq'))


@app.route('/faq/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)
    db.session.delete(faq)
    db.session.commit()
    flash('FAQ excluído!', 'success')
    return redirect(url_for('gerenciar_faq'))


# =============================================================================
# ROTAS - ATENDIMENTO (TICKETS)
# =============================================================================

@app.route('/atendimento')
@login_required
def painel_atendimento():
    filtro = request.args.get('filtro', 'pendente')
    page = request.args.get('page', 1, type=int)

    q = TicketAtendimento.query

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

    # Estatísticas
    stats = {
        'pendente': TicketAtendimento.query.filter_by(status='pendente').count(),
        'em_atendimento': TicketAtendimento.query.filter_by(status='em_atendimento').count(),
        'urgente': TicketAtendimento.query.filter_by(prioridade='urgente', status='pendente').count(),
        'resolvido_hoje': TicketAtendimento.query.filter(
            TicketAtendimento.status == 'resolvido',
            TicketAtendimento.data_resolucao >= datetime.utcnow().replace(hour=0, minute=0, second=0)
        ).count()
    }

    return render_template('atendimento.html', tickets=tickets, filtro=filtro, stats=stats)


@app.route('/atendimento/<int:id>')
@login_required
def detalhe_ticket(id):
    ticket = TicketAtendimento.query.get_or_404(id)
    # Buscar histórico de mensagens do contato
    logs = LogMsg.query.filter_by(contato_id=ticket.contato_id).order_by(LogMsg.data.desc()).limit(20).all()
    return render_template('ticket_detalhe.html', ticket=ticket, logs=logs)


@app.route('/atendimento/<int:id>/assumir', methods=['POST'])
@login_required
def assumir_ticket(id):
    ticket = TicketAtendimento.query.get_or_404(id)

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
    ticket = TicketAtendimento.query.get_or_404(id)
    resposta = request.form.get('resposta', '').strip()

    if not resposta:
        flash('Digite uma resposta', 'danger')
        return redirect(url_for('detalhe_ticket', id=id))

    # Enviar via WhatsApp
    ws = WhatsApp()
    telefones = ticket.contato.telefones.filter_by(whatsapp_valido=True).all()

    if not telefones:
        flash('Nenhum telefone válido para enviar resposta', 'danger')
        return redirect(url_for('detalhe_ticket', id=id))

    enviado = False
    for tel in telefones:
        ok, _ = ws.enviar(tel.numero_fmt, f"👤 *Resposta do atendente {current_user.nome}:*\n\n{resposta}")
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

    if enviado:
        # Resolver ticket
        ticket.status = 'resolvido'
        ticket.data_resolucao = datetime.utcnow()
        ticket.resposta = resposta
        db.session.commit()

        flash('Resposta enviada e ticket resolvido!', 'success')
    else:
        flash('Erro ao enviar resposta', 'danger')

    return redirect(url_for('painel_atendimento'))


@app.route('/atendimento/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar_ticket(id):
    ticket = TicketAtendimento.query.get_or_404(id)
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
    camps = Campanha.query.order_by(Campanha.data_criacao.desc()).all()

    return render_template('logs.html', logs=logs, campanhas=camps, campanha_id=camp_id, direcao=direcao)


@app.route('/relatorios')
@login_required
def relatorios():
    """Página de relatórios com dashboard executivo"""
    campanhas = Campanha.query.order_by(Campanha.data_criacao.desc()).all()

    # Se houver uma campanha selecionada via query param
    campanha_id = request.args.get('campanha_id', type=int)
    campanha_selecionada = None
    if campanha_id:
        campanha_selecionada = Campanha.query.get(campanha_id)

    return render_template('relatorios.html',
                          campanhas=campanhas,
                          campanha_selecionada=campanha_selecionada)


@app.route('/api/relatorios/<int:campanha_id>')
@login_required
def api_relatorios(campanha_id):
    """API para retornar dados de relatórios de uma campanha específica"""
    campanha = Campanha.query.get_or_404(campanha_id)

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

        contatos_data.append({
            'id': contato.id,
            'nome': contato.nome,
            'telefone': telefone_str,
            'procedimento': contato.procedimento,
            'status': contato.status,
            'confirmado': contato.confirmado,
            'rejeitado': contato.rejeitado,
            'erro': contato.erro,
            'data_envio': contato.data_envio.isoformat() if contato.data_envio else None,
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
