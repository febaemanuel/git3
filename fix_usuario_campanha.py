#!/usr/bin/env python3
"""
Script para diagnosticar e corrigir problema de usuário em campanhas de consulta
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, CampanhaConsulta, AgendamentoConsulta, ConfigWhatsApp, Usuario

print("=" * 70)
print("DIAGNÓSTICO - PROBLEMA DE USUÁRIO EM CAMPANHAS")
print("=" * 70)
print()

with app.app_context():
    # 1. Verificar usuários
    print("1. USUÁRIOS DO SISTEMA:")
    usuarios = Usuario.query.all()
    for u in usuarios:
        tipo = u.tipo_sistema if hasattr(u, 'tipo_sistema') else 'BUSCA_ATIVA'
        print(f"   - ID {u.id}: {u.email} (Tipo: {tipo})")
    print()

    # 2. Verificar configurações de WhatsApp
    print("2. CONFIGURAÇÕES DE WHATSAPP:")
    configs = ConfigWhatsApp.query.all()
    for c in configs:
        usuario = Usuario.query.get(c.usuario_id)
        print(f"   - Usuário {c.usuario_id} ({usuario.email if usuario else 'N/A'})")
        print(f"     Instance: {c.instance_name}")
        print(f"     Conectado: {'SIM' if c.conectado else 'NÃO'}")
    print()

    # 3. Verificar campanhas de consulta
    print("3. CAMPANHAS DE CONSULTA:")
    campanhas = CampanhaConsulta.query.all()

    if not campanhas:
        print("   ⚠ Nenhuma campanha encontrada!")

    for camp in campanhas:
        criador = Usuario.query.get(camp.criador_id)
        print(f"   - Campanha #{camp.id}: {camp.nome}")
        print(f"     Criador: ID {camp.criador_id} ({criador.email if criador else 'N/A'})")
        print(f"     Status: {camp.status}")

        # Verificar se criador tem WhatsApp configurado
        config_criador = ConfigWhatsApp.query.filter_by(usuario_id=camp.criador_id).first()
        if config_criador:
            print(f"     ✅ Criador TEM WhatsApp configurado ({config_criador.instance_name})")
        else:
            print(f"     ❌ Criador NÃO tem WhatsApp configurado!")

        # Contar consultas
        total_consultas = AgendamentoConsulta.query.filter_by(campanha_id=camp.id).count()
        print(f"     Total de consultas: {total_consultas}")
    print()

    # 4. Verificar se há problema de usuário diferente
    print("4. VERIFICANDO CONFLITOS:")
    print()

    problema_encontrado = False

    for camp in campanhas:
        config_criador = ConfigWhatsApp.query.filter_by(usuario_id=camp.criador_id).first()

        if not config_criador:
            print(f"❌ PROBLEMA: Campanha #{camp.id} ({camp.nome})")
            print(f"   Criador: ID {camp.criador_id}")
            print(f"   Problema: Criador não tem WhatsApp configurado!")
            print()
            problema_encontrado = True

            # Verificar se existe outro usuário com WhatsApp
            outras_configs = ConfigWhatsApp.query.filter(
                ConfigWhatsApp.usuario_id != camp.criador_id
            ).all()

            if outras_configs:
                print(f"   💡 SOLUÇÃO: Alterar criador da campanha para usuário com WhatsApp")
                print(f"   Usuários com WhatsApp disponíveis:")
                for cfg in outras_configs:
                    usuario = Usuario.query.get(cfg.usuario_id)
                    print(f"      - ID {cfg.usuario_id}: {usuario.email if usuario else 'N/A'}")
                print()

                # Perguntar se quer corrigir
                resposta = input(f"   Corrigir campanha #{camp.id} para usuário {outras_configs[0].usuario_id}? (s/n): ")

                if resposta.lower() == 's':
                    camp.criador_id = outras_configs[0].usuario_id
                    db.session.commit()
                    print(f"   ✅ Campanha #{camp.id} corrigida! Novo criador: ID {camp.criador_id}")
                    print()

    if not problema_encontrado:
        print("✅ Nenhum problema encontrado! Todas as campanhas têm WhatsApp configurado.")

print()
print("=" * 70)
print("DIAGNÓSTICO COMPLETO")
print("=" * 70)
