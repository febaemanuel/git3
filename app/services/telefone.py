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
