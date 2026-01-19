#!/usr/bin/env python3
"""
Script para alterar o modo do usuário admin de FILA para CONSULTA
Execute este script dentro do container Docker:
    docker exec -it busca-ativa-web python3 alterar_modo_admin.py
"""

from app import app, db, Usuario

def alterar_modo_admin():
    with app.app_context():
        print("\n" + "="*70)
        print("🔍 VERIFICANDO USUÁRIOS ADMIN ATUAIS")
        print("="*70 + "\n")

        # Buscar usuários admin
        admins = Usuario.query.filter_by(is_admin=True).all()

        if not admins:
            print("❌ Nenhum usuário admin encontrado!")
            return

        print(f"📋 {len(admins)} usuário(s) admin encontrado(s):\n")
        for i, u in enumerate(admins, 1):
            print(f"{i}. ID: {u.id}")
            print(f"   Nome: {u.nome}")
            print(f"   Email: {u.email}")
            print(f"   Modo Atual: {u.tipo_sistema}")
            print(f"   {'✅' if u.ativo else '❌'} {'Ativo' if u.ativo else 'Inativo'}")
            print()

        print("="*70)
        print("🔄 ALTERANDO MODO PARA: AGENDAMENTO_CONSULTA")
        print("="*70 + "\n")

        # Alterar todos os admins para AGENDAMENTO_CONSULTA
        alterados = 0
        for u in admins:
            modo_antigo = u.tipo_sistema
            u.tipo_sistema = 'AGENDAMENTO_CONSULTA'
            alterados += 1
            print(f"✅ {u.nome} ({u.email})")
            print(f"   {modo_antigo} → AGENDAMENTO_CONSULTA\n")

        # Salvar alterações
        try:
            db.session.commit()
            print("="*70)
            print(f"✅ SUCESSO! {alterados} usuário(s) admin alterado(s)")
            print("="*70 + "\n")

            # Verificar alteração
            print("🔍 VERIFICANDO ALTERAÇÕES:\n")
            admins_atualizados = Usuario.query.filter_by(is_admin=True).all()
            for u in admins_atualizados:
                print(f"✅ {u.nome}: {u.tipo_sistema}")
            print()

        except Exception as e:
            db.session.rollback()
            print(f"\n❌ ERRO ao salvar alterações: {e}")
            print("As alterações foram revertidas.\n")

if __name__ == '__main__':
    alterar_modo_admin()
