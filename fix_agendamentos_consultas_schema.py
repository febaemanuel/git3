#!/usr/bin/env python3
"""
Fix Completo: Adiciona TODAS as colunas faltantes em agendamentos_consultas

Este script verifica e adiciona automaticamente todas as colunas necessárias
na tabela agendamentos_consultas conforme o modelo definido em app.py

Uso:
    python3 fix_agendamentos_consultas_schema.py
"""

from sqlalchemy import text

# Definir TODAS as colunas esperadas conforme app.py:814-865
COLUNAS_ESPERADAS = {
    # Dados da planilha
    'posicao': 'VARCHAR(50)',
    'cod_master': 'VARCHAR(50)',
    'codigo_aghu': 'VARCHAR(50)',
    'paciente': 'VARCHAR(200) NOT NULL',
    'telefone_cadastro': 'VARCHAR(20)',
    'telefone_registro': 'VARCHAR(20)',
    'data_registro': 'VARCHAR(50)',
    'procedencia': 'VARCHAR(200)',
    'medico_solicitante': 'VARCHAR(200)',
    'tipo': 'VARCHAR(50) NOT NULL',
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

    # Controle de status
    'status': "VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO'",
    'mensagem_enviada': 'BOOLEAN DEFAULT FALSE',
    'data_envio_mensagem': 'TIMESTAMP',

    # Comprovante
    'comprovante_path': 'VARCHAR(255)',
    'comprovante_nome': 'VARCHAR(255)',

    # Rejeição
    'motivo_rejeicao': 'TEXT',

    # Timestamps
    'created_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
    'updated_at': 'TIMESTAMP DEFAULT CURRENT_TIMESTAMP',
    'data_confirmacao': 'TIMESTAMP',
    'data_rejeicao': 'TIMESTAMP'
}


def main():
    print("\n" + "="*75)
    print("FIX COMPLETO: Schema de agendamentos_consultas")
    print("="*75 + "\n")

    try:
        from app import app, db

        with app.app_context():
            # 1. Verificar quais colunas existem
            print("[1/3] Verificando colunas existentes...\n")
            result = db.session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'agendamentos_consultas'
                ORDER BY ordinal_position
            """))

            colunas_existentes = {row[0] for row in result.fetchall()}
            print(f"   Colunas existentes: {len(colunas_existentes)}")

            # 2. Identificar colunas faltando
            print("\n[2/3] Identificando colunas faltantes...\n")
            colunas_faltando = []

            for coluna, tipo in COLUNAS_ESPERADAS.items():
                if coluna not in colunas_existentes:
                    colunas_faltando.append((coluna, tipo))
                    print(f"   ✗ FALTA: {coluna} ({tipo})")

            if not colunas_faltando:
                print("   ✓ Todas as colunas já existem!")
                print("\n" + "="*75)
                print("Nenhuma ação necessária.")
                print("="*75)
                return

            print(f"\n   Total de colunas faltando: {len(colunas_faltando)}")

            # 3. Adicionar colunas faltando
            print("\n[3/3] Adicionando colunas faltantes...\n")

            for coluna, tipo in colunas_faltando:
                try:
                    # Remover NOT NULL de colunas que já podem ter dados na tabela
                    tipo_safe = tipo.replace(' NOT NULL', '')

                    sql = f"ALTER TABLE agendamentos_consultas ADD COLUMN {coluna} {tipo_safe}"
                    db.session.execute(text(sql))
                    db.session.commit()
                    print(f"   ✓ Adicionada: {coluna}")
                except Exception as e:
                    if 'already exists' not in str(e).lower():
                        print(f"   ⚠ Erro ao adicionar {coluna}: {e}")
                        db.session.rollback()

            print("\n" + "="*75)
            print("✓ SCHEMA CORRIGIDO COM SUCESSO!")
            print("="*75)

            # Verificação final
            print("\nVerificação final:")
            result = db.session.execute(text("""
                SELECT COUNT(*) as total
                FROM information_schema.columns
                WHERE table_name = 'agendamentos_consultas'
            """))
            total = result.scalar()
            print(f"Total de colunas agora: {total}")

            print("\n" + "="*75)
            print("✓ Reinicie o container: docker restart busca-ativa-web")
            print("="*75)

    except Exception as e:
        print(f"\n✗ ERRO: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
