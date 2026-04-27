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
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, login_manager, csrf
from app.config import BaseConfig, BASE_DIR
from app.services.timezone import (
    TZ_FORTALEZA,
    obter_agora_fortaleza,
    obter_hora_fortaleza,
    obter_hoje_fortaleza,
)
from app.services.telefone import formatar_numero
from app.services.whatsapp import WhatsApp
from app.services.mensagem import (
    formatar_data_consulta,
    enviar_e_registrar_consulta,
    obter_saudacao_dinamica,
    formatar_mensagem_consulta_inicial,
    formatar_mensagem_consulta_retry1,
    formatar_mensagem_consulta_retry2,
    formatar_mensagem_comprovante,
    formatar_mensagem_perguntar_motivo,
    formatar_mensagem_voltar_posto,
    formatar_mensagem_interconsulta_aprovada,
    formatar_mensagem_confirmacao_rejeicao,
    formatar_mensagem_cancelamento_sem_resposta,
    formatar_mensagem_fila_retry1,
    formatar_mensagem_fila_retry2,
    formatar_mensagem_fila_sem_resposta,
)
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

# Importar Celery app configurado com backend Redis
try:
    from celery_app import celery as celery_app
    from celery.result import AsyncResult
except ImportError as e:
    celery_app = None
    AsyncResult = None
    logger.warning(f"Celery não disponível - funcionalidades assíncronas desabilitadas: {e}")

_STATIC_DIR = os.path.join(BASE_DIR, 'static')
app = Flask(
    __name__,
    template_folder=os.path.join(BASE_DIR, 'templates'),
    static_folder=_STATIC_DIR if os.path.isdir(_STATIC_DIR) else None,
)
app.config.from_object(BaseConfig)

os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

db.init_app(app)
csrf.init_app(app)
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Faca login para acessar.'
login_manager.login_message_category = 'warning'

# Constantes
ADMIN_EMAIL = 'admin@huwc.com'
ADMIN_SENHA = 'admin123'
ADMIN_NOME = 'Administrador'

# RESPOSTAS VÁLIDAS - DEVEM SER EXATAS (não aceita palavras soltas em frases)
# Aceita combinações como "1 SIM", "2 NAO" etc.
RESPOSTAS_SIM = [
    'SIM', 'S', '1',
    'CONFIRMO', 'CONFIRMADO',
    'TENHO INTERESSE', 'ACEITO', 'OK',
    '1 SIM', '1SIM', 'SIM 1', 'SIM1'
]
RESPOSTAS_NAO = [
    'NAO', 'NÃO', 'N', '2',
    'NAO QUERO', 'NÃO QUERO',
    'NAO TENHO INTERESSE', 'NÃO TENHO INTERESSE',
    '2 NAO', '2NAO', 'NAO 2', 'NAO2',
    '2 NÃO', '2NÃO', 'NÃO 2', 'NÃO2'
]
RESPOSTAS_DESCONHECO = [
    '3', 'DESCONHECO', 'DESCONHEÇO',
    'NAO SOU', 'NÃO SOU',
    'ENGANO', 'NUMERO ERRADO', 'NÚMERO ERRADO',
    '3 DESCONHECO', '3DESCONHECO', '3 DESCONHEÇO', '3DESCONHEÇO'
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
# MODELOS (movidos para app/models/* — re-exportados aqui pra manter as
# referências usadas pelas rotas em app/main.py)
# =============================================================================

from app.models import *  # noqa: F401,F403
from app.models import (  # noqa: F401  (explicit names for linters)
    Usuario,
    ConfigGlobal, ConfigWhatsApp, RespostaAutomatica, Tutorial,
    ProcedimentoNormalizado,
    Campanha, Contato, Telefone, LogMsg, TicketAtendimento,
    TentativaContato, ConfigTentativas,
    CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta,
    LogMsgConsulta, PesquisaSatisfacao, Paciente,
    ComprovanteAntecipado, HistoricoConsulta,
    normalizar_nome_paciente, buscar_comprovante_antecipado,
    ConfigUsuarioGeral, TIPOS_PERGUNTA, Pesquisa, PerguntaPesquisa,
    RespostaPesquisa, RespostaItem, STATUS_ENVIO_PESQUISA,
    STATUS_ENVIO_TELEFONE, TEMPLATES_PESQUISA, EnvioPesquisa,
    EnvioPesquisaTelefone,
)



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
            # Padrão 1: ESPECIALIDADE em uma linha e o valor na linha seguinte
            r'ESPECIALIDADE\s*\n\s*([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]+(?:\s+[A-ZÁÉÍÓÚÀÂÊÔÃÕÇ]+)*)',
            # Padrão 2: Unidade Funcional com valor na mesma linha
            r'Unidade\s+Funcional[:\s]+(?:AMBULATÓRIO\s+)?([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$|\.|,)',
            # Padrão 3: Especialidade: valor na mesma linha
            r'Especialidade[:\s]+([A-ZÁÉÍÓÚÀÂÊÔÃÕÇ\s]+?)(?:\n|$)',
            # Padrão 4: AMBULATÓRIO seguido do nome
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
            return 'consultas.consultas_dashboard'
        if tipo == 'GERAL':
            return 'geral.geral_dashboard'
        # Aceita tanto BUSCA_ATIVA quanto FILA_CIRURGICA (compatibilidade)
        return 'fila.dashboard'
    return 'auth.login'

@app.context_processor
def inject_dashboard_route():
    """Disponibiliza get_dashboard_route nos templates"""
    return dict(get_dashboard_route=get_dashboard_route)



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
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            flash('❌ Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
            return redirect(url_for(get_dashboard_route()))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# ROTAS
# =============================================================================































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




















# Configuracoes




# =============================================================================
# ADMIN DASHBOARD - Painel de Performance do Sistema
# =============================================================================





















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




# =============================================================================
# ROTAS - FAQ (RESPOSTAS AUTOMATICAS)
# =============================================================================









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



# =============================================================================
# ROTAS - USUÁRIO GERAL (wizard de configuração + dashboard placeholder)
# =============================================================================

TIPOS_USO_GERAL = ['CONFIRMACAO', 'PESQUISA', 'ENQUETE']
CANAIS_RESPOSTA_GERAL = ['WHATSAPP_LINK_EXTERNO', 'WHATSAPP_INTERATIVO', 'LINK_INTERNO']


def _exigir_usuario_geral():
    """Bloqueia acesso a quem não é tipo_sistema='GERAL'. Retorna a config (criando se necessário)."""
    if getattr(current_user, 'tipo_sistema', None) != 'GERAL':
        flash('Esta área é exclusiva de usuários do tipo Geral.', 'warning')
        return None, redirect(url_for(get_dashboard_route()))

    config = ConfigUsuarioGeral.query.filter_by(usuario_id=current_user.id).first()
    if not config:
        config = ConfigUsuarioGeral(usuario_id=current_user.id, wizard_concluido=False)
        db.session.add(config)
        db.session.commit()
    return config, None






# -----------------------------------------------------------------------------
# Pesquisas (CRUD para o usuário GERAL)
# -----------------------------------------------------------------------------

def _get_pesquisa_do_usuario(pesquisa_id):
    """Carrega a pesquisa garantindo que pertence ao usuário logado (ou admin)."""
    from flask import abort
    pesquisa = Pesquisa.query.get_or_404(pesquisa_id)
    if pesquisa.usuario_id != current_user.id and not current_user.is_admin:
        abort(403)
    return pesquisa






















# -----------------------------------------------------------------------------
# Envio em massa do link da pesquisa via WhatsApp
# -----------------------------------------------------------------------------

def _normalizar_telefones_textarea(texto):
    """Recebe texto (uma linha por telefone, opcional 'nome | numero') e devolve
    lista [(numero_formatado, nome_or_None), ...] sem duplicatas, com numero válido.
    """
    seen = set()
    saida = []
    for linha in (texto or '').splitlines():
        linha = linha.strip()
        if not linha:
            continue
        nome = None
        if '|' in linha:
            partes = linha.split('|', 1)
            nome = partes[0].strip() or None
            numero_raw = partes[1].strip()
        else:
            numero_raw = linha
        numero_fmt = formatar_numero(numero_raw)
        if not numero_fmt or numero_fmt in seen:
            continue
        seen.add(numero_fmt)
        saida.append((numero_fmt, nome))
    return saida


def _renderizar_mensagem_envio(mensagem_template, link_publico, nome_destinatario=None):
    """Substitui placeholders na mensagem; se {LINK} ausente, anexa no fim."""
    texto = mensagem_template or ''
    if '{NOME}' in texto:
        texto = texto.replace('{NOME}', nome_destinatario or '')
    if '{LINK}' in texto:
        texto = texto.replace('{LINK}', link_publico)
    else:
        texto = (texto.rstrip() + '\n\n' + link_publico).strip()
    return texto




def _get_envio_do_usuario(envio_id):
    from flask import abort
    envio = EnvioPesquisa.query.get_or_404(envio_id)
    if envio.usuario_id != current_user.id and not current_user.is_admin:
        abort(403)
    return envio












# -----------------------------------------------------------------------------
# Pesquisa pública (formulário web acessado pelo paciente via link)
# -----------------------------------------------------------------------------



# =============================================================================
# ROTAS - TUTORIAL
# =============================================================================





# =============================================================================
# ROTAS - FOLLOW-UP (JOB)
# =============================================================================





# =============================================================================
# ROTAS - DASHBOARD DE SENTIMENTOS
# =============================================================================



# Logs






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





# =============================================================================
# BLUEPRINTS
# =============================================================================

from app.routes import register_blueprints
register_blueprints(app)

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
