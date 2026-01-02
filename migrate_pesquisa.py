"""
Script de migração para adicionar pesquisa de satisfação
Execute: python migrate_pesquisa.py
"""

from app import app, db
from sqlalchemy import text

with app.app_context():
    # Criar tabela de pesquisas se não existir (PostgreSQL)
    try:
        with db.engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pesquisas_satisfacao (
                    id SERIAL PRIMARY KEY,
                    consulta_id INTEGER,
                    usuario_id INTEGER,
                    nota_satisfacao INTEGER,
                    equipe_atenciosa BOOLEAN,
                    comentario TEXT,
                    tipo_agendamento VARCHAR(50),
                    especialidade VARCHAR(100),
                    data_resposta TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    pulou BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (consulta_id) REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                )
            """))
            conn.commit()
        print("[OK] Tabela pesquisas_satisfacao criada/verificada")
    except Exception as e:
        if "already exists" in str(e).lower():
            print("[OK] Tabela pesquisas_satisfacao ja existe")
        else:
            print(f"Tabela pesquisas_satisfacao: {e}")

    # Adicionar coluna etapa_pesquisa se não existir
    try:
        with db.engine.connect() as conn:
            conn.execute(text("ALTER TABLE agendamentos_consultas ADD COLUMN etapa_pesquisa VARCHAR(30)"))
            conn.commit()
        print("[OK] Coluna etapa_pesquisa adicionada")
    except Exception as e:
        if "already exists" in str(e).lower() or "duplicate column" in str(e).lower():
            print("[OK] Coluna etapa_pesquisa ja existe")
        else:
            print(f"Coluna etapa_pesquisa: {e}")

    print("\nMigracao concluida!")
