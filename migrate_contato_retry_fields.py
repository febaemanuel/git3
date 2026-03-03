"""
Script de migração para adicionar campos de retry tracking e novos campos na fila cirúrgica.
Execute com: docker exec -it busca-ativa-web python migrate_contato_retry_fields.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração dos campos da fila cirúrgica...")

            with db.engine.connect() as conn:

                # ── TABELA contatos ──────────────────────────────────────────
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='contatos'
                    AND column_name IN (
                        'tentativas_contato', 'data_ultima_tentativa',
                        'motivo_rejeicao', 'data_rejeicao'
                    )
                """))
                existing_contatos = [row[0] for row in result]

                campos_contatos = [
                    ('tentativas_contato',   'INTEGER DEFAULT 0'),
                    ('data_ultima_tentativa', 'TIMESTAMP'),
                    ('motivo_rejeicao',       'TEXT'),
                    ('data_rejeicao',         'TIMESTAMP'),
                ]
                for col, tipo in campos_contatos:
                    if col not in existing_contatos:
                        print(f"➕ contatos: adicionando '{col}'...")
                        conn.execute(text(f"ALTER TABLE contatos ADD COLUMN {col} {tipo}"))
                        conn.commit()
                        print(f"   ✅ '{col}' adicionada")
                    else:
                        print(f"   ⏭️  contatos.{col} já existe")

                # ── TABELA telefones ─────────────────────────────────────────
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='telefones'
                    AND column_name IN ('nao_pertence')
                """))
                existing_telefones = [row[0] for row in result]

                if 'nao_pertence' not in existing_telefones:
                    print("➕ telefones: adicionando 'nao_pertence'...")
                    conn.execute(text(
                        "ALTER TABLE telefones ADD COLUMN nao_pertence BOOLEAN DEFAULT FALSE"
                    ))
                    conn.commit()
                    print("   ✅ 'nao_pertence' adicionada")
                else:
                    print("   ⏭️  telefones.nao_pertence já existe")

            print("\n✅ Migração concluída com sucesso!")
            print("\n📊 Próximos passos:")
            print("   1. Reiniciar a aplicação web: docker restart busca-ativa-web")
            print("   2. Reiniciar Celery Beat: docker restart busca-ativa-beat")
            print("   3. Reiniciar Celery Worker: docker restart busca-ativa-worker")

        except Exception as e:
            print(f"\n❌ Erro na migração: {e}")
            raise

if __name__ == '__main__':
    migrate()
