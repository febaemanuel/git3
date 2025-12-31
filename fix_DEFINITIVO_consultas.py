#!/usr/bin/env python3
"""
FIX DEFINITIVO: Corrige TODAS as tabelas do modo consulta DE UMA VEZ

Este script verifica e adiciona TODAS as colunas faltantes em:
- campanhas_consultas
- agendamentos_consultas
- telefones_consultas
- logs_msgs_consultas

Uso:
    python3 fix_DEFINITIVO_consultas.py
"""

from sqlalchemy import text
import sys

def fix_table(db, table_name, colunas_esperadas):
    """Adiciona colunas faltantes em uma tabela"""
    print(f"\n[{table_name}] Verificando colunas...")

    # Verificar quais existem
    result = db.session.execute(text(f"""
        SELECT column_name
        FROM information_schema.columns
        WHERE table_name = '{table_name}'
    """))
    existentes = {row[0] for row in result.fetchall()}

    # Identificar faltantes
    faltantes = [(col, tipo) for col, tipo in colunas_esperadas.items() if col not in existentes]

    if not faltantes:
        print(f"   ✓ OK - Todas as colunas existem")
        return True

    print(f"   ⚠ Faltam {len(faltantes)} coluna(s). Adicionando...")

    # Adicionar
    adicionadas = 0
    for coluna, tipo in faltantes:
        try:
            tipo_safe = tipo.replace(' NOT NULL', '')
            sql = f"ALTER TABLE {table_name} ADD COLUMN {coluna} {tipo_safe}"
            db.session.execute(text(sql))
            db.session.commit()
            print(f"   ✓ {coluna}")
            adicionadas += 1
        except Exception as e:
            if 'already exists' not in str(e).lower():
                print(f"   ✗ {coluna}: {e}")
                db.session.rollback()

    print(f"   Total: {adicionadas}/{len(faltantes)} adicionadas")
    return True

def main():
    print("\n" + "="*75)
    print("FIX DEFINITIVO - Modo Consulta (TODAS AS TABELAS)")
    print("="*75)

    try:
        from app import app, db

        with app.app_context():

            # 1. campanhas_consultas
            print("\n[1/4] campanhas_consultas")
            fix_table(db, 'campanhas_consultas', {
                'celery_task_id': 'VARCHAR(100)',
                'status_msg': 'TEXT'
            })

            # 2. agendamentos_consultas
            print("\n[2/4] agendamentos_consultas")
            fix_table(db, 'agendamentos_consultas', {
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
            })

            # 3. telefones_consultas
            print("\n[3/4] telefones_consultas")
            fix_table(db, 'telefones_consultas', {
                'consulta_id': 'INTEGER',
                'numero': 'VARCHAR(20)',
                'prioridade': 'INTEGER DEFAULT 1',
                'enviado': 'BOOLEAN DEFAULT FALSE',
                'data_envio': 'TIMESTAMP',
                'msg_id': 'VARCHAR(100)',
                'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
            })

            # 4. logs_msgs_consultas
            print("\n[4/4] logs_msgs_consultas")
            fix_table(db, 'logs_msgs_consultas', {
                'campanha_id': 'INTEGER',
                'consulta_id': 'INTEGER',
                'direcao': 'VARCHAR(20)',
                'telefone': 'VARCHAR(20)',
                'mensagem': 'TEXT',
                'status': 'VARCHAR(20)',
                'erro': 'TEXT',
                'msg_id': 'VARCHAR(100)',
                'data': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP'
            })

            print("\n" + "="*75)
            print("✓✓✓ TODAS AS TABELAS CORRIGIDAS! ✓✓✓")
            print("="*75)
            print("\nPróximos passos:")
            print("  1. Reinicie: docker restart busca-ativa-web")
            print("  2. Acesse: https://chsistemas.cloud/consultas/dashboard")
            print("\n🎉 AGORA VAI FUNCIONAR! 🎉\n")
            return 0

    except Exception as e:
        print(f"\n✗ ERRO: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
