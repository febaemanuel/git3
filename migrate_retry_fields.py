"""
Script de migração manual para adicionar campos de retry tracking
Execute com: docker exec -it busca-ativa-web python migrate_retry_fields.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração...")
            
            # Verificar se as colunas já existem
            result = db.engine.execute(text("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE table_name='agendamentos_consultas' 
                AND column_name IN ('tentativas_contato', 'data_ultima_tentativa', 'cancelado_sem_resposta')
            """))
            
            existing_columns = [row[0] for row in result]
            
            # Adicionar tentativas_contato se não existir
            if 'tentativas_contato' not in existing_columns:
                print("➕ Adicionando coluna 'tentativas_contato'...")
                db.engine.execute(text(
                    "ALTER TABLE agendamentos_consultas ADD COLUMN tentativas_contato INTEGER DEFAULT 0"
                ))
                print("   ✅ Coluna 'tentativas_contato' adicionada")
            else:
                print("   ⏭️  Coluna 'tentativas_contato' já existe")
            
            # Adicionar data_ultima_tentativa se não existir
            if 'data_ultima_tentativa' not in existing_columns:
                print("➕ Adicionando coluna 'data_ultima_tentativa'...")
                db.engine.execute(text(
                    "ALTER TABLE agendamentos_consultas ADD COLUMN data_ultima_tentativa TIMESTAMP"
                ))
                print("   ✅ Coluna 'data_ultima_tentativa' adicionada")
            else:
                print("   ⏭️  Coluna 'data_ultima_tentativa' já existe")
            
            # Adicionar cancelado_sem_resposta se não existir
            if 'cancelado_sem_resposta' not in existing_columns:
                print("➕ Adicionando coluna 'cancelado_sem_resposta'...")
                db.engine.execute(text(
                    "ALTER TABLE agendamentos_consultas ADD COLUMN cancelado_sem_resposta BOOLEAN DEFAULT FALSE"
                ))
                print("   ✅ Coluna 'cancelado_sem_resposta' adicionada")
            else:
                print("   ⏭️  Coluna 'cancelado_sem_resposta' já existe")
            
            print("\n✅ Migração concluída com sucesso!")
            print("\n📊 Próximos passos:")
            print("   1. Reiniciar Celery Beat: docker restart busca-ativa-beat")
            print("   2. Reiniciar Celery Worker: docker restart busca-ativa-worker")
            
        except Exception as e:
            print(f"\n❌ Erro na migração: {e}")
            raise

if __name__ == '__main__':
    migrate()
