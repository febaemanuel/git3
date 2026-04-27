"""Timezone helpers anchored on Fortaleza (UTC-3)."""

from datetime import datetime

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
