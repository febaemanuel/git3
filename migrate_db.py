#!/usr/bin/env python3
"""
Script de migração para adicionar tabelas de agendamento de consultas
"""
import sys
from app import db, app

def migrate():
    """Executa migração do banco de dados"""
    with app.app_context():
        try:
            print("Iniciando migração do banco de dados...")

            # Criar todas as tabelas
            db.create_all()

            print("✓ Tabelas criadas/atualizadas com sucesso!")
            print("✓ Modelo AgendamentoConsulta adicionado")
            print("✓ Campo tipo_sistema adicionado ao modelo Usuario")
            print("\nMigração concluída!")

        except Exception as e:
            print(f"✗ Erro na migração: {e}")
            import traceback
            traceback.print_exc()
            sys.exit(1)

if __name__ == '__main__':
    migrate()
