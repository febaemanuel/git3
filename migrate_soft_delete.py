#!/usr/bin/env python3
"""
Migração para adicionar campos de Soft Delete na tabela campanhas_consultas.
Executar: python migrate_soft_delete.py
"""

import os
import sys

# Adicionar diretório atual ao path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from sqlalchemy import text

def migrate():
    """Adiciona campos de soft delete na tabela campanhas_consultas"""

    with app.app_context():
        conn = db.engine.connect()

        # Verificar se os campos já existem
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'campanhas_consultas'
            AND column_name = 'excluida'
        """))

        if result.fetchone():
            print("✓ Campos de soft delete já existem!")
            conn.close()
            return

        print("Adicionando campos de soft delete...")

        try:
            # Adicionar campo excluida
            conn.execute(text("""
                ALTER TABLE campanhas_consultas
                ADD COLUMN IF NOT EXISTS excluida BOOLEAN DEFAULT FALSE
            """))
            print("  ✓ Campo 'excluida' adicionado")

            # Adicionar campo data_exclusao
            conn.execute(text("""
                ALTER TABLE campanhas_consultas
                ADD COLUMN IF NOT EXISTS data_exclusao TIMESTAMP
            """))
            print("  ✓ Campo 'data_exclusao' adicionado")

            # Adicionar campo excluido_por_id
            conn.execute(text("""
                ALTER TABLE campanhas_consultas
                ADD COLUMN IF NOT EXISTS excluido_por_id INTEGER REFERENCES usuarios(id)
            """))
            print("  ✓ Campo 'excluido_por_id' adicionado")

            conn.commit()
            print("\n✅ Migração concluída com sucesso!")

        except Exception as e:
            conn.rollback()
            print(f"\n❌ Erro na migração: {e}")
            raise
        finally:
            conn.close()

if __name__ == '__main__':
    migrate()
