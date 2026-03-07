"""
Script de migração para adicionar campos invalido e erro_envio à tabela telefones (fila cirúrgica).
Execute: python migrate_telefone_fila_invalido.py
"""

from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        try:
            conn.execute(text("""
                ALTER TABLE telefones
                ADD COLUMN IF NOT EXISTS invalido BOOLEAN DEFAULT FALSE
            """))
            conn.commit()
            print("[OK] Coluna 'invalido' adicionada em telefones")
        except Exception as e:
            print(f"[ERRO] invalido: {e}")

        try:
            conn.execute(text("""
                ALTER TABLE telefones
                ADD COLUMN IF NOT EXISTS erro_envio VARCHAR(200)
            """))
            conn.commit()
            print("[OK] Coluna 'erro_envio' adicionada em telefones")
        except Exception as e:
            print(f"[ERRO] erro_envio: {e}")

    print("\nMigração concluída. Reinicie web e worker.")
