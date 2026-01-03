"""
Script de migração para adicionar pesquisa de satisfação + histórico + reagendamento
Execute: python migrate_pesquisa.py
"""

from app import app, db
from sqlalchemy import text

with app.app_context():
    with db.engine.connect() as conn:
        # 1. Tabela PESQUISAS_SATISFACAO
        try:
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
            print("[OK] Tabela pesquisas_satisfacao")
        except Exception as e:
            print(f"[ERR] Tabela pesquisas_satisfacao: {e}")

        # 2. Tabela PACIENTES
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS pacientes (
                    id SERIAL PRIMARY KEY,
                    usuario_id INTEGER,
                    nome VARCHAR(200) NOT NULL,
                    data_nascimento VARCHAR(20),
                    prontuario VARCHAR(50),
                    codigo VARCHAR(50),
                    telefone VARCHAR(20),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                )
            """))
            conn.commit()
            print("[OK] Tabela pacientes")
        except Exception as e:
            conn.rollback()
            print(f"[ERR] Tabela pacientes: {e}")

        # 3. Tabela HISTORICO_CONSULTAS
        try:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS historico_consultas (
                    id SERIAL PRIMARY KEY,
                    paciente_id INTEGER,
                    consulta_id INTEGER,
                    usuario_id INTEGER,
                    nro_consulta VARCHAR(50),
                    data_consulta VARCHAR(20),
                    hora_consulta VARCHAR(10),
                    dia_semana VARCHAR(10),
                    grade VARCHAR(50),
                    unidade_funcional VARCHAR(200),
                    andar VARCHAR(10),
                    ala_bloco VARCHAR(50),
                    setor VARCHAR(50),
                    sala VARCHAR(10),
                    tipo_consulta VARCHAR(100),
                    tipo_demanda VARCHAR(100),
                    equipe VARCHAR(100),
                    profissional VARCHAR(200),
                    especialidade VARCHAR(100),
                    marcado_por VARCHAR(100),
                    observacao TEXT,
                    nro_autorizacao VARCHAR(50),
                    status VARCHAR(50) DEFAULT 'CONFIRMADA',
                    comprovante_path VARCHAR(255),
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (paciente_id) REFERENCES pacientes(id) ON DELETE CASCADE,
                    FOREIGN KEY (consulta_id) REFERENCES agendamentos_consultas(id) ON DELETE SET NULL,
                    FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
                )
            """))
            conn.commit()
            print("[OK] Tabela historico_consultas")
        except Exception as e:
            conn.rollback()
            print(f"[ERR] Tabela historico_consultas: {e}")

        # 4. Colunas na tabela AGENDAMENTOS_CONSULTAS
        colunas = [
            ("etapa_pesquisa", "VARCHAR(30)"),
            ("data_reagendamento", "TIMESTAMP"),
            ("nova_data", "VARCHAR(50)"),
            ("nova_hora", "VARCHAR(20)")
        ]
        
        for col_nome, col_tipo in colunas:
            try:
                conn.execute(text(f"ALTER TABLE agendamentos_consultas ADD COLUMN {col_nome} {col_tipo}"))
                conn.commit()
                print(f"[OK] Coluna {col_nome}")
            except Exception as e:
                conn.rollback()
                if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                    print(f"[OK] Coluna {col_nome} ja existe")
                else:
                    print(f"[ERR] Coluna {col_nome}: {e}")

        # 5. Coluna nao_pertence em telefones_consultas (para opção 3 - DESCONHEÇO)
        try:
            conn.execute(text("ALTER TABLE telefones_consultas ADD COLUMN nao_pertence BOOLEAN DEFAULT FALSE"))
            conn.commit()
            print("[OK] Coluna nao_pertence em telefones_consultas")
        except Exception as e:
            conn.rollback()
            if "duplicate" in str(e).lower() or "exists" in str(e).lower():
                print("[OK] Coluna nao_pertence ja existe")
            else:
                print(f"[ERR] Coluna nao_pertence: {e}")

    print("\nMigracao concluida!")
