"""Cross-cutting models: global config, WhatsApp config, FAQ, tutorial,
procedure normalization cache."""

import json
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.extensions import db


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
