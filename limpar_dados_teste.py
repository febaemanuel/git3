#!/usr/bin/env python3
"""
Script para LIMPAR dados de teste e validar integridade do sistema
ATENÇÃO: Este script vai DELETAR usuários e campanhas de teste!
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db, Usuario, CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta, LogMsgConsulta, ConfigWhatsApp

print("=" * 80)
print("LIMPEZA DE DADOS DE TESTE - MODO CONSULTA")
print("=" * 80)
print()

with app.app_context():
    # 1. Listar usuários febaemanuel
    print("1. IDENTIFICANDO USUÁRIOS DE TESTE (febaemanuel*)...")
    usuarios_teste = Usuario.query.filter(Usuario.email.like('%febaemanuel%')).all()

    print(f"   Encontrados {len(usuarios_teste)} usuários de teste:")
    for u in usuarios_teste:
        tipo = getattr(u, 'tipo_sistema', 'BUSCA_ATIVA')
        print(f"   - ID {u.id}: {u.email} (Tipo: {tipo})")
    print()

    # 2. Contar campanhas de consulta desses usuários
    print("2. CAMPANHAS DE CONSULTA DESSES USUÁRIOS:")
    ids_usuarios_teste = [u.id for u in usuarios_teste]
    campanhas_teste = CampanhaConsulta.query.filter(
        CampanhaConsulta.criador_id.in_(ids_usuarios_teste)
    ).all()

    print(f"   Total de campanhas: {len(campanhas_teste)}")
    for camp in campanhas_teste:
        consultas_count = AgendamentoConsulta.query.filter_by(campanha_id=camp.id).count()
        print(f"   - Campanha #{camp.id}: {camp.nome or '(sem nome)'} - {consultas_count} consultas - Status: {camp.status}")
    print()

    # 3. Perguntar confirmação
    print("⚠️  ATENÇÃO: Esta operação é IRREVERSÍVEL!")
    print()
    resposta = input("Deseja DELETAR todos esses usuários e campanhas? (s/n): ").strip().lower()

    if resposta != 's':
        print("\n❌ Operação cancelada pelo usuário.")
        sys.exit(0)

    print()
    print("=" * 80)
    print("INICIANDO LIMPEZA...")
    print("=" * 80)
    print()

    # 4. Deletar em ordem correta (respeitando foreign keys)
    total_deletado = {
        'logs': 0,
        'telefones': 0,
        'consultas': 0,
        'campanhas': 0,
        'configs_whatsapp': 0,
        'usuarios': 0
    }

    for camp in campanhas_teste:
        print(f"Deletando campanha #{camp.id}...")

        # 4.1 Deletar logs de mensagens
        logs = LogMsgConsulta.query.filter_by(campanha_id=camp.id).all()
        for log in logs:
            db.session.delete(log)
        total_deletado['logs'] += len(logs)

        # 4.2 Deletar telefones das consultas
        consultas = AgendamentoConsulta.query.filter_by(campanha_id=camp.id).all()
        for consulta in consultas:
            telefones = TelefoneConsulta.query.filter_by(consulta_id=consulta.id).all()
            for tel in telefones:
                db.session.delete(tel)
            total_deletado['telefones'] += len(telefones)

            # 4.3 Deletar consulta
            db.session.delete(consulta)
            total_deletado['consultas'] += 1

        # 4.4 Deletar campanha
        db.session.delete(camp)
        total_deletado['campanhas'] += 1

    db.session.commit()
    print(f"✅ Campanhas deletadas: {total_deletado['campanhas']}")
    print(f"✅ Consultas deletadas: {total_deletado['consultas']}")
    print(f"✅ Telefones deletados: {total_deletado['telefones']}")
    print(f"✅ Logs deletados: {total_deletado['logs']}")
    print()

    # 5. Deletar configurações de WhatsApp
    for u in usuarios_teste:
        config = ConfigWhatsApp.query.filter_by(usuario_id=u.id).first()
        if config:
            db.session.delete(config)
            total_deletado['configs_whatsapp'] += 1

    db.session.commit()
    print(f"✅ Configurações WhatsApp deletadas: {total_deletado['configs_whatsapp']}")
    print()

    # 6. Deletar usuários
    for u in usuarios_teste:
        print(f"Deletando usuário ID {u.id}: {u.email}")
        db.session.delete(u)
        total_deletado['usuarios'] += 1

    db.session.commit()
    print(f"✅ Usuários deletados: {total_deletado['usuarios']}")
    print()

    print("=" * 80)
    print("LIMPEZA CONCLUÍDA COM SUCESSO!")
    print("=" * 80)
    print()
    print("RESUMO:")
    print(f"  ✅ {total_deletado['usuarios']} usuários de teste removidos")
    print(f"  ✅ {total_deletado['configs_whatsapp']} configurações WhatsApp removidas")
    print(f"  ✅ {total_deletado['campanhas']} campanhas removidas")
    print(f"  ✅ {total_deletado['consultas']} consultas removidas")
    print(f"  ✅ {total_deletado['telefones']} telefones removidos")
    print(f"  ✅ {total_deletado['logs']} logs removidos")
    print()

    # 7. Verificar integridade restante
    print("=" * 80)
    print("VERIFICANDO INTEGRIDADE DO SISTEMA...")
    print("=" * 80)
    print()

    # Verificar campanhas órfãs (sem usuário válido)
    campanhas_restantes = CampanhaConsulta.query.all()
    print(f"Campanhas restantes: {len(campanhas_restantes)}")

    campanhas_orfas = []
    for camp in campanhas_restantes:
        usuario = Usuario.query.get(camp.criador_id)
        if not usuario:
            campanhas_orfas.append(camp)
            print(f"  ⚠️  ÓRFÃ: Campanha #{camp.id} tem criador_id={camp.criador_id} (usuário não existe!)")
        else:
            config = ConfigWhatsApp.query.filter_by(usuario_id=camp.criador_id).first()
            if not config:
                print(f"  ⚠️  SEM WHATSAPP: Campanha #{camp.id} - Usuário {usuario.email} não tem WhatsApp!")

    print()

    if campanhas_orfas:
        print(f"❌ ERRO: {len(campanhas_orfas)} campanhas órfãs encontradas!")
        print("   Recomendação: Execute novamente para limpar ou atribua a um usuário válido")
    else:
        print("✅ Nenhuma campanha órfã encontrada!")

    print()
    print("=" * 80)
    print("SISTEMA LIMPO E VALIDADO!")
    print("=" * 80)
