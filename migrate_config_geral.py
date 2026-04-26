"""
Migração: cria a tabela config_usuario_geral usada pelo wizard do tipo
de usuário GERAL (Onda 1).

Execute uma única vez no servidor:
    python migrate_config_geral.py

Idempotente: pode rodar de novo sem efeitos colaterais.
"""

from app import app, db
from sqlalchemy import text


def main():
    with app.app_context():
        with db.engine.connect() as conn:
            try:
                conn.execute(text("""
                    CREATE TABLE IF NOT EXISTS config_usuario_geral (
                        id SERIAL PRIMARY KEY,
                        usuario_id INTEGER NOT NULL UNIQUE,
                        tipos_uso TEXT,
                        canal_resposta VARCHAR(40),
                        wizard_concluido BOOLEAN NOT NULL DEFAULT FALSE,
                        data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        data_atualizacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                    )
                """))
                conn.commit()
                print("[OK] Tabela config_usuario_geral pronta")
            except Exception as e:
                conn.rollback()
                print(f"[ERR] config_usuario_geral: {e}")
                raise


if __name__ == '__main__':
    main()
