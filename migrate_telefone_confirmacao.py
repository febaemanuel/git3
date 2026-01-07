"""
Script de migração para adicionar campo telefone_confirmacao
Execute com: docker exec -it busca-ativa-web python migrate_telefone_confirmacao.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração do campo telefone_confirmacao...")
            
            with db.engine.connect() as conn:
                # Verificar se campo já existe
                result = conn.execute(text("""
                    SELECT column_name 
                    FROM information_schema.columns 
                    WHERE table_name = 'agendamentos_consultas' 
                    AND column_name = 'telefone_confirmacao'
                """))
                
                if result.fetchone():
                    print("⏭️  Campo 'telefone_confirmacao' já existe, pulando...")
                else:
                    print("➕ Adicionando campo 'telefone_confirmacao'...")
                    conn.execute(text(
                        "ALTER TABLE agendamentos_consultas ADD COLUMN telefone_confirmacao VARCHAR(20)"
                    ))
                    conn.commit()
                    print("   ✅ Campo 'telefone_confirmacao' adicionado")
            
            print("\n✅ Migração concluída com sucesso!")
            print("\n📊 O que foi corrigido:")
            print("   - Comprovante agora será enviado para o telefone que CONFIRMOU")
            print("   - Não mais para o primeiro telefone da lista")
            
        except Exception as e:
            print(f"\n❌ Erro na migração: {e}")
            raise

if __name__ == '__main__':
    migrate()
