"""
Script de backfill: preenche hora_aghu via OCR APENAS nas consultas que ainda
podem usar esse dado em mensagens futuras (AGUARDANDO_ENVIO / AGUARDANDO_CONFIRMACAO).

NÃO processa consultas já em estado final (CONFIRMADO, REJEITADO, etc.) — fazer
OCR delas seria desperdício porque elas não vão mais disparar mensagem nenhuma.

Uso:
    docker compose exec -T celery_worker python /app/backfill_hora_aghu.py
    docker compose exec -T celery_worker python /app/backfill_hora_aghu.py --all      # processa tudo (cuidado!)
    docker compose exec -T celery_worker python /app/backfill_hora_aghu.py --limit 50 # processa só 50
    docker compose exec -T celery_worker python /app/backfill_hora_aghu.py --sleep 2  # 2s entre cada OCR

Throttling: por padrão dorme 500ms entre cada OCR pra não estourar CPU.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, '/app')

from app import (
    app, db,
    AgendamentoConsulta, ComprovanteAntecipado,
    extrair_dados_comprovante,
)

# Só processa consultas que AINDA NÃO RECEBERAM a MSG1 — essas são as únicas
# que vão se beneficiar do hora_aghu (porque a MSG1 não foi enviada ainda).
# Consultas que já receberam a mensagem não adianta preencher hora_aghu agora,
# o paciente já recebeu a mensagem sem horário.
STATUS_ATIVOS = ('AGUARDANDO_ENVIO',)


def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--all', action='store_true', help='Processa TODAS as consultas, mesmo as já finalizadas')
    p.add_argument('--limit', type=int, default=0, help='Limita ao número N de consultas')
    p.add_argument('--sleep', type=float, default=0.5, help='Segundos entre cada OCR (default 0.5)')
    return p.parse_args()


def main():
    args = parse_args()

    with app.app_context():
        atualizadas = 0
        sem_hora_no_pdf = 0
        erros_ocr = 0
        ja_tinha = 0
        sem_arquivo = 0

        # 1) Consultas em status ativo com comprovante já vinculado
        q = AgendamentoConsulta.query.filter(
            AgendamentoConsulta.comprovante_path.isnot(None),
            AgendamentoConsulta.comprovante_path != '',
        )
        if not args.all:
            q = q.filter(AgendamentoConsulta.status.in_(STATUS_ATIVOS))
        if args.limit > 0:
            q = q.limit(args.limit)
        consultas = q.all()
        modo = 'TODAS' if args.all else 'ativas'
        print(f"[1/2] Consultas {modo} com comprovante vinculado: {len(consultas)}")
        print(f"      (throttling: {args.sleep}s entre cada OCR)")

        for i, ag in enumerate(consultas):
            if (ag.hora_aghu or '').strip() and (ag.hora_aghu or '').strip() != '00:00':
                ja_tinha += 1
                continue
            if not os.path.exists(ag.comprovante_path):
                sem_arquivo += 1
                continue
            try:
                dados = extrair_dados_comprovante(ag.comprovante_path) or {}
                hora = (dados.get('hora') or '').strip()
                if hora and hora != '00:00':
                    ag.hora_aghu = hora
                    atualizadas += 1
                else:
                    sem_hora_no_pdf += 1
            except Exception as e:
                erros_ocr += 1
                print(f"  ! erro OCR consulta {ag.id}: {str(e)[:80]}")

            # Commit a cada 50 + throttle
            if (i + 1) % 50 == 0:
                db.session.commit()
                print(f"  ... {i+1}/{len(consultas)} processadas ({atualizadas} preenchidas)")
            if args.sleep > 0:
                time.sleep(args.sleep)
        db.session.commit()

        # 2) ComprovanteAntecipado de campanhas ainda ativas
        q2 = ComprovanteAntecipado.query.filter(
            ComprovanteAntecipado.consulta_id.isnot(None),
            ComprovanteAntecipado.usado == False,  # ainda não foi usado = campanha em andamento
        )
        if args.limit > 0:
            q2 = q2.limit(max(args.limit - atualizadas, 0))
        antecipados = q2.all()
        print(f"[2/2] Comprovantes antecipados ainda não usados: {len(antecipados)}")

        for i, comp in enumerate(antecipados):
            ag = db.session.get(AgendamentoConsulta, comp.consulta_id)
            if not ag:
                continue
            if (ag.hora_aghu or '').strip() and (ag.hora_aghu or '').strip() != '00:00':
                ja_tinha += 1
                continue
            if not comp.filepath or not os.path.exists(comp.filepath):
                sem_arquivo += 1
                continue
            try:
                dados = extrair_dados_comprovante(comp.filepath) or {}
                hora = (dados.get('hora') or '').strip()
                if hora and hora != '00:00':
                    ag.hora_aghu = hora
                    atualizadas += 1
                else:
                    sem_hora_no_pdf += 1
            except Exception as e:
                erros_ocr += 1
                print(f"  ! erro OCR antecipado {comp.id}: {str(e)[:80]}")

            if (i + 1) % 50 == 0:
                db.session.commit()
                print(f"  ... {i+1}/{len(antecipados)} processadas")
            if args.sleep > 0:
                time.sleep(args.sleep)
        db.session.commit()

        print("")
        print("=" * 60)
        print(f"BACKFILL CONCLUÍDO")
        print(f"  hora_aghu preenchido:        {atualizadas}")
        print(f"  já tinham horário:           {ja_tinha}")
        print(f"  PDF sem horário extraível:   {sem_hora_no_pdf}")
        print(f"  PDF não encontrado em disco: {sem_arquivo}")
        print(f"  erros de OCR:                {erros_ocr}")
        print("=" * 60)


if __name__ == '__main__':
    main()
