#!/usr/bin/env python3
"""
Script para deletar usuário e todas as suas campanhas
USO: python deletar_usuario.py febaemanuel
"""

import sys
from app import app, db, Usuario, Campanha, CampanhaConsulta

def deletar_usuario(username_ou_email):
    with app.app_context():
        # Buscar usuário
        usuario = Usuario.query.filter(
            (Usuario.username == username_ou_email) |
            (Usuario.email == username_ou_email)
        ).first()

        if not usuario:
            print(f"❌ Usuário '{username_ou_email}' não encontrado!")
            return

        print(f"\n🔍 Usuário encontrado:")
        print(f"   ID: {usuario.id}")
        print(f"   Username: {usuario.username}")
        print(f"   Email: {usuario.email}")
        print(f"   Nome: {usuario.nome}")
        print(f"   Tipo: {usuario.tipo_sistema}")

        # Contar campanhas
        campanhas_fila = Campanha.query.filter_by(criador_id=usuario.id).count()
        campanhas_consulta = CampanhaConsulta.query.filter_by(criador_id=usuario.id).count()

        print(f"\n📊 Campanhas a serem deletadas:")
        print(f"   Fila Cirúrgica: {campanhas_fila}")
        print(f"   Consultas: {campanhas_consulta}")

        # Confirmação
        print(f"\n⚠️  ATENÇÃO: Esta ação é IRREVERSÍVEL!")
        confirmacao = input("\nDigite 'DELETAR' para confirmar: ")

        if confirmacao != 'DELETAR':
            print("❌ Operação cancelada.")
            return

        print("\n🗑️  Deletando...")

        # Deletar campanhas de fila cirúrgica
        if campanhas_fila > 0:
            Campanha.query.filter_by(criador_id=usuario.id).delete()
            print(f"   ✅ {campanhas_fila} campanhas de fila cirúrgica deletadas")

        # Deletar campanhas de consultas
        if campanhas_consulta > 0:
            CampanhaConsulta.query.filter_by(criador_id=usuario.id).delete()
            print(f"   ✅ {campanhas_consulta} campanhas de consultas deletadas")

        # Deletar usuário
        db.session.delete(usuario)
        db.session.commit()

        print(f"   ✅ Usuário '{usuario.username}' deletado")
        print("\n✅ Operação concluída com sucesso!")

if __name__ == '__main__':
    if len(sys.argv) != 2:
        print("Uso: python deletar_usuario.py <username_ou_email>")
        print("Exemplo: python deletar_usuario.py febaemanuel")
        sys.exit(1)

    deletar_usuario(sys.argv[1])
