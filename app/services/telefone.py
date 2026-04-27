"""Telephone number normalization."""


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

