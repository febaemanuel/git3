"""AI / heuristic helpers: sentiment analysis, FAQ matching, DeepSeek wrappers.

Lifted out of app/main.py.
"""

import json
import logging
import os
import re
import time
from datetime import datetime, timedelta

import requests

from app.extensions import db
from app.models import LogMsg, ProcedimentoNormalizado, RespostaAutomatica


logger = logging.getLogger(__name__)


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
