"""
Script de migração para aumentar tamanho dos campos de telefone
Execute com: docker exec -it busca-ativa-web python migrate_phone_fields.py
"""

from app import db, app
from sqlalchemy import text

def migrate():
    with app.app_context():
        try:
            print("🔄 Iniciando migração dos campos de telefone...")
            
            with db.engine.connect() as conn:
                # Aumentar tamanho do campo telefone_cadastro
                print("➕ Alterando 'telefone_cadastro' para VARCHAR(200)...")
                conn.execute(text(
                    "ALTER TABLE agendamentos_consultas ALTER COLUMN telefone_cadastro TYPE VARCHAR(200)"
                ))
                conn.commit()
                print("   ✅ Campo 'telefone_cadastro' alterado")
                
                # Aumentar tamanho do campo telefone_registro
                print("➕ Alterando 'telefone_registro' para VARCHAR(200)...")
                conn.execute(text(
                    "ALTER TABLE agendamentos_consultas ALTER COLUMN telefone_registro TYPE VARCHAR(200)"
                ))
                conn.commit()
                print("   ✅ Campo 'telefone_registro' alterado")
            
            print("\n✅ Migração concluída com sucesso!")
            print("\n📊 Agora você pode importar planilhas com múltiplos telefones!")
            
        except Exception as e:
            print(f"\n❌ Erro na migração: {e}")
            raise

if __name__ == '__main__':
    migrate()
