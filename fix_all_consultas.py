#!/usr/bin/env python3
"""
Fix ALL: Aplica TODOS os fixes necessários para o modo consulta

Este script executa automaticamente todos os fixes em sequência:
1. Adiciona celery_task_id em campanhas_consultas
2. Adiciona TODAS as colunas em agendamentos_consultas
3. Verifica status final

Uso:
    python3 fix_all_consultas.py
"""

from sqlalchemy import text
import sys

def print_header():
    print("\n" + "="*75)
    print("FIX ALL - Modo Consulta (Agendamento de Consultas)")
    print("="*75 + "\n")

def fix_celery_task_id(db):
    """Fix 1: Adiciona celery_task_id em campanhas_consultas"""
    print("[1/2] Verificando celery_task_id em campanhas_consultas...")

    result = db.session.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'celery_task_id'
    """))
    exists = result.fetchone() is not None

    if exists:
        print("   ✓ Coluna celery_task_id já existe\n")
        return True

    print("   ⚠ Coluna celery_task_id NÃO existe. Adicionando...")
    try:
        db.session.execute(text("""
            ALTER TABLE campanhas_consultas
            ADD COLUMN celery_task_id VARCHAR(100)
        """))
        db.session.commit()
        print("   ✓ Coluna celery_task_id adicionada!\n")
        return True
    except Exception as e:
        print(f"   ✗ Erro: {e}\n")
        db.session.rollback()
        return False

def fix_agendamentos_schema(db):
    """Fix 2: Adiciona todas as colunas em agendamentos_consultas"""
    print("[2/2] Verificando schema de agendamentos_consultas...")

    # Colunas esperadas
    COLUNAS = {
        'posicao': 'VARCHAR(50)',
        'cod_master': 'VARCHAR(50)',
        'codigo_aghu': 'VARCHAR(50)',
        'paciente': 'VARCHAR(200)',
        'telefone_cadastro': 'VARCHAR(20)',
        'telefone_registro': 'VARCHAR(20)',
        'data_registro': 'VARCHAR(50)',
        'procedencia': 'VARCHAR(200)',
        'medico_solicitante': 'VARCHAR(200)',
        'tipo': 'VARCHAR(50)',
        'observacoes': 'TEXT',
        'exames': 'TEXT',
        'sub_especialidade': 'VARCHAR(200)',
        'especialidade': 'VARCHAR(200)',
        'grade_aghu': 'VARCHAR(50)',
        'prioridade': 'VARCHAR(50)',
        'indicacao_data': 'VARCHAR(50)',
        'data_requisicao': 'VARCHAR(50)',
        'data_exata_ou_dias': 'VARCHAR(50)',
        'estimativa_agendamento': 'VARCHAR(50)',
        'data_aghu': 'VARCHAR(50)',
        'paciente_voltar_posto_sms': 'VARCHAR(10)',
        'status': "VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO'",
        'mensagem_enviada': 'BOOLEAN DEFAULT FALSE',
        'data_envio_mensagem': 'TIMESTAMP',
        'comprovante_path': 'VARCHAR(255)',
        'comprovante_nome': 'VARCHAR(255)',
        'motivo_rejeicao': 'TEXT',
        'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        'updated_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
        'data_confirmacao': 'TIMESTAMP',
        'data_rejeicao': 'TIMESTAMP'
    }

    # Verificar quais existem
    result = db.session.execute(text("""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = 'agendamentos_consultas'
    """))
    existentes = {row[0] for row in result.fetchall()}

    # Identificar faltantes
    faltantes = [(col, tipo) for col, tipo in COLUNAS.items() if col not in existentes]

    if not faltantes:
        print("   ✓ Todas as colunas já existem\n")
        return True

    print(f"   ⚠ Faltam {len(faltantes)} coluna(s). Adicionando...\n")

    # Adicionar colunas faltantes
    adicionadas = 0
    erros = 0

    for coluna, tipo in faltantes:
        try:
            tipo_safe = tipo.replace(' NOT NULL', '')
            sql = f"ALTER TABLE agendamentos_consultas ADD COLUMN {coluna} {tipo_safe}"
            db.session.execute(text(sql))
            db.session.commit()
            print(f"   ✓ {coluna}")
            adicionadas += 1
        except Exception as e:
            if 'already exists' not in str(e).lower():
                print(f"   ✗ {coluna}: {e}")
                erros += 1
                db.session.rollback()

    print(f"\n   Resumo: {adicionadas} adicionadas, {erros} erro(s)\n")
    return erros == 0

def main():
    print_header()

    try:
        from app import app, db

        with app.app_context():
            # Executar fixes
            fix1_ok = fix_celery_task_id(db)
            fix2_ok = fix_agendamentos_schema(db)

            # Resultado final
            print("="*75)
            if fix1_ok and fix2_ok:
                print("✓ TODOS OS FIXES APLICADOS COM SUCESSO!")
                print("="*75)
                print("\nPróximos passos:")
                print("  1. Reinicie o container: docker restart busca-ativa-web")
                print("  2. Acesse: https://chsistemas.cloud/consultas/dashboard")
                print("\n✓ Pronto! 🎉")
                return 0
            else:
                print("⚠ ALGUNS FIXES FALHARAM")
                print("="*75)
                print("\nVerifique os erros acima e tente novamente.")
                return 1

    except Exception as e:
        print(f"\n✗ ERRO CRÍTICO: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
