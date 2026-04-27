"""Comprovante OCR helper (extrair_dados_comprovante).

Originally lived in app/main.py — moved here to keep main.py focused on
constants/wiring and to make the OCR boundary explicit.
"""

import logging
import os
import re

from app.services.timezone import obter_agora_fortaleza  # noqa: F401  (legacy)


logger = logging.getLogger(__name__)


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
