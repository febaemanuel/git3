"""Shared module for the BUSCA ATIVA / Agendamento / GERAL stack.

Holds the constants, helper functions, AI/OCR classes and seed routines
that the route blueprints (app/routes/*) consume. The Flask app itself is
built by ``app.create_app()``; this module only contributes data and
behavior, not application construction.
"""

from flask import render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_user, logout_user, login_required, current_user
from app.extensions import db, login_manager, csrf
from app.services.timezone import (
    TZ_FORTALEZA,
    obter_agora_fortaleza,
    obter_hora_fortaleza,
    obter_hoje_fortaleza,
)
from app.services.telefone import formatar_numero
from app.services.whatsapp import WhatsApp
from app.services.mensagem import (
    formatar_data_consulta,
    enviar_e_registrar_consulta,
    obter_saudacao_dinamica,
    formatar_mensagem_consulta_inicial,
    formatar_mensagem_consulta_retry1,
    formatar_mensagem_consulta_retry2,
    formatar_mensagem_comprovante,
    formatar_mensagem_perguntar_motivo,
    formatar_mensagem_voltar_posto,
    formatar_mensagem_interconsulta_aprovada,
    formatar_mensagem_confirmacao_rejeicao,
    formatar_mensagem_cancelamento_sem_resposta,
    formatar_mensagem_fila_retry1,
    formatar_mensagem_fila_retry2,
    formatar_mensagem_fila_sem_resposta,
)
from datetime import datetime, timedelta, date
import pandas as pd
import os
import threading
import time
import logging
import requests
import json
from io import BytesIO


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('busca_ativa.log', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# Importar Celery app configurado com backend Redis
try:
    from celery_app import celery as celery_app
    from celery.result import AsyncResult
except ImportError as e:
    celery_app = None
    AsyncResult = None
    logger.warning(f"Celery não disponível - funcionalidades assíncronas desabilitadas: {e}")

# Backwards-compat re-exports: extrair_dados_comprovante moved to
# app/services/ocr.py, AI classes to app/ai.py, seed data to app/seeds.py.
from app.services.ocr import extrair_dados_comprovante  # noqa: F401
from app.ai import AnaliseSentimento, DeepSeekAI, SistemaFAQ  # noqa: F401
from app.seeds import (  # noqa: F401
    ADMIN_EMAIL, ADMIN_NOME, ADMIN_SENHA,
    criar_admin, criar_faqs_padrao, criar_tutoriais_padrao,
)

# Constantes

# RESPOSTAS VÁLIDAS - DEVEM SER EXATAS (não aceita palavras soltas em frases)
# Aceita combinações como "1 SIM", "2 NAO" etc.
RESPOSTAS_SIM = [
    'SIM', 'S', '1',
    'CONFIRMO', 'CONFIRMADO',
    'TENHO INTERESSE', 'ACEITO', 'OK',
    '1 SIM', '1SIM', 'SIM 1', 'SIM1'
]
RESPOSTAS_NAO = [
    'NAO', 'NÃO', 'N', '2',
    'NAO QUERO', 'NÃO QUERO',
    'NAO TENHO INTERESSE', 'NÃO TENHO INTERESSE',
    '2 NAO', '2NAO', 'NAO 2', 'NAO2',
    '2 NÃO', '2NÃO', 'NÃO 2', 'NÃO2'
]
RESPOSTAS_DESCONHECO = [
    '3', 'DESCONHECO', 'DESCONHEÇO',
    'NAO SOU', 'NÃO SOU',
    'ENGANO', 'NUMERO ERRADO', 'NÚMERO ERRADO',
    '3 DESCONHECO', '3DESCONHECO', '3 DESCONHEÇO', '3DESCONHEÇO'
]

MENSAGEM_PADRAO = """📋 *Olá, {nome}*!

Aqui é da *Central de Agendamentos do Hospital Universitário Walter Cantídio*.

Consta em nossos registros que você está na lista de espera para o procedimento: *{procedimento}*.

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa

_Por favor, responda com o número da opção._
"""


# =============================================================================
# MODELOS (movidos para app/models/* — re-exportados aqui pra manter as
# referências usadas pelas rotas em app/main.py)
# =============================================================================

from app.models import *  # noqa: F401,F403
from app.models import (  # noqa: F401  (explicit names for linters)
    Usuario,
    ConfigGlobal, ConfigWhatsApp, RespostaAutomatica, Tutorial,
    ProcedimentoNormalizado,
    Campanha, Contato, Telefone, LogMsg, TicketAtendimento,
    TentativaContato, ConfigTentativas,
    CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta,
    LogMsgConsulta, PesquisaSatisfacao, Paciente,
    ComprovanteAntecipado, HistoricoConsulta,
    normalizar_nome_paciente, buscar_comprovante_antecipado,
    ConfigUsuarioGeral, TIPOS_PERGUNTA, Pesquisa, PerguntaPesquisa,
    RespostaPesquisa, RespostaItem, STATUS_ENVIO_PESQUISA,
    STATUS_ENVIO_TELEFONE, TEMPLATES_PESQUISA, EnvioPesquisa,
    EnvioPesquisaTelefone,
)







# =============================================================================
# FUNCOES AUXILIARES
# =============================================================================

def verificar_acesso_campanha(campanha_id):
    """Verifica se o usuario atual tem acesso a campanha.
    Retorna a campanha se tiver acesso, senao retorna None."""
    from flask import abort
    camp = Campanha.query.get_or_404(campanha_id)
    if camp.criador_id != current_user.id:
        abort(403)  # Forbidden
    return camp

def verificar_acesso_ticket(ticket_id):
    """Verifica se o usuario atual tem acesso ao ticket.
    Retorna o ticket se tiver acesso, senao retorna None."""
    from flask import abort
    ticket = TicketAtendimento.query.get_or_404(ticket_id)
    if ticket.campanha and ticket.campanha.criador_id != current_user.id:
        abort(403)  # Forbidden
    return ticket

def verificar_acesso_contato(contato_id):
    """Verifica se o usuario atual tem acesso ao contato.
    Retorna o contato se tiver acesso, senao retorna None."""
    from flask import abort
    contato = Contato.query.get_or_404(contato_id)
    if contato.campanha.criador_id != current_user.id:
        abort(403)  # Forbidden
    return contato

def get_dashboard_route():
    """
    Retorna a rota correta do dashboard baseado no tipo_sistema do usuário
    IMPORTANTE: Use isso em TODOS os redirecionamentos para dashboard
    """
    if current_user.is_authenticated:
        tipo = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
        if tipo == 'AGENDAMENTO_CONSULTA':
            return 'consultas.dashboard'
        if tipo == 'GERAL':
            return 'geral.dashboard'
        # Aceita tanto BUSCA_ATIVA quanto FILA_CIRURGICA (compatibilidade)
        return 'fila.dashboard'
    return 'auth.login'

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


def validar_campanha_bg(campanha_id):
    """
    DEPRECATED: Esta função foi substituída pela task Celery validar_campanha_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.validar_campanha_task.delay(campanha_id) ao invés desta função.
    """
    from app import app  # lazy: avoids circular import
    with app.app_context():
        try:
            camp = db.session.get(Campanha, campanha_id)
            if not camp:
                return

            camp.status = 'validando'
            camp.status_msg = 'Verificando numeros...'
            db.session.commit()

            # Usar WhatsApp do criador da campanha
            ws = WhatsApp(camp.criador_id)
            if not ws.ok():
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp nao configurado'
                db.session.commit()
                return

            # Buscar telefones pendentes de validacao
            # Join com Contato para garantir que sao da campanha certa
            telefones = Telefone.query.join(Contato).filter(Contato.campanha_id == campanha_id, Telefone.whatsapp_valido == None).all()
            
            if not telefones:
                camp.status = 'pronta'
                camp.status_msg = 'Nenhum numero para validar'
                db.session.commit()
                return

            total = len(telefones)
            validos = invalidos = 0

            # Processa em lotes
            batch = 50
            for i in range(0, total, batch):
                lote = telefones[i:i+batch]
                nums = [t.numero_fmt for t in lote]

                camp.status_msg = f'Verificando {i+len(lote)}/{total}...'
                db.session.commit()

                result = ws.verificar_numeros(nums)

                for t in lote:
                    info = result.get(t.numero_fmt, {})
                    t.whatsapp_valido = info.get('exists', False)
                    t.jid = info.get('jid', '')
                    t.data_validacao = datetime.utcnow()
                    if t.whatsapp_valido:
                        validos += 1
                    else:
                        invalidos += 1

                db.session.commit()
                time.sleep(1)

            # Atualizar status dos contatos
            # Se tiver pelo menos 1 valido -> pronto_envio
            contatos = camp.contatos.all()
            for c in contatos:
                tels_validos = c.telefones.filter_by(whatsapp_valido=True).count()
                if tels_validos > 0:
                    if c.status == 'pendente':
                        c.status = 'pronto_envio'
                else:
                    # Se ja validou todos e nao tem nenhum valido
                    tels_pendentes = c.telefones.filter_by(whatsapp_valido=None).count()
                    if tels_pendentes == 0:
                        c.status = 'sem_whatsapp' # ou erro

            camp.status = 'pronta'
            camp.status_msg = f'{validos} nums validos, {invalidos} invalidos'
            camp.atualizar_stats()
            db.session.commit()

        except Exception as e:
            logger.error(f"Erro validacao: {e}")
            camp = db.session.get(Campanha, campanha_id)
            if camp:
                camp.status = 'erro'
                camp.status_msg = str(e)[:200]
                db.session.commit()


def enviar_campanha_bg(campanha_id):
    """
    DEPRECATED: Esta função foi substituída pela task Celery enviar_campanha_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.enviar_campanha_task.delay(campanha_id) ao invés desta função.
    """
    from app import app  # lazy: avoids circular import
    with app.app_context():
        try:
            camp = db.session.get(Campanha, campanha_id)
            if not camp:
                return

            ws = WhatsApp(camp.criador_id)
            if not ws.ok():
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp nao configurado'
                db.session.commit()
                return

            conn, _ = ws.conectado()
            if not conn:
                camp.status = 'erro'
                camp.status_msg = 'WhatsApp desconectado'
                db.session.commit()
                return

            camp.status = 'em_andamento'
            camp.data_inicio = datetime.utcnow()
            db.session.commit()

            # Buscar contatos pendentes ou prontos
            # Prioriza prontos, depois pendentes
            contatos = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).order_by(Contato.status.desc(), Contato.id).all()
            
            total = len(contatos)
            enviados_pessoas = 0 # Contador de PESSOAS contactadas com sucesso
            erros = 0

            for i, c in enumerate(contatos):
                db.session.refresh(camp)
                if camp.status != 'em_andamento':
                    break

                # Verificar se atingiu duração máxima
                if camp.atingiu_duracao():
                    camp.status = 'concluida'
                    camp.status_msg = f'Duração de {camp.dias_duracao} dias atingida'
                    db.session.commit()
                    break

                # Verificar se está dentro do horário de funcionamento
                if not camp.pode_enviar_agora():
                    camp.status = 'pausada'
                    camp.status_msg = f'Fora do horário ({camp.hora_inicio}h-{camp.hora_fim}h)'
                    db.session.commit()
                    break

                # Verificar se atingiu meta diária
                if not camp.pode_enviar_hoje():
                    camp.status = 'pausada'
                    camp.status_msg = f'Meta diária atingida ({camp.meta_diaria} pessoas)'
                    db.session.commit()
                    break

                camp.status_msg = f'Processando {i+1}/{total}: {c.nome}'
                db.session.commit()
                
                # Validacao JIT (Just-In-Time)
                if c.status == 'pendente':
                    # Validar numeros deste contato
                    tels = c.telefones.filter_by(whatsapp_valido=None).all()
                    if tels:
                        nums = [t.numero_fmt for t in tels]
                        result = ws.verificar_numeros(nums)
                        
                        tem_valido = False
                        for t in tels:
                            info = result.get(t.numero_fmt, {})
                            t.whatsapp_valido = info.get('exists', False)
                            t.jid = info.get('jid', '')
                            t.data_validacao = datetime.utcnow()
                            if t.whatsapp_valido:
                                tem_valido = True
                        
                        db.session.commit()
                        
                        # Re-verificar se tem validos agora
                        if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                            c.status = 'pronto_envio'
                        else:
                            c.status = 'sem_whatsapp'
                            db.session.commit()
                            continue # Pula para proximo
                    else:
                        # Se estava pendente mas nao tinha numeros para validar (??)
                        if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                            c.status = 'pronto_envio'
                        else:
                            c.status = 'sem_whatsapp'
                            db.session.commit()
                            continue

                # Envio
                if c.status == 'pronto_envio':
                    # Usar procedimento normalizado (mais simples) se disponível, senão usar original
                    procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
                    msg = camp.mensagem.replace('{nome}', c.nome).replace('{procedimento}', procedimento_msg)
                    
                    # Enviar para TODOS os numeros validos da pessoa
                    telefones_validos = c.telefones.filter_by(whatsapp_valido=True).all()
                    
                    sucesso_pessoa = False
                    
                    for t in telefones_validos:
                        ok, result = ws.enviar(t.numero_fmt, msg)

                        if ok:
                            t.enviado = True
                            t.data_envio = datetime.utcnow()
                            t.msg_id = result
                            sucesso_pessoa = True

                            log = LogMsg(campanha_id=camp.id, contato_id=c.id, direcao='enviada',
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='ok')
                            db.session.add(log)
                        else:
                            log = LogMsg(campanha_id=camp.id, contato_id=c.id, direcao='enviada',
                                         telefone=t.numero_fmt, mensagem=msg[:500], status='erro', erro=result)

                    # Se conseguiu enviar para pelo menos um número, registrar o envio
                    if sucesso_pessoa:
                        c.status = 'enviado'
                        camp.registrar_envio()  # Incrementar contador diário
                        enviados_pessoas += 1

                    db.session.commit()
                    camp.atualizar_stats()
                    db.session.commit()

                    if i < total - 1:
                        # Calcular intervalo automaticamente baseado no horário e meta diária
                        intervalo = camp.calcular_intervalo()
                        logger.info(f"Aguardando {intervalo}s até próximo envio (baseado em {camp.hora_inicio}h-{camp.hora_fim}h, meta: {camp.meta_diaria})")
                        time.sleep(intervalo)

            # Verificar se acabou
            # Se nao tem mais pendentes ou pronto_envio
            restantes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
            if restantes == 0 and camp.status == 'em_andamento':
                camp.status = 'concluida'
                camp.data_fim = datetime.utcnow()
                camp.status_msg = f'{enviados_pessoas} pessoas contactadas'

            camp.atualizar_stats()
            db.session.commit()

        except Exception as e:
            logger.error(f"Erro envio: {e}")
            camp = db.session.get(Campanha, campanha_id)
            if camp:
                camp.status = 'erro'
                camp.status_msg = str(e)[:200]
                db.session.commit()


def processar_followup_bg():
    """
    DEPRECATED: Esta função foi substituída pela task Celery follow_up_automatico_task.
    Mantida apenas para compatibilidade temporária.
    Use tasks.follow_up_automatico_task.delay() ao invés desta função.
    """
    from app import app  # lazy: avoids circular import
    with app.app_context():
        try:
            config = ConfigTentativas.get()
            if not config.ativo:
                logger.info("Follow-up desativado")
                return

            logger.info("=== INICIANDO PROCESSAMENTO DE FOLLOW-UP ===")

            # Mensagens de follow-up personalizadas
            MENSAGENS_FOLLOWUP = {
                1: """📋 *Olá novamente, {nome}*!

Não recebemos sua resposta sobre o procedimento: *{procedimento}*.

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa""",

                2: """📋 *{nome}*, esta é nossa penúltima tentativa de contato.

Procedimento: *{procedimento}*

⚠️ *IMPORTANTE:* Se não recebermos resposta em {dias} dias, faremos uma última tentativa.

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho interesse""",

                3: """📋 *{nome}*, este é nosso último contato.

Como não recebemos resposta, vamos considerar que você não tem mais interesse no procedimento: *{procedimento}*.

Se ainda tiver interesse, responda URGENTE nesta mensagem ou ligue para (85) 3366-8000.

Caso contrário, sua vaga será disponibilizada."""
            }

            data_limite = datetime.utcnow() - timedelta(days=config.intervalo_dias)

            # Buscar contatos que precisam de follow-up
            contatos = Contato.query.join(Telefone).filter(
                Contato.status == 'enviado',
                Contato.confirmado == False,
                Contato.rejeitado == False,
                Contato.data_resposta == None,
                Telefone.enviado == True,
                Telefone.whatsapp_valido == True
            ).distinct().all()

            logger.info(f"Total de contatos para verificar: {len(contatos)}")

            processados = 0

            for c in contatos:
                # Verificar última tentativa
                ultima_tentativa = TentativaContato.query.filter_by(
                    contato_id=c.id
                ).order_by(TentativaContato.numero_tentativa.desc()).first()

                # Verificar primeira tentativa (envio original)
                primeiro_envio = c.telefones.filter(Telefone.enviado == True).order_by(Telefone.data_envio).first()

                if not ultima_tentativa:
                    # Primeira tentativa de follow-up
                    if primeiro_envio and primeiro_envio.data_envio < data_limite:
                        num_tentativa = 1
                    else:
                        continue
                else:
                    # Já tem tentativas
                    if ultima_tentativa.numero_tentativa >= config.max_tentativas:
                        # Esgotou tentativas - marcar como "sem resposta"
                        if c.status != 'sem_resposta':
                            c.status = 'sem_resposta'
                            c.erro = f'Sem resposta após {config.max_tentativas} tentativas'
                            db.session.commit()
                            logger.info(f"Contato {c.nome} marcado como sem resposta")
                        continue

                    if ultima_tentativa.data_tentativa < data_limite:
                        num_tentativa = ultima_tentativa.numero_tentativa + 1
                    else:
                        continue

                # Enviar follow-up
                msg_template = MENSAGENS_FOLLOWUP.get(num_tentativa, MENSAGENS_FOLLOWUP[1])
                # Usar procedimento normalizado (mais simples) se disponível, senão usar original
                procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
                msg = msg_template.replace('{nome}', c.nome).replace(
                    '{procedimento}', procedimento_msg
                ).replace('{dias}', str(config.intervalo_dias))

                # Criar WhatsApp instance para o criador da campanha
                if not c.campanha or not c.campanha.criador_id:
                    logger.warning(f"Contato {c.id} sem campanha ou criador válido")
                    continue

                ws = WhatsApp(c.campanha.criador_id)
                if not ws.ok():
                    logger.error(f"WhatsApp não configurado para usuário {c.campanha.criador_id}")
                    continue

                telefones = c.telefones.filter_by(whatsapp_valido=True).all()
                enviado = False

                for t in telefones:
                    ok, _ = ws.enviar(t.numero_fmt, msg)
                    if ok:
                        enviado = True

                        # Registrar tentativa
                        tentativa = TentativaContato(
                            contato_id=c.id,
                            numero_tentativa=num_tentativa,
                            data_tentativa=datetime.utcnow(),
                            proxima_tentativa=datetime.utcnow() + timedelta(days=config.intervalo_dias),
                            status='enviada',
                            mensagem_enviada=msg
                        )
                        db.session.add(tentativa)

                        # Log
                        log = LogMsg(
                            campanha_id=c.campanha_id,
                            contato_id=c.id,
                            direcao='enviada',
                            telefone=t.numero_fmt,
                            mensagem=f'[Follow-up {num_tentativa}] {msg[:500]}',
                            status='ok'
                        )
                        db.session.add(log)

                        logger.info(f"Follow-up {num_tentativa} enviado para {c.nome}")
                        break

                if enviado:
                    db.session.commit()
                    processados += 1
                    time.sleep(15)  # Intervalo entre envios

            logger.info(f"=== FOLLOW-UP CONCLUÍDO: {processados} mensagens enviadas ===")

        except Exception as e:
            logger.error(f"Erro no processamento de follow-up: {e}", exc_info=True)


@login_manager.user_loader
def load_user(uid):
    return db.session.get(Usuario, int(uid))


# Decorator para rotas que exigem permissão de administrador
def admin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated:
            return redirect(url_for('auth.login'))
        if not current_user.is_admin:
            flash('❌ Acesso negado. Apenas administradores podem acessar esta página.', 'danger')
            return redirect(url_for(get_dashboard_route()))
        return f(*args, **kwargs)
    return decorated_function


# =============================================================================
# ROTAS
# =============================================================================































# API
# @app.route('/api/dashboard/tickets')
# @login_required
# def api_dashboard_tickets():
#     """Retorna estatísticas de tickets para o dashboard"""
#     # Filtrar apenas tickets das campanhas do usuario atual
#     user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]
#     if user_campanhas_ids:
#         urgentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente', TicketAtendimento.prioridade == 'urgente').count()
#         pendentes = TicketAtendimento.query.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids), TicketAtendimento.status == 'pendente').count()
#     else:
#         urgentes = 0
#         pendentes = 0
#     return jsonify({'urgentes': urgentes, 'pendentes': pendentes})




















# Configuracoes




# =============================================================================
# ADMIN DASHBOARD - Painel de Performance do Sistema
# =============================================================================





















# Funcao auxiliar para verificar respostas validas
def verificar_resposta_em_lista(texto_up, lista_respostas):
    """
    Verifica se o texto É EXATAMENTE uma resposta válida.
    MUDANÇA CRÍTICA: Agora aceita SOMENTE respostas exatas (mensagem completa).
    Exemplos:
    - "SIM" → ✅ aceito
    - "1" → ✅ aceito  
    - "TENHO INTERESSE" → ✅ aceito
    - "Boa tarde! Não sei quando posso ir" → ❌ rejeitado (não é resposta exata)
    - "Sim, quero" → ❌ rejeitado (não é resposta exata)
    """
    # Remove espaços extras e normaliza
    texto_normalizado = ' '.join(texto_up.split())
    
    # Verifica se a mensagem COMPLETA é exatamente uma das respostas válidas
    return texto_normalizado in lista_respostas


# Webhook




# =============================================================================
# ROTAS - FAQ (RESPOSTAS AUTOMATICAS)
# =============================================================================









# # =============================================================================
# # ROTAS - ATENDIMENTO (TICKETS)
# # =============================================================================
# 
# @app.route('/atendimento')
# @login_required
# def painel_atendimento():
#     filtro = request.args.get('filtro', 'pendente')
#     page = request.args.get('page', 1, type=int)
# 
#     # Filtrar apenas tickets das campanhas do usuario atual
#     user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]
# 
#     q = TicketAtendimento.query
#     if user_campanhas_ids:
#         q = q.filter(TicketAtendimento.campanha_id.in_(user_campanhas_ids))
#     else:
#         # Se nao tem campanhas, nao tem tickets
#         q = q.filter(TicketAtendimento.id == None)
# 
#     if filtro == 'pendente':
#         q = q.filter_by(status='pendente')
#     elif filtro == 'em_atendimento':
#         q = q.filter_by(status='em_atendimento')
#     elif filtro == 'resolvido':
#         q = q.filter_by(status='resolvido')
#     elif filtro == 'meus':
#         q = q.filter_by(atendente_id=current_user.id, status='em_atendimento')
#     elif filtro == 'urgente':
#         q = q.filter_by(prioridade='urgente', status='pendente')
# 
#     # Buscar todos os tickets (nao paginados ainda)
#     all_tickets = q.order_by(
#         TicketAtendimento.prioridade.desc(),
#         TicketAtendimento.data_criacao.desc()
#     ).all()
# 
#     # Agrupar tickets por (contato_id, campanha_id)
#     from collections import defaultdict
#     grupos = defaultdict(list)
#     for ticket in all_tickets:
#         chave = (ticket.contato_id, ticket.campanha_id)
#         grupos[chave].append(ticket)
# 
#     # Criar lista de grupos com informacoes agregadas
#     grupos_lista = []
#     prioridade_ordem = {'urgente': 4, 'alta': 3, 'media': 2, 'baixa': 1}
# 
#     for (contato_id, campanha_id), tickets_grupo in grupos.items():
#         # Ordenar tickets do grupo por data (mais recente primeiro)
#         tickets_grupo.sort(key=lambda t: t.data_criacao, reverse=True)
# 
#         # Pegar a maior prioridade do grupo
#         maior_prioridade = max(tickets_grupo, key=lambda t: prioridade_ordem.get(t.prioridade, 0))
# 
#         grupo_obj = {
#             'tickets': tickets_grupo,
#             'ticket_principal': tickets_grupo[0],  # Mais recente
#             'contato': tickets_grupo[0].contato,
#             'campanha': tickets_grupo[0].campanha,
#             'prioridade': maior_prioridade.prioridade,
#             'status': tickets_grupo[0].status,
#             'data_criacao': tickets_grupo[0].data_criacao,
#             'count': len(tickets_grupo),
#             'atendente': tickets_grupo[0].atendente
#         }
#         grupos_lista.append(grupo_obj)
# 
#     # Ordenar grupos por prioridade e data
#     grupos_lista.sort(
#         key=lambda g: (prioridade_ordem.get(g['prioridade'], 0), g['data_criacao']),
#         reverse=True
#     )
# 
#     # Paginar os grupos
#     per_page = 20
#     total = len(grupos_lista)
#     total_pages = (total + per_page - 1) // per_page
#     start = (page - 1) * per_page
#     end = start + per_page
#     grupos_paginados = grupos_lista[start:end]
# 
#     # Criar objeto de paginacao simulado
#     class PaginacaoSimulada:
#         def __init__(self, items, page, per_page, total):
#             self.items = items
#             self.page = page
#             self.per_page = per_page
#             self.total = total
#             self.pages = (total + per_page - 1) // per_page
#             self.has_prev = page > 1
#             self.has_next = page < self.pages
#             self.prev_num = page - 1 if self.has_prev else None
#             self.next_num = page + 1 if self.has_next else None
# 
#         def iter_pages(self, left_edge=2, left_current=2, right_current=5, right_edge=2):
#             last = 0
#             for num in range(1, self.pages + 1):
#                 if num <= left_edge or \
#                    (num > self.page - left_current - 1 and num < self.page + right_current) or \
#                    num > self.pages - right_edge:
#                     if last + 1 != num:
#                         yield None
#                     yield num
#                     last = num
# 
#     tickets_agrupados = PaginacaoSimulada(grupos_paginados, page, per_page, total)
# 
#     # Estatísticas apenas dos tickets das campanhas do usuario
#     # IMPORTANTE: Contar grupos (contato+campanha), não tickets individuais
#     if user_campanhas_ids:
#         # Buscar tickets pendentes e agrupar
#         tickets_pendentes = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'pendente'
#         ).all()
#         grupos_pendentes = set((t.contato_id, t.campanha_id) for t in tickets_pendentes)
# 
#         # Em atendimento
#         tickets_atendimento = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'em_atendimento'
#         ).all()
#         grupos_atendimento = set((t.contato_id, t.campanha_id) for t in tickets_atendimento)
# 
#         # Urgentes pendentes
#         tickets_urgentes = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.prioridade == 'urgente',
#             TicketAtendimento.status == 'pendente'
#         ).all()
#         grupos_urgentes = set((t.contato_id, t.campanha_id) for t in tickets_urgentes)
# 
#         # Resolvidos hoje
#         tickets_resolvidos = TicketAtendimento.query.filter(
#             TicketAtendimento.campanha_id.in_(user_campanhas_ids),
#             TicketAtendimento.status == 'resolvido',
#             TicketAtendimento.data_resolucao >= datetime.utcnow().replace(hour=0, minute=0, second=0)
#         ).all()
#         grupos_resolvidos = set((t.contato_id, t.campanha_id) for t in tickets_resolvidos)
# 
#         stats = {
#             'pendente': len(grupos_pendentes),
#             'em_atendimento': len(grupos_atendimento),
#             'urgente': len(grupos_urgentes),
#             'resolvido_hoje': len(grupos_resolvidos)
#         }
#     else:
#         stats = {'pendente': 0, 'em_atendimento': 0, 'urgente': 0, 'resolvido_hoje': 0}
# 
#     return render_template('atendimento.html', tickets=tickets_agrupados, filtro=filtro, stats=stats)
# 
# 
# @app.route('/atendimento/<int:id>')
# @login_required
# def detalhe_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     # Buscar todos os tickets do mesmo grupo (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id
#     ).order_by(TicketAtendimento.data_criacao.desc()).all()
# 
#     # Buscar histórico de mensagens do contato
#     logs = LogMsg.query.filter_by(contato_id=ticket.contato_id).order_by(LogMsg.data.desc()).limit(20).all()
# 
#     return render_template('ticket_detalhe.html', ticket=ticket, tickets_relacionados=tickets_relacionados, logs=logs)
# 
# 
# @app.route('/atendimento/<int:id>/assumir', methods=['POST'])
# @login_required
# def assumir_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     if ticket.status != 'pendente':
#         flash('Ticket já está em atendimento', 'warning')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     # Assumir ticket atual
#     ticket.status = 'em_atendimento'
#     ticket.atendente_id = current_user.id
#     ticket.data_atendimento = datetime.utcnow()
# 
#     # Assumir TODOS os tickets relacionados (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id,
#         status='pendente'
#     ).all()
# 
#     for t in tickets_relacionados:
#         t.status = 'em_atendimento'
#         t.atendente_id = current_user.id
#         t.data_atendimento = datetime.utcnow()
# 
#     db.session.commit()
# 
#     flash(f'✅ {len(tickets_relacionados)} ticket(s) assumido(s)!', 'success')
#     return redirect(url_for('detalhe_ticket', id=id))
# 
# 
# @app.route('/atendimento/<int:id>/responder', methods=['POST'])
# @login_required
# def responder_ticket(id):
#     ticket = verificar_acesso_ticket(id)
#     resposta = request.form.get('resposta', '').strip()
# 
#     if not resposta:
#         flash('Digite uma resposta', 'danger')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     # Enviar via WhatsApp usando a instância do criador da campanha
#     ws = WhatsApp(ticket.campanha.criador_id)
# 
#     # Priorizar telefones validados, mas aceitar todos se não houver validados
#     telefones_validados = ticket.contato.telefones.filter_by(whatsapp_valido=True).all()
#     telefones_todos = ticket.contato.telefones.all()
# 
#     # Usar validados se houver, senão usar todos
#     telefones = telefones_validados if telefones_validados else telefones_todos
# 
#     if not telefones:
#         flash('Nenhum telefone cadastrado para este contato', 'danger')
#         return redirect(url_for('detalhe_ticket', id=id))
# 
#     enviado = False
#     erro_msg = None
#     for tel in telefones:
#         ok, resultado = ws.enviar(tel.numero_fmt, f"👤 *Resposta do atendente {current_user.nome}:*\n\n{resposta}")
#         if ok:
#             enviado = True
# 
#             # Registrar log
#             log = LogMsg(
#                 campanha_id=ticket.campanha_id,
#                 contato_id=ticket.contato_id,
#                 direcao='enviada',
#                 telefone=tel.numero_fmt,
#                 mensagem=f'[Atendimento] {resposta}',
#                 status='ok'
#             )
#             db.session.add(log)
#             break
#         else:
#             erro_msg = resultado
# 
#     if enviado:
#         # Resolver ticket atual
#         ticket.status = 'resolvido'
#         ticket.data_resolucao = datetime.utcnow()
#         ticket.resposta = resposta
# 
#         # Resolver TODOS os tickets relacionados (mesmo contato e campanha)
#         tickets_relacionados = TicketAtendimento.query.filter_by(
#             contato_id=ticket.contato_id,
#             campanha_id=ticket.campanha_id
#         ).filter(TicketAtendimento.status != 'resolvido').all()
# 
#         for t in tickets_relacionados:
#             t.status = 'resolvido'
#             t.data_resolucao = datetime.utcnow()
#             t.resposta = resposta
# 
#         db.session.commit()
# 
#         flash(f'✅ Resposta enviada e {len(tickets_relacionados)} ticket(s) resolvido(s) com sucesso!', 'success')
#     else:
#         msg_erro = f'❌ Erro ao enviar resposta via WhatsApp'
#         if erro_msg:
#             msg_erro += f': {erro_msg}'
#         flash(msg_erro, 'danger')
# 
#     return redirect(url_for('painel_atendimento'))
# 
# 
# @app.route('/atendimento/<int:id>/cancelar', methods=['POST'])
# @login_required
# def cancelar_ticket(id):
#     ticket = verificar_acesso_ticket(id)
# 
#     # Cancelar ticket atual
#     ticket.status = 'cancelado'
# 
#     # Cancelar TODOS os tickets relacionados (mesmo contato e campanha)
#     tickets_relacionados = TicketAtendimento.query.filter_by(
#         contato_id=ticket.contato_id,
#         campanha_id=ticket.campanha_id
#     ).filter(TicketAtendimento.status.in_(['pendente', 'em_atendimento'])).all()
# 
#     for t in tickets_relacionados:
#         t.status = 'cancelado'
# 
#     db.session.commit()
# 
#     flash(f'✅ {len(tickets_relacionados)} ticket(s) cancelado(s)', 'info')
#     return redirect(url_for('painel_atendimento'))
# 
# 
# =============================================================================
# ROTAS - CADASTRO PUBLICO
# =============================================================================



# =============================================================================
# ROTAS - USUÁRIO GERAL (wizard de configuração + dashboard placeholder)
# =============================================================================

TIPOS_USO_GERAL = ['CONFIRMACAO', 'PESQUISA', 'ENQUETE']
CANAIS_RESPOSTA_GERAL = ['WHATSAPP_LINK_EXTERNO', 'WHATSAPP_INTERATIVO', 'LINK_INTERNO']


def _exigir_usuario_geral():
    """Bloqueia acesso a quem não é tipo_sistema='GERAL'. Retorna a config (criando se necessário)."""
    if getattr(current_user, 'tipo_sistema', None) != 'GERAL':
        flash('Esta área é exclusiva de usuários do tipo Geral.', 'warning')
        return None, redirect(url_for(get_dashboard_route()))

    config = ConfigUsuarioGeral.query.filter_by(usuario_id=current_user.id).first()
    if not config:
        config = ConfigUsuarioGeral(usuario_id=current_user.id, wizard_concluido=False)
        db.session.add(config)
        db.session.commit()
    return config, None






# -----------------------------------------------------------------------------
# Pesquisas (CRUD para o usuário GERAL)
# -----------------------------------------------------------------------------

def _get_pesquisa_do_usuario(pesquisa_id):
    """Carrega a pesquisa garantindo que pertence ao usuário logado (ou admin)."""
    from flask import abort
    pesquisa = Pesquisa.query.get_or_404(pesquisa_id)
    if pesquisa.usuario_id != current_user.id and not current_user.is_admin:
        abort(403)
    return pesquisa






















# -----------------------------------------------------------------------------
# Envio em massa do link da pesquisa via WhatsApp
# -----------------------------------------------------------------------------

def _normalizar_telefones_textarea(texto):
    """Recebe texto (uma linha por telefone, opcional 'nome | numero') e devolve
    lista [(numero_formatado, nome_or_None), ...] sem duplicatas, com numero válido.
    """
    seen = set()
    saida = []
    for linha in (texto or '').splitlines():
        linha = linha.strip()
        if not linha:
            continue
        nome = None
        if '|' in linha:
            partes = linha.split('|', 1)
            nome = partes[0].strip() or None
            numero_raw = partes[1].strip()
        else:
            numero_raw = linha
        numero_fmt = formatar_numero(numero_raw)
        if not numero_fmt or numero_fmt in seen:
            continue
        seen.add(numero_fmt)
        saida.append((numero_fmt, nome))
    return saida


def _renderizar_mensagem_envio(mensagem_template, link_publico, nome_destinatario=None):
    """Substitui placeholders na mensagem; se {LINK} ausente, anexa no fim."""
    texto = mensagem_template or ''
    if '{NOME}' in texto:
        texto = texto.replace('{NOME}', nome_destinatario or '')
    if '{LINK}' in texto:
        texto = texto.replace('{LINK}', link_publico)
    else:
        texto = (texto.rstrip() + '\n\n' + link_publico).strip()
    return texto




def _get_envio_do_usuario(envio_id):
    from flask import abort
    envio = EnvioPesquisa.query.get_or_404(envio_id)
    if envio.usuario_id != current_user.id and not current_user.is_admin:
        abort(403)
    return envio












# -----------------------------------------------------------------------------
# Pesquisa pública (formulário web acessado pelo paciente via link)
# -----------------------------------------------------------------------------



# =============================================================================
# ROTAS - TUTORIAL
# =============================================================================





# =============================================================================
# ROTAS - FOLLOW-UP (JOB)
# =============================================================================





# =============================================================================
# ROTAS - DASHBOARD DE SENTIMENTOS
# =============================================================================



# Logs







