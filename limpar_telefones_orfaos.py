#!/usr/bin/env python3
"""
Script para limpar telefones órfãos (sem campanhas associadas)
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, TelefoneConsulta, AgendamentoConsulta

print("=" * 80)
print("LIMPEZA DE TELEFONES ÓRFÃOS")
print("=" * 80)
print()

with app.app_context():
    # 1. Buscar todos os telefones
    print("1. Buscando telefones...")
    todos_telefones = TelefoneConsulta.query.all()
    print(f"   Total de telefones: {len(todos_telefones)}")
    print()

    # 2. Identificar órfãos
    print("2. Identificando telefones órfãos...")
    orfaos = []

    for tel in todos_telefones:
        consulta = AgendamentoConsulta.query.get(tel.consulta_id)
        if not consulta:
            orfaos.append(tel)

    print(f"   Telefones órfãos encontrados: {len(orfaos)}")
    print()

    if not orfaos:
        print("✅ Nenhum telefone órfão encontrado!")
        print()
        print("=" * 80)
        print("SISTEMA LIMPO!")
        print("=" * 80)
        sys.exit(0)

    # 3. Mostrar alguns exemplos
    print("3. Exemplos de telefones órfãos:")
    for tel in orfaos[:10]:
        print(f"   - ID {tel.id}: {tel.numero} (consulta_id: {tel.consulta_id})")
    if len(orfaos) > 10:
        print(f"   ... e mais {len(orfaos) - 10} telefones")
    print()

    # 4. Perguntar confirmação
    resposta = input(f"Deletar {len(orfaos)} telefones órfãos? (s/n): ").strip().lower()

    if resposta != 's':
        print("\n❌ Operação cancelada.")
        sys.exit(0)

    # 5. Deletar
    print()
    print("Deletando telefones órfãos...")
    for tel in orfaos:
        db.session.delete(tel)

    db.session.commit()

    print(f"✅ {len(orfaos)} telefones órfãos deletados!")
    print()
    print("=" * 80)
    print("LIMPEZA CONCLUÍDA!")
    print("=" * 80)
