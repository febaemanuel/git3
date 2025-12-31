#!/usr/bin/env python3
"""
Fix: Adiciona coluna celery_task_id faltante em campanhas_consultas

Uso:
    python3 fix_celery_task_id.py
"""

from sqlalchemy import text

def main():
    print("\n" + "="*70)
    print("FIX: Adicionando coluna celery_task_id em campanhas_consultas")
    print("="*70 + "\n")

    try:
        from app import app, db

        with app.app_context():
            # Verificar se a coluna já existe
            result = db.session.execute(text("""
                SELECT column_name
                FROM information_schema.columns
                WHERE table_name = 'campanhas_consultas' AND column_name = 'celery_task_id'
            """))
            exists = result.fetchone() is not None

            if exists:
                print("✓ Coluna celery_task_id já existe!")
                print("\nNenhuma ação necessária.")
                return

            print("⚠ Coluna celery_task_id NÃO existe. Adicionando...")

            # Adicionar coluna
            db.session.execute(text("""
                ALTER TABLE campanhas_consultas
                ADD COLUMN celery_task_id VARCHAR(100)
            """))
            db.session.commit()

            print("✓ Coluna celery_task_id adicionada com sucesso!\n")

            # Verificar
            result = db.session.execute(text("""
                SELECT column_name, data_type, character_maximum_length
                FROM information_schema.columns
                WHERE table_name = 'campanhas_consultas' AND column_name = 'celery_task_id'
            """))
            row = result.fetchone()
            if row:
                print(f"Verificação: {row[0]} ({row[1]}({row[2]}))")

            print("\n" + "="*70)
            print("✓ SUCESSO! O dashboard deve funcionar agora.")
            print("="*70)
            print("\nReinicie o container: docker restart busca-ativa-web")

    except Exception as e:
        print(f"\n✗ ERRO: {e}")
        import traceback
        traceback.print_exc()

if __name__ == '__main__':
    main()
