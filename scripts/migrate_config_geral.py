"""
Migração: cria as tabelas usadas pelo módulo GERAL (wizard + pesquisas).

Execute uma única vez no servidor a partir da raiz do repo:
    python scripts/migrate_config_geral.py

Idempotente (CREATE TABLE IF NOT EXISTS) — pode rodar de novo.
"""

import os
import sys

# Permite rodar a partir da raiz: garante que `app` é importável.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app, db
from sqlalchemy import text


TABELAS = [
    ("config_usuario_geral", """
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
    """),
    ("pesquisas", """
        CREATE TABLE IF NOT EXISTS pesquisas (
            id SERIAL PRIMARY KEY,
            usuario_id INTEGER NOT NULL,
            titulo VARCHAR(200) NOT NULL,
            descricao TEXT,
            mensagem_whatsapp TEXT,
            token_publico VARCHAR(40) NOT NULL UNIQUE,
            ativa BOOLEAN NOT NULL DEFAULT TRUE,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    """),
    ("pesquisas_idx_usuario", """
        CREATE INDEX IF NOT EXISTS ix_pesquisas_usuario_id ON pesquisas (usuario_id)
    """),
    ("perguntas_pesquisa", """
        CREATE TABLE IF NOT EXISTS perguntas_pesquisa (
            id SERIAL PRIMARY KEY,
            pesquisa_id INTEGER NOT NULL,
            ordem INTEGER NOT NULL DEFAULT 0,
            texto VARCHAR(500) NOT NULL,
            tipo VARCHAR(30) NOT NULL DEFAULT 'TEXTO_CURTO',
            opcoes TEXT,
            obrigatoria BOOLEAN NOT NULL DEFAULT TRUE,
            FOREIGN KEY (pesquisa_id) REFERENCES pesquisas(id) ON DELETE CASCADE
        )
    """),
    ("perguntas_idx_pesquisa", """
        CREATE INDEX IF NOT EXISTS ix_perguntas_pesquisa_id ON perguntas_pesquisa (pesquisa_id)
    """),
    ("respostas_pesquisa", """
        CREATE TABLE IF NOT EXISTS respostas_pesquisa (
            id SERIAL PRIMARY KEY,
            pesquisa_id INTEGER NOT NULL,
            iniciada_em TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            concluida_em TIMESTAMP,
            ip_origem VARCHAR(45),
            user_agent VARCHAR(255),
            FOREIGN KEY (pesquisa_id) REFERENCES pesquisas(id) ON DELETE CASCADE
        )
    """),
    ("respostas_idx_pesquisa", """
        CREATE INDEX IF NOT EXISTS ix_respostas_pesquisa_id ON respostas_pesquisa (pesquisa_id)
    """),
    ("respostas_itens", """
        CREATE TABLE IF NOT EXISTS respostas_itens (
            id SERIAL PRIMARY KEY,
            resposta_id INTEGER NOT NULL,
            pergunta_id INTEGER NOT NULL,
            valor TEXT,
            FOREIGN KEY (resposta_id) REFERENCES respostas_pesquisa(id) ON DELETE CASCADE,
            FOREIGN KEY (pergunta_id) REFERENCES perguntas_pesquisa(id) ON DELETE CASCADE
        )
    """),
    ("respostas_itens_idx_resposta", """
        CREATE INDEX IF NOT EXISTS ix_respostas_itens_resposta_id ON respostas_itens (resposta_id)
    """),
    ("respostas_itens_idx_pergunta", """
        CREATE INDEX IF NOT EXISTS ix_respostas_itens_pergunta_id ON respostas_itens (pergunta_id)
    """),
    ("envios_pesquisa", """
        CREATE TABLE IF NOT EXISTS envios_pesquisa (
            id SERIAL PRIMARY KEY,
            pesquisa_id INTEGER NOT NULL,
            usuario_id INTEGER NOT NULL,
            nome VARCHAR(120),
            mensagem_template TEXT NOT NULL,
            intervalo_segundos INTEGER NOT NULL DEFAULT 60,
            hora_inicio INTEGER NOT NULL DEFAULT 8,
            hora_fim INTEGER NOT NULL DEFAULT 18,
            meta_diaria INTEGER NOT NULL DEFAULT 50,
            enviados_hoje INTEGER NOT NULL DEFAULT 0,
            data_ultimo_envio DATE,
            status VARCHAR(20) NOT NULL DEFAULT 'pendente',
            status_msg VARCHAR(200),
            total INTEGER NOT NULL DEFAULT 0,
            enviados INTEGER NOT NULL DEFAULT 0,
            falhas INTEGER NOT NULL DEFAULT 0,
            data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            data_inicio TIMESTAMP,
            data_fim TIMESTAMP,
            celery_task_id VARCHAR(100),
            FOREIGN KEY (pesquisa_id) REFERENCES pesquisas(id) ON DELETE CASCADE,
            FOREIGN KEY (usuario_id) REFERENCES usuarios(id)
        )
    """),
    ("envios_pesquisa_idx", """
        CREATE INDEX IF NOT EXISTS ix_envios_pesquisa_pesquisa_id ON envios_pesquisa (pesquisa_id)
    """),
    ("envios_pesquisa_idx_user", """
        CREATE INDEX IF NOT EXISTS ix_envios_pesquisa_usuario_id ON envios_pesquisa (usuario_id)
    """),
    ("envios_pesquisa_telefones", """
        CREATE TABLE IF NOT EXISTS envios_pesquisa_telefones (
            id SERIAL PRIMARY KEY,
            envio_id INTEGER NOT NULL,
            numero VARCHAR(20) NOT NULL,
            nome VARCHAR(120),
            status VARCHAR(20) NOT NULL DEFAULT 'pendente',
            erro VARCHAR(300),
            data_envio TIMESTAMP,
            FOREIGN KEY (envio_id) REFERENCES envios_pesquisa(id) ON DELETE CASCADE
        )
    """),
    ("envios_pesquisa_telefones_idx", """
        CREATE INDEX IF NOT EXISTS ix_envios_pesquisa_telefones_envio_id ON envios_pesquisa_telefones (envio_id)
    """),
]


def main():
    with app.app_context():
        with db.engine.connect() as conn:
            for nome, sql in TABELAS:
                try:
                    conn.execute(text(sql))
                    conn.commit()
                    print(f"[OK] {nome}")
                except Exception as e:
                    conn.rollback()
                    print(f"[ERR] {nome}: {e}")
                    raise


if __name__ == '__main__':
    main()
