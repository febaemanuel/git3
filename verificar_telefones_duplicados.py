#!/usr/bin/env python3
"""
Script para verificar telefones duplicados em campanhas de consultas
de usuários diferentes - isso causa respostas duplicadas no webhook
"""

from app import app, db, TelefoneConsulta

def verificar_duplicados():
    with app.app_context():
        # Buscar todos os telefones de consultas
        telefones = db.session.query(
            TelefoneConsulta.numero,
            db.func.count(db.distinct(TelefoneConsulta.consulta_id)).label('total_consultas'),
            db.func.count(db.distinct(db.text('campanhas_consultas.criador_id'))).label('total_usuarios')
        ).join(
            TelefoneConsulta.consulta
        ).join(
            'campanha'
        ).group_by(
            TelefoneConsulta.numero
        ).having(
            db.text('total_usuarios > 1')
        ).all()

        if not telefones:
            print("✅ Nenhum telefone duplicado encontrado!")
            return

        print(f"⚠️  Encontrados {len(telefones)} telefones em campanhas de múltiplos usuários:\n")

        for numero, total_consultas, total_usuarios in telefones:
            print(f"Telefone: {numero}")
            print(f"  - Total de consultas: {total_consultas}")
            print(f"  - Total de usuários diferentes: {total_usuarios}")

            # Buscar detalhes
            tels = TelefoneConsulta.query.filter_by(numero=numero).all()
            usuarios_campanhas = {}
            for tel in tels:
                if tel.consulta and tel.consulta.campanha:
                    usuario_id = tel.consulta.campanha.criador_id
                    campanha_id = tel.consulta.campanha_id
                    status = tel.consulta.status

                    if usuario_id not in usuarios_campanhas:
                        usuarios_campanhas[usuario_id] = []
                    usuarios_campanhas[usuario_id].append({
                        'campanha': campanha_id,
                        'consulta': tel.consulta_id,
                        'status': status
                    })

            for usuario_id, campanhas in usuarios_campanhas.items():
                print(f"  - Usuário {usuario_id}:")
                for camp in campanhas:
                    print(f"    * Campanha {camp['campanha']}, Consulta {camp['consulta']}, Status: {camp['status']}")
            print()

        print("\n⚠️  RECOMENDAÇÃO:")
        print("O mesmo telefone NÃO deveria estar em campanhas de usuários diferentes!")
        print("Isso causa respostas duplicadas no webhook.")
        print("\nSOLUÇÕES:")
        print("1. Deletar as campanhas antigas/duplicadas")
        print("2. Usar telefones diferentes para cada usuário")

if __name__ == '__main__':
    verificar_duplicados()
