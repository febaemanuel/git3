"""Excel spreadsheet ingestion for fila campanhas."""

import logging
import re
from datetime import datetime, date

import pandas as pd

from app.ai import DeepSeekAI
from app.extensions import db
from app.models import Campanha, Contato, ProcedimentoNormalizado, Telefone
from app.services.telefone import formatar_numero


logger = logging.getLogger(__name__)


def processar_planilha(arquivo, campanha_id):
    try:
        df = pd.read_excel(arquivo)
        if df.empty:
            return False, "Planilha vazia", 0

        df.columns = [str(c).strip().lower() for c in df.columns]

        # Normalizar colunas: substituir múltiplos espaços por um único
        import re
        df.columns = [re.sub(r'\s+', ' ', c) for c in df.columns]

        col_nome = col_tel = col_proc = col_nasc = None
        for c in df.columns:
            if c in ['nome', 'usuario', 'usuário', 'paciente']:
                col_nome = c
            elif c in ['telefone', 'celular', 'fone', 'tel', 'whatsapp', 'contato']:
                col_tel = c
            elif c in ['procedimento', 'cirurgia', 'procedimentos']:
                col_proc = c
            elif c in ['nascimento', 'data_nascimento', 'data nascimento', 'dt_nasc', 'dtnasc', 'dt nasc']:
                col_nasc = c

        if not col_nome or not col_tel:
            return False, f"Colunas obrigatorias nao encontradas. Disponiveis: {list(df.columns)}", 0

        criados = 0

        # Agrupar por Nome e Data de Nascimento (se houver) para unificar contatos
        pessoas = {} # chave: (nome, data_nascimento_str) -> {telefones: set(), proc: str, data_nasc_obj: date}

        for _, row in df.iterrows():
            nome = str(row.get(col_nome, '')).strip()
            if not nome or nome.lower() == 'nan':
                continue

            # Tratamento Data Nascimento
            dt_nasc = None
            dt_nasc_str = ''
            if col_nasc:
                val = row.get(col_nasc)
                if pd.notna(val):
                    try:
                        if isinstance(val, datetime):
                            # Já é datetime do Excel
                            dt_nasc = val.date()
                        else:
                            # Converter para string e limpar
                            val_str = str(val).strip()

                            # Extrair apenas a parte da data com regex (DD/MM/YYYY ou DD-MM-YYYY ou DD.MM.YYYY)
                            import re
                            match = re.search(r'(\d{1,2})[/\-\.](\d{1,2})[/\-\.](\d{4})', val_str)
                            if match:
                                dia, mes, ano = match.groups()
                                # Criar data manualmente para garantir formato correto
                                dt_nasc = datetime(int(ano), int(mes), int(dia)).date()
                            else:
                                # Fallback: tentar parsear com pandas
                                dt_nasc = pd.to_datetime(val_str, dayfirst=True).date()

                        dt_nasc_str = dt_nasc.isoformat()
                        logger.info(f"Data importada: {val} -> {dt_nasc}")
                    except Exception as e:
                        logger.warning(f"Erro ao parsear data '{val}': {e}")
                        pass

            chave = (nome, dt_nasc_str)

            if chave not in pessoas:
                # Procedimento
                proc = str(row.get(col_proc, 'o procedimento')).strip() if col_proc else 'o procedimento'
                if proc.lower() == 'nan': proc = 'o procedimento'
                if '-' in proc:
                    partes = proc.split('-', 1)
                    if partes[0].strip().isdigit():
                        proc = partes[1].strip()

                pessoas[chave] = {
                    'nome': nome,
                    'nascimento': dt_nasc,
                    'procedimento': proc,
                    'telefones': set()
                }

            # Telefones
            tels = str(row.get(col_tel, '')).strip()
            if tels and tels.lower() != 'nan':
                for tel in tels.replace(',', ' ').replace(';', ' ').replace('/', ' ').split():
                    tel = tel.strip()
                    if not tel: continue
                    fmt = formatar_numero(tel)
                    if fmt:
                        pessoas[chave]['telefones'].add((tel, fmt))

        # =========================================================================
        # NORMALIZAÇÃO DE PROCEDIMENTOS COM IA (DeepSeek)
        # =========================================================================
        # Coletar procedimentos únicos da planilha
        procedimentos_unicos = set()
        for dados in pessoas.values():
            if dados['procedimento']:
                procedimentos_unicos.add(dados['procedimento'])

        # Normalizar procedimentos únicos usando IA com cache
        ai = DeepSeekAI()
        mapa_normalizacao = {}  # original -> normalizado

        logger.info(f"Normalizando {len(procedimentos_unicos)} procedimentos únicos...")

        # Separar procedimentos que já estão no cache vs que precisam normalizar
        procedimentos_para_normalizar = []
        for proc_original in procedimentos_unicos:
            cached = ProcedimentoNormalizado.obter_ou_criar(proc_original)
            if cached and cached.aprovado:
                # Usar do cache
                mapa_normalizacao[proc_original] = cached.termo_simples
                logger.info(f"[CACHE] '{proc_original}' -> '{cached.termo_simples}'")
                cached.incrementar_uso()
            else:
                # Adicionar para normalizar em batch
                procedimentos_para_normalizar.append(proc_original)

        # Normalizar em BATCH (dividir em chunks de 20 procedimentos)
        if procedimentos_para_normalizar:
            BATCH_SIZE = 20  # Processar 20 procedimentos por vez
            total = len(procedimentos_para_normalizar)
            logger.info(f"Normalizando {total} procedimentos em lotes de {BATCH_SIZE}...")

            # Dividir em chunks
            for i in range(0, total, BATCH_SIZE):
                chunk = procedimentos_para_normalizar[i:i+BATCH_SIZE]
                chunk_num = (i // BATCH_SIZE) + 1
                total_chunks = (total + BATCH_SIZE - 1) // BATCH_SIZE

                logger.info(f"[LOTE {chunk_num}/{total_chunks}] Processando {len(chunk)} procedimentos...")

                try:
                    resultados_batch = ai._chamar_api_batch(chunk)
                    logger.info(f"[LOTE {chunk_num}/{total_chunks}] API retornou {len(resultados_batch)} resultados")

                    for proc_original in chunk:
                        resultado = resultados_batch.get(proc_original.upper())
                        if resultado and resultado.get('termo_simples'):
                            # Salvar no cache
                            ProcedimentoNormalizado.salvar_normalizacao(
                                termo_original=proc_original,
                                termo_normalizado=resultado['termo_normalizado'],
                                termo_simples=resultado['termo_simples'],
                                explicacao=resultado.get('explicacao', ''),
                                fonte='deepseek'
                            )
                            mapa_normalizacao[proc_original] = resultado['termo_simples']
                            logger.info(f"[API] '{proc_original}' -> '{resultado['termo_simples']}'")
                        else:
                            # Fallback: usar o original
                            mapa_normalizacao[proc_original] = proc_original.title()
                            logger.warning(f"[FALLBACK] '{proc_original}' -> usando original")

                except Exception as e:
                    logger.error(f"[LOTE {chunk_num}/{total_chunks}] Erro ao processar batch: {e}")
                    # Em caso de erro, usar original para este chunk
                    for proc_original in chunk:
                        if proc_original not in mapa_normalizacao:
                            mapa_normalizacao[proc_original] = proc_original.title()
                            logger.warning(f"[ERRO-FALLBACK] '{proc_original}' -> usando original")

        logger.info(f"Normalização concluída. {len(mapa_normalizacao)} mapeamentos criados.")
        # =========================================================================

        # Salvar no Banco
        for chave, dados in pessoas.items():
            if not dados['telefones']:
                continue

            # Obter procedimento normalizado
            proc_original = dados['procedimento']
            proc_normalizado = mapa_normalizacao.get(proc_original, proc_original)

            c = Contato(
                campanha_id=campanha_id,
                nome=dados['nome'][:200],
                data_nascimento=dados['nascimento'],
                procedimento=proc_original[:500],  # Termo original
                procedimento_normalizado=proc_normalizado[:300],  # Termo normalizado
                status='pendente'
            )
            db.session.add(c)
            db.session.flush() # Para ter o ID

            for i, (original, fmt) in enumerate(dados['telefones']):
                t = Telefone(
                    contato_id=c.id,
                    numero=original[:20],
                    numero_fmt=fmt,
                    prioridade=i+1
                )
                db.session.add(t)

            criados += 1

        db.session.commit()
        camp = db.session.get(Campanha, campanha_id)
        if camp:
            camp.atualizar_stats()
            db.session.commit()

        return True, "OK", criados
    except Exception as e:
        logger.error(f"Erro processar planilha: {e}")
        return False, str(e), 0
