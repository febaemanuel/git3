"""
Script de backfill: percorre comprovantes existentes (ComprovanteAntecipado E
AgendamentoConsulta.comprovante_path) e roda OCR pra preencher hora_aghu nas
consultas que ainda não têm horário.

Uso (dentro do container celery_worker ou web):
    docker compose exec -T celery_worker python /app/backfill_hora_aghu.py
"""
import os
import sys

sys.path.insert(0, '/app')

from app import (
    app, db,
    AgendamentoConsulta, ComprovanteAntecipado,
    extrair_dados_comprovante, normalizar_nome_paciente,
)


def main():
    with app.app_context():
        atualizadas = 0
        sem_hora_no_pdf = 0
        erros_ocr = 0
        ja_tinha = 0

        # 1) Consultas com comprovante já vinculado (path != NULL) — OCR direto no PDF
        consultas = AgendamentoConsulta.query.filter(
            AgendamentoConsulta.comprovante_path.isnot(None),
            AgendamentoConsulta.comprovante_path != '',
        ).all()
        print(f"[1/2] Consultas com comprovante vinculado: {len(consultas)}")
        for ag in consultas:
            if (ag.hora_aghu or '').strip() and (ag.hora_aghu or '').strip() != '00:00':
                ja_tinha += 1
                continue
            try:
                if not os.path.exists(ag.comprovante_path):
                    continue
                dados = extrair_dados_comprovante(ag.comprovante_path) or {}
                hora = (dados.get('hora') or '').strip()
                if hora and hora != '00:00':
                    ag.hora_aghu = hora
                    atualizadas += 1
                    if atualizadas % 100 == 0:
                        db.session.commit()
                        print(f"  ... {atualizadas} atualizadas até agora")
                else:
                    sem_hora_no_pdf += 1
            except Exception as e:
                erros_ocr += 1
                print(f"  ! erro OCR consulta {ag.id}: {e}")
        db.session.commit()

        # 2) ComprovanteAntecipado vinculados a consulta — só processa as ainda sem hora_aghu
        antecipados = ComprovanteAntecipado.query.filter(
            ComprovanteAntecipado.consulta_id.isnot(None)
        ).all()
        print(f"[2/2] Comprovantes antecipados vinculados: {len(antecipados)}")
        for comp in antecipados:
            ag = db.session.get(AgendamentoConsulta, comp.consulta_id)
            if not ag:
                continue
            if (ag.hora_aghu or '').strip() and (ag.hora_aghu or '').strip() != '00:00':
                ja_tinha += 1
                continue
            try:
                if not comp.filepath or not os.path.exists(comp.filepath):
                    continue
                dados = extrair_dados_comprovante(comp.filepath) or {}
                hora = (dados.get('hora') or '').strip()
                if hora and hora != '00:00':
                    ag.hora_aghu = hora
                    atualizadas += 1
                else:
                    sem_hora_no_pdf += 1
            except Exception as e:
                erros_ocr += 1
                print(f"  ! erro OCR antecipado {comp.id}: {e}")
        db.session.commit()

        print("")
        print("=" * 60)
        print(f"BACKFILL CONCLUÍDO")
        print(f"  hora_aghu preenchido:        {atualizadas}")
        print(f"  já tinham horário:           {ja_tinha}")
        print(f"  PDF sem horário extraível:   {sem_hora_no_pdf}")
        print(f"  erros de OCR:                {erros_ocr}")
        print("=" * 60)


if __name__ == '__main__':
    main()
