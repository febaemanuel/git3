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
        
        # Contar enviados: todos que ja receberam a mensagem (enviado, aguardando_nascimento, concluido)
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
    data = db.Column(db.DateTime, default=datetime.utcnow)

    # Relationships
    campanha = db.relationship('Campanha', backref='logs')
    contato = db.relationship('Contato', backref='logs_msg')


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
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='enviado')
                            db.session.add(log)
                        else:
                            log = LogMsg(campanha_id=camp.id, contato_id=c.id, direcao='enviada',
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='erro', erro=result)
                            db.session.add(log)

                    # Atualizar status do contato
                    if sucesso_pessoa:
                        c.status = 'enviado'
                        enviados_pessoas += 1
                    else:
                        c.erro = 'Falha ao enviar para todos os números'

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

    # Deletar logs relacionados primeiro (evita erro de Foreign Key)
    LogMsg.query.filter_by(campanha_id=id).delete()

    # Deletar logs de contatos específicos
    for contato in camp.contatos.all():
        LogMsg.query.filter_by(contato_id=contato.id).delete()

    db.session.delete(camp)
    db.session.commit()
    flash('Campanha excluída com sucesso!', 'success')
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
        else:
            c.data_nascimento = None
        
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

        # Log da mensagem recebida
        log = LogMsg(campanha_id=c.campanha_id, contato_id=c.id, direcao='recebida',
                     telefone=numero, mensagem=texto[:500], status='recebido')
        db.session.add(log)
        db.session.commit()
        
        ws = WhatsApp()

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
                # Verificar se temos data de nascimento cadastrada
                if not c.data_nascimento:
                    # Sem data cadastrada - aceitar qualquer data e prosseguir
                    # (ou pode-se rejeitar - depende da regra de negócio)
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
                    logger.info(f"Contato {c.id} confirmado sem data de nascimento cadastrada")

                elif dt_input == c.data_nascimento:
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


if __name__ == '__main__':
    debug = os.environ.get('DEBUG', 'True').lower() in ('true', '1', 'yes')
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=debug, host='0.0.0.0', port=port)
