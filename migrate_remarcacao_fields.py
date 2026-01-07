"""
Script de migração para adicionar campos de remarcação
Execute com: docker exec -it busca-ativa-web python migrate_remarcacao_fields.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração dos campos de remarcação...")
            
            with db.engine.connect() as conn:
                # Verificar se campo motivo_remarcacao já existe
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'agendamentos_consultas' 
                    AND column_name = 'motivo_remarcacao'
                """))
                
                if result.fetchone():
                    print("⏭️  Campo 'motivo_remarcacao' já existe, pulando...")
                else:
                    print("➕ Adicionando campo 'motivo_remarcacao'...")
                    conn.execute(text(
                        "ALTER TABLE agendamentos_consultas ADD COLUMN motivo_remarcacao VARCHAR(200)"
                    ))
                    conn.commit()
                    print("   ✅ Campo 'motivo_remarcacao' adicionado")
                
                # Verificar se campo data_anterior já existe
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'agendamentos_consultas' 
                    AND column_name = 'data_anterior'
                """))
                
                if result.fetchone():
                    print("⏭️  Campo 'data_anterior' já existe, pulando...")
                else:
                    print("➕ Adicionando campo 'data_anterior'...")
                    conn.execute(text(
                        "ALTER TABLE agendamentos_consultas ADD COLUMN data_anterior VARCHAR(50)"
                    ))
                    conn.commit()
                    print("   ✅ Campo 'data_anterior' adicionado")
            
            print("\n✅ Migração concluída com sucesso!")
            print("\n📊 Agora o sistema suporta:")
            print("   - TIPO: RETORNO (consultas de retorno)")
            print("   - TIPO: INTERCONSULTA (interconsultas)")
            print("   - TIPO: REMARCACAO (consultas remarcadas)")
            
        except Exception as e:
            print(f"\n❌ Erro na migração: {e}")
            raise

if __name__ == '__main__':
    migrate()
