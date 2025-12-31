#!/usr/bin/env python3
"""
=====================================================
MIGRAÇÃO: Modo Consulta - Verificação e Aplicação
=====================================================

Script Python para verificar e aplicar automaticamente
as migrations do modo consulta no banco de dados.

Uso:
    python migrate_modo_consulta.py --check     # Apenas verifica
    python migrate_modo_consulta.py --apply     # Aplica as migrations

IMPORTANTE: Execute este script no servidor de produção
se estiver recebendo erro ao acessar /consultas/dashboard
"""

import sys
import os
from sqlalchemy import inspect, text

def print_header():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║       MIGRAÇÃO: MODO CONSULTA - Agendamento de Consultas      ║
╚═══════════════════════════════════════════════════════════════╝
    """)

def check_tables(engine):
    """Verifica quais tabelas do modo consulta existem"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    required_tables = [
        'campanhas_consultas',
        'agendamentos_consultas',
        'telefones_consultas',
        'logs_msgs_consultas'
    ]

    print("\n[1/2] Verificando tabelas do modo consulta...\n")

    missing = []
    for table in required_tables:
        exists = table in existing_tables
        status = "✓ OK" if exists else "✗ FALTA"
        print(f"   {status}: {table}")
        if not exists:
            missing.append(table)

    return missing

def check_column_tipo_sistema(engine):
    """Verifica se a coluna tipo_sistema existe na tabela usuarios"""
    print("\n[2/2] Verificando campo tipo_sistema em usuarios...\n")

    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT column_name
            FROM information_schema.columns
            WHERE table_name = 'usuarios' AND column_name = 'tipo_sistema'
        """))
        exists = result.fetchone() is not None

        if exists:
            print("   ✓ OK: Campo tipo_sistema existe")

            # Verificar valores
            result = conn.execute(text("""
                SELECT tipo_sistema, COUNT(*) as total
                FROM usuarios
                GROUP BY tipo_sistema
            """))
            print("\n   Distribuição de usuários:")
            for row in result:
                tipo = row[0] if row[0] else 'NULL'
                total = row[1]
                print(f"   - {tipo}: {total} usuário(s)")
        else:
            print("   ✗ FALTA: Campo tipo_sistema não existe")
            return False

    return exists

def apply_migrations(engine):
    """Aplica as migrations do modo consulta"""
    print("\n" + "="*65)
    print("APLICANDO MIGRATIONS")
    print("="*65 + "\n")

    # Ler o arquivo SQL
    sql_file = 'migration_modo_consulta.sql'
    if not os.path.exists(sql_file):
        print(f"✗ ERRO: Arquivo {sql_file} não encontrado!")
        return False

    print(f"Lendo {sql_file}...")
    with open(sql_file, 'r', encoding='utf-8') as f:
        sql_content = f.read()

    # Executar as migrations
    print("Executando migrations...\n")
    try:
        with engine.begin() as conn:
            # Dividir por statement (simplificado - assume que ; separa statements)
            # Para produção real, use um parser SQL adequado
            for statement in sql_content.split(';'):
                statement = statement.strip()
                if statement and not statement.startswith('--') and not statement.startswith('/*'):
                    # Pular comentários e queries de verificação (SELECT)
                    if statement.upper().startswith('SELECT') or statement.upper().startswith('COMMENT'):
                        continue
                    try:
                        conn.execute(text(statement))
                    except Exception as e:
                        # Ignorar erros de "already exists"
                        if 'already exists' not in str(e).lower():
                            print(f"   ⚠ Aviso: {e}")

        print("✓ Migrations aplicadas com sucesso!\n")

        # Aplicar migration_modo_consulta_fix.sql se existir
        fix_file = 'migration_modo_consulta_fix.sql'
        if os.path.exists(fix_file):
            print(f"Aplicando correções ({fix_file})...")
            with open(fix_file, 'r', encoding='utf-8') as f:
                fix_content = f.read()

            with engine.begin() as conn:
                for statement in fix_content.split(';'):
                    statement = statement.strip()
                    if statement and not statement.startswith('--') and not statement.upper().startswith('SELECT'):
                        try:
                            conn.execute(text(statement))
                        except Exception as e:
                            if 'already exists' not in str(e).lower():
                                print(f"   ⚠ Aviso: {e}")

            print("✓ Correções aplicadas com sucesso!\n")

        return True

    except Exception as e:
        print(f"✗ ERRO ao aplicar migrations: {e}")
        return False

def main():
    args = sys.argv[1:]

    if not args or '--help' in args or '-h' in args:
        print_header()
        print(__doc__)
        return

    print_header()

    # Carregar ambiente
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    # Conectar ao banco
    print("Conectando ao banco de dados...\n")
    try:
        from app import app, db

        with app.app_context():
            engine = db.engine

            if '--check' in args:
                # Apenas verificar
                missing = check_tables(engine)
                has_tipo_sistema = check_column_tipo_sistema(engine)

                print("\n" + "="*65)
                if missing or not has_tipo_sistema:
                    print("RESULTADO: Migrations PENDENTES")
                    print("="*65)
                    print("\nExecute com --apply para aplicar as migrations:")
                    print("  python migrate_modo_consulta.py --apply")
                else:
                    print("RESULTADO: Banco de dados ATUALIZADO")
                    print("="*65)
                    print("\nTodas as tabelas do modo consulta existem!")

            elif '--apply' in args:
                # Verificar primeiro
                missing = check_tables(engine)
                has_tipo_sistema = check_column_tipo_sistema(engine)

                if not missing and has_tipo_sistema:
                    print("\n✓ Banco já está atualizado! Nenhuma ação necessária.")
                    return

                # Confirmar
                print("\n" + "="*65)
                print("⚠ ATENÇÃO: Você vai aplicar migrations no banco de dados!")
                print("="*65)
                response = input("\nDeseja continuar? [s/N]: ").strip().lower()

                if response in ['s', 'sim', 'y', 'yes']:
                    if apply_migrations(engine):
                        print("\n" + "="*65)
                        print("✓ SUCESSO! Migrations aplicadas com sucesso!")
                        print("="*65)
                        print("\nO sistema de consultas agora está disponível em:")
                        print("  https://seu-dominio.com/consultas/dashboard")
                    else:
                        print("\n✗ Falha ao aplicar migrations. Verifique os erros acima.")
                        sys.exit(1)
                else:
                    print("\nOperação cancelada.")

            else:
                print("Uso: python migrate_modo_consulta.py [--check | --apply]")

    except Exception as e:
        print(f"\n✗ ERRO: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    main()
