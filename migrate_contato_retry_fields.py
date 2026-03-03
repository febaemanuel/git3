"""
Script de migração para adicionar campos de retry tracking na tabela contatos (fila cirúrgica).
Execute com: docker exec -it busca-ativa-web python migrate_contato_retry_fields.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração dos campos de retry da fila...")

            with db.engine.connect() as conn:
                # Verificar se as colunas já existem
                result = conn.execute(text("""
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_name='contatos'
                    AND column_name IN ('tentativas_contato', 'data_ultima_tentativa')
                """))

                existing_columns = [row[0] for row in result]

                # Adicionar tentativas_contato se não existir
                if 'tentativas_contato' not in existing_columns:
                    print("➕ Adicionando coluna 'tentativas_contato'...")
                    conn.execute(text(
                        "ALTER TABLE contatos ADD COLUMN tentativas_contato INTEGER DEFAULT 0"
                    ))
                    conn.commit()
                    print("   ✅ Coluna 'tentativas_contato' adicionada")
                else:
                    print("   ⏭️  Coluna 'tentativas_contato' já existe")

                # Adicionar data_ultima_tentativa se não existir
                if 'data_ultima_tentativa' not in existing_columns:
                    print("➕ Adicionando coluna 'data_ultima_tentativa'...")
                    conn.execute(text(
                        "ALTER TABLE contatos ADD COLUMN data_ultima_tentativa TIMESTAMP"
                    ))
                    conn.commit()
                    print("   ✅ Coluna 'data_ultima_tentativa' adicionada")
                else:
                    print("   ⏭️  Coluna 'data_ultima_tentativa' já existe")

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
