"""
=============================================================================
CELERY TASKS
=============================================================================
Tasks assíncronas do sistema (migradas de threading para Celery)
"""

from celery_app import celery
from celery import Task
from celery.utils.log import get_task_logger
import time

logger = get_task_logger(__name__)


class DatabaseTask(Task):
    """Task base com gerenciamento automático de sessão do banco"""
    _db = None
    _flask_app = None

    @property
    def db(self):
        if self._db is None:
            # Import aqui para evitar circular dependency
            from app import db
            self._db = db
        return self._db

    @property
    def flask_app(self):
        if self._flask_app is None:
            # Import aqui para evitar circular dependency
            from app import app as flask_app
            self._flask_app = flask_app
        return self._flask_app

    def __call__(self, *args, **kwargs):
        """Executa task com context do Flask"""
        with self.flask_app.app_context():
            return super().__call__(*args, **kwargs)


@celery.task(
    base=DatabaseTask,
    bind=True,
    name='tasks.validar_campanha_task',
    max_retries=3,
    default_retry_delay=60,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=600,
    retry_jitter=True
)
def validar_campanha_task(self, campanha_id):
    """
    Valida números WhatsApp de uma campanha

    Args:
        campanha_id: ID da campanha

    Raises:
        Retry: Se houver erro temporário
    """
    from app import db, Campanha, Telefone, WhatsApp
    from datetime import datetime

    logger.info(f"Iniciando validação da campanha {campanha_id}")

    try:
        camp = db.session.get(Campanha, campanha_id)
        if not camp:
            logger.error(f"Campanha {campanha_id} não encontrada")
            return {'erro': 'Campanha não encontrada'}

        camp.status = 'validando'
        camp.status_msg = 'Validando numeros...'
        db.session.commit()

        ws = WhatsApp(camp.criador_id)
        if not ws.ok():
            camp.status = 'erro'
            camp.status_msg = 'WhatsApp nao configurado'
            db.session.commit()
            return {'erro': 'WhatsApp não configurado'}

        # Buscar telefones não validados
        telefones = Telefone.query.join(Telefone.contato).filter(
            Telefone.contato.has(campanha_id=camp.id),
            Telefone.whatsapp_valido == None
        ).all()

        total = len(telefones)
        validos = 0
        invalidos = 0

        logger.info(f"Total de telefones para validar: {total}")

        # Validar em lotes de 50
        batch_size = 50
        for i in range(0, total, batch_size):
            batch = telefones[i:i + batch_size]
            nums = [t.numero_fmt for t in batch]

            # Atualizar progresso
            progresso = int((i / total) * 100)
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': i,
                    'total': total,
                    'percent': progresso,
                    'status': f'Validando {i}/{total} números...'
                }
            )

            # Validar lote
            result = ws.verificar_numeros(nums)

            for t in batch:
                info = result.get(t.numero_fmt, {})
                t.whatsapp_valido = info.get('exists', False)
                t.jid = info.get('jid', '')
                t.data_validacao = datetime.utcnow()

                if t.whatsapp_valido:
                    validos += 1
                else:
                    invalidos += 1

            db.session.commit()
            time.sleep(1)  # Pausa entre lotes

        # Atualizar status dos contatos
        for c in camp.contatos.all():
            tem_valido = c.telefones.filter_by(whatsapp_valido=True).count() > 0
            if tem_valido:
                c.status = 'pronto_envio'
            else:
                c.status = 'sem_whatsapp'

        camp.status = 'validada'
        camp.status_msg = f'{validos} validos, {invalidos} invalidos'
        db.session.commit()

        logger.info(f"Validação concluída: {validos} válidos, {invalidos} inválidos")

        return {
            'sucesso': True,
            'total': total,
            'validos': validos,
            'invalidos': invalidos
        }

    except Exception as e:
        logger.exception(f"Erro na validação: {e}")
        camp.status = 'erro'
        camp.status_msg = str(e)[:200]
        db.session.commit()
        raise


@celery.task(
    base=DatabaseTask,
    bind=True,
    name='tasks.enviar_campanha_task',
    max_retries=5,
    default_retry_delay=120,
    autoretry_for=(Exception,),
    retry_backoff=True,
    retry_backoff_max=1800,
    retry_jitter=True,
    time_limit=7200,  # 2 horas máximo
    soft_time_limit=7000
)
def enviar_campanha_task(self, campanha_id):
    """
    Envia mensagens WhatsApp de uma campanha

    Args:
        campanha_id: ID da campanha

    Raises:
        Retry: Se houver erro temporário (API indisponível, etc)
    """
    from app import db, Campanha, Contato, Telefone, LogMsg, WhatsApp
    from datetime import datetime

    logger.info(f"Iniciando envio da campanha {campanha_id}")

    try:
        camp = db.session.get(Campanha, campanha_id)
        if not camp:
            logger.error(f"Campanha {campanha_id} não encontrada")
            return {'erro': 'Campanha não encontrada'}

        ws = WhatsApp(camp.criador_id)
        if not ws.ok():
            camp.status = 'erro'
            camp.status_msg = 'WhatsApp nao configurado'
            db.session.commit()
            return {'erro': 'WhatsApp não configurado'}

        conn, _ = ws.conectado()
        if not conn:
            camp.status = 'erro'
            camp.status_msg = 'WhatsApp desconectado'
            db.session.commit()
            return {'erro': 'WhatsApp desconectado'}

        camp.status = 'em_andamento'
        camp.data_inicio = datetime.utcnow()
        db.session.commit()

        # Buscar contatos pendentes ou prontos
        contatos = camp.contatos.filter(
            Contato.status.in_(['pendente', 'pronto_envio'])
        ).order_by(Contato.status.desc(), Contato.id).all()

        total = len(contatos)
        enviados_pessoas = 0
        erros = 0

        logger.info(f"Total de contatos para enviar: {total}")

        for i, c in enumerate(contatos):
            # Refresh campanha para verificar status
            db.session.refresh(camp)
            if camp.status != 'em_andamento':
                logger.info(f"Campanha pausada/cancelada, parando...")
                break

            # Verificar limites
            if camp.atingiu_duracao():
                camp.status = 'concluida'
                camp.status_msg = f'Duração de {camp.dias_duracao} dias atingida'
                db.session.commit()
                break

            if not camp.pode_enviar_agora():
                camp.status = 'pausada'
                camp.status_msg = f'Fora do horário ({camp.hora_inicio}h-{camp.hora_fim}h)'
                db.session.commit()
                break

            if not camp.pode_enviar_hoje():
                camp.status = 'pausada'
                camp.status_msg = f'Meta diária atingida ({camp.meta_diaria} pessoas)'
                db.session.commit()
                break

            # Atualizar progresso
            progresso = int((i / total) * 100)
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': i + 1,
                    'total': total,
                    'percent': progresso,
                    'enviados': enviados_pessoas,
                    'erros': erros,
                    'status': f'Enviando para {c.nome}...'
                }
            )

            camp.status_msg = f'Processando {i+1}/{total}: {c.nome}'
            db.session.commit()

            # Validação JIT se necessário
            if c.status == 'pendente':
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

                    if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                        c.status = 'pronto_envio'
                    else:
                        c.status = 'sem_whatsapp'
                        db.session.commit()
                        continue
                else:
                    if c.telefones.filter_by(whatsapp_valido=True).count() > 0:
                        c.status = 'pronto_envio'
                    else:
                        c.status = 'sem_whatsapp'
                        db.session.commit()
                        continue

            # Envio
            if c.status == 'pronto_envio':
                procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
                msg = camp.mensagem.replace('{nome}', c.nome).replace('{procedimento}', procedimento_msg)

                telefones_validos = c.telefones.filter_by(whatsapp_valido=True).all()
                sucesso_pessoa = False

                for t in telefones_validos:
                    ok, result = ws.enviar(t.numero_fmt, msg)

                    if ok:
                        t.enviado = True
                        t.data_envio = datetime.utcnow()
                        t.msg_id = result
                        sucesso_pessoa = True

                        log = LogMsg(
                            campanha_id=camp.id,
                            contato_id=c.id,
                            direcao='enviada',
                            telefone=t.numero_fmt,
                            mensagem=msg[:500],
                            status='ok'
                        )
                        db.session.add(log)
                    else:
                        log = LogMsg(
                            campanha_id=camp.id,
                            contato_id=c.id,
                            direcao='enviada',
                            telefone=t.numero_fmt,
                            mensagem=msg[:500],
                            status='erro',
                            erro=result
                        )
                        db.session.add(log)

                if sucesso_pessoa:
                    c.status = 'enviado'
                    camp.registrar_envio()
                    enviados_pessoas += 1
                else:
                    erros += 1

                db.session.commit()
                camp.atualizar_stats()
                db.session.commit()

                # Aguardar intervalo calculado
                if i < total - 1:
                    intervalo = camp.calcular_intervalo()
                    logger.info(f"Aguardando {intervalo}s até próximo envio")
                    time.sleep(intervalo)

        # Verificar se acabou
        restantes = camp.contatos.filter(
            Contato.status.in_(['pendente', 'pronto_envio'])
        ).count()

        if restantes == 0 and camp.status == 'em_andamento':
            camp.status = 'concluida'
            camp.data_fim = datetime.utcnow()
            camp.status_msg = f'{enviados_pessoas} pessoas contactadas'

        camp.atualizar_stats()
        db.session.commit()

        logger.info(f"Envio concluído: {enviados_pessoas} enviados, {erros} erros")

        return {
            'sucesso': True,
            'total': total,
            'enviados': enviados_pessoas,
            'erros': erros
        }

    except Exception as e:
        logger.exception(f"Erro no envio: {e}")
        camp.status = 'erro'
        camp.status_msg = str(e)[:200]
        db.session.commit()
        raise


@celery.task(
    base=DatabaseTask,
    bind=True,
    name='tasks.follow_up_automatico_task'
)
def follow_up_automatico_task(self):
    """
    Task periódica para enviar follow-ups automáticos
    Executada diariamente às 9h via Celery Beat
    """
    from app import db, Contato, Telefone, ConfigTentativas, TentativaContato, LogMsg, WhatsApp
    from datetime import datetime, timedelta

    logger.info("Iniciando follow-up automático")

    try:
        config = ConfigTentativas.query.first()
        if not config or not config.ativo:
            logger.info("Follow-up automático desativado")
            return {'sucesso': False, 'motivo': 'Desativado'}

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
            # Criar WhatsApp instance para o criador da campanha
            if not c.campanha or not c.campanha.criador_id:
                logger.warning(f"Contato {c.id} sem campanha ou criador válido")
                continue

            ws = WhatsApp(c.campanha.criador_id)
            if not ws.ok():
                logger.error(f"WhatsApp não configurado para usuário {c.campanha.criador_id}")
                continue

            # Verificar última tentativa
            ultima_tentativa = TentativaContato.query.filter_by(
                contato_id=c.id
            ).order_by(TentativaContato.numero_tentativa.desc()).first()

            primeiro_envio = c.telefones.filter(Telefone.enviado == True).order_by(Telefone.data_envio).first()

            if not ultima_tentativa:
                if primeiro_envio and primeiro_envio.data_envio < data_limite:
                    num_tentativa = 1
                else:
                    continue
            else:
                if ultima_tentativa.numero_tentativa >= config.max_tentativas:
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

            telefones = c.telefones.filter_by(whatsapp_valido=True).all()
            enviado = False

            for t in telefones:
                ok, _ = ws.enviar(t.numero_fmt, msg)
                if ok:
                    enviado = True

                    tentativa = TentativaContato(
                        contato_id=c.id,
                        numero_tentativa=num_tentativa,
                        data_tentativa=datetime.utcnow(),
                        proxima_tentativa=datetime.utcnow() + timedelta(days=config.intervalo_dias),
                        status='enviada',
                        mensagem_enviada=msg
                    )
                    db.session.add(tentativa)

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
                processados += 1

            db.session.commit()
            time.sleep(2)  # Pausa entre envios

        logger.info(f"Follow-up automático concluído: {processados} mensagens enviadas")

        return {
            'sucesso': True,
            'total_verificados': len(contatos),
            'processados': processados
        }

    except Exception as e:
        logger.exception(f"Erro no follow-up automático: {e}")
        raise


@celery.task(
    base=DatabaseTask,
    name='tasks.limpar_tasks_antigas'
)
def limpar_tasks_antigas():
    """
    Limpa resultados de tasks antigas do Redis
    Executada a cada 6 horas
    """
    from celery.result import AsyncResult
    from datetime import datetime, timedelta

    logger.info("Limpando tasks antigas do Redis")

    # Limpar tasks mais antigas que 24 horas
    # Esta é uma operação leve que o Celery faz automaticamente
    # através do result_expires no celery_app.py

    return {'sucesso': True, 'limpeza': 'automática via result_expires'}


@celery.task(
    base=DatabaseTask,
    bind=True,
    name='tasks.processar_planilha_task',
    max_retries=2,
    default_retry_delay=30,
    time_limit=1800,  # 30 minutos máximo
    soft_time_limit=1700
)
def processar_planilha_task(self, arquivo_path, campanha_id):
    """
    Processa planilha Excel de forma assíncrona com feedback de progresso

    Args:
        arquivo_path: Caminho do arquivo Excel
        campanha_id: ID da campanha

    Returns:
        dict: Resultado do processamento
    """
    from app import db, Campanha, Contato, Telefone, DeepSeekAI
    from datetime import datetime
    import pandas as pd

    logger.info(f"Processando planilha para campanha {campanha_id}")

    try:
        # Atualizar status inicial
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 0,
                'total': 100,
                'percent': 0,
                'status': 'Lendo arquivo Excel...'
            }
        )

        # Carregar campanha
        camp = db.session.get(Campanha, campanha_id)
        if not camp:
            return {'sucesso': False, 'erro': 'Campanha não encontrada'}

        camp.status = 'processando'
        camp.status_msg = 'Lendo planilha...'
        db.session.commit()

        # Ler Excel
        df = pd.read_excel(arquivo_path)
        if df.empty:
            camp.status = 'erro'
            camp.status_msg = 'Planilha vazia'
            db.session.commit()
            return {'sucesso': False, 'erro': 'Planilha vazia'}

        self.update_state(
            state='PROGRESS',
            meta={
                'current': 10,
                'total': 100,
                'percent': 10,
                'status': f'Processando {len(df)} linhas...'
            }
        )

        # Normalizar colunas
        df.columns = [str(c).strip().lower() for c in df.columns]

        # Identificar colunas
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
            camp.status = 'erro'
            camp.status_msg = f"Colunas obrigatórias não encontradas"
            db.session.commit()
            return {'sucesso': False, 'erro': f"Colunas obrigatórias não encontradas. Disponíveis: {list(df.columns)}"}

        # Agrupar por pessoa
        pessoas = {}
        total_linhas = len(df)

        for idx, row in df.iterrows():
            # Atualizar progresso
            if idx % 10 == 0:
                progresso = 10 + int((idx / total_linhas) * 20)  # 10-30%
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': idx,
                        'total': total_linhas,
                        'percent': progresso,
                        'status': f'Processando linha {idx+1}/{total_linhas}...'
                    }
                )

            nome = str(row.get(col_nome, '')).strip()
            if not nome or nome.lower() == 'nan':
                continue

            # Data nascimento
            dt_nasc = None
            dt_nasc_str = ''
            if col_nasc:
                val = row.get(col_nasc)
                if pd.notna(val):
                    try:
                        if isinstance(val, datetime):
                            dt_nasc = val.date()
                        else:
                            dt_nasc = pd.to_datetime(val, dayfirst=True).date()
                        dt_nasc_str = dt_nasc.isoformat()
                    except:
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
                    # Formatar número
                    num = ''.join(filter(str.isdigit, str(tel))).lstrip('0')
                    if num:
                        if num.startswith('55'):
                            fmt = num if len(num) in [12, 13] else None
                        elif len(num) in [10, 11]:
                            fmt = '55' + num
                        else:
                            fmt = None

                        if fmt:
                            pessoas[chave]['telefones'].add((tel, fmt))

        # Normalizar procedimentos
        procedimentos_unicos = set()
        for dados in pessoas.values():
            if dados['procedimento']:
                procedimentos_unicos.add(dados['procedimento'])

        self.update_state(
            state='PROGRESS',
            meta={
                'current': 30,
                'total': 100,
                'percent': 30,
                'status': f'Normalizando {len(procedimentos_unicos)} procedimentos...'
            }
        )

        camp.status_msg = f'Normalizando procedimentos...'
        db.session.commit()

        ai = DeepSeekAI()
        mapa_normalizacao = {}

        for idx, proc_original in enumerate(procedimentos_unicos, 1):
            # Atualizar progresso
            progresso = 30 + int((idx / len(procedimentos_unicos)) * 40)  # 30-70%
            self.update_state(
                state='PROGRESS',
                meta={
                    'current': idx,
                    'total': len(procedimentos_unicos),
                    'percent': progresso,
                    'status': f'Normalizando procedimento {idx}/{len(procedimentos_unicos)}: {proc_original[:50]}...'
                }
            )

            resultado = ai.normalizar_procedimento(proc_original)
            if resultado:
                # Usar termo SIMPLES para melhor compreensão do paciente
                mapa_normalizacao[proc_original] = resultado['simples']
                logger.info(f"[{idx}/{len(procedimentos_unicos)}] Normalizado: '{proc_original}' -> '{resultado['simples']}' (fonte: {resultado['fonte']})")
            else:
                mapa_normalizacao[proc_original] = proc_original
                logger.info(f"[{idx}/{len(procedimentos_unicos)}] Mantido original: '{proc_original}'")

        # Salvar contatos no banco
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 70,
                'total': 100,
                'percent': 70,
                'status': 'Salvando contatos no banco de dados...'
            }
        )

        camp.status_msg = 'Salvando contatos...'
        db.session.commit()

        criados = 0
        total_pessoas = len(pessoas)

        for idx, (chave, dados) in enumerate(pessoas.items(), 1):
            if not dados['telefones']:
                continue

            # Atualizar progresso
            if idx % 10 == 0:
                progresso = 70 + int((idx / total_pessoas) * 25)  # 70-95%
                self.update_state(
                    state='PROGRESS',
                    meta={
                        'current': idx,
                        'total': total_pessoas,
                        'percent': progresso,
                        'status': f'Salvando contato {idx}/{total_pessoas}: {dados["nome"][:30]}...'
                    }
                )

            # Obter procedimento normalizado
            proc_original = dados['procedimento']
            proc_normalizado = mapa_normalizacao.get(proc_original, proc_original)

            c = Contato(
                campanha_id=campanha_id,
                nome=dados['nome'][:200],
                data_nascimento=dados['nascimento'],
                procedimento=proc_original[:500],
                procedimento_normalizado=proc_normalizado[:300],
                status='pendente'
            )
            db.session.add(c)
            db.session.flush()

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

        # Atualizar estatísticas
        self.update_state(
            state='PROGRESS',
            meta={
                'current': 95,
                'total': 100,
                'percent': 95,
                'status': 'Atualizando estatísticas...'
            }
        )

        camp.atualizar_stats()
        camp.status = 'pronta'
        camp.status_msg = f'{criados} contatos importados'
        db.session.commit()

        logger.info(f"Planilha processada com sucesso: {criados} contatos criados")

        # Limpar arquivo temporário
        import os
        if os.path.exists(arquivo_path):
            try:
                os.remove(arquivo_path)
                logger.info(f"Arquivo temporário removido: {arquivo_path}")
            except Exception as e:
                logger.warning(f"Erro ao remover arquivo temporário: {e}")

        return {
            'sucesso': True,
            'criados': criados,
            'campanha_id': campanha_id,
            'procedimentos_normalizados': len(mapa_normalizacao)
        }

    except Exception as e:
        logger.exception(f"Erro ao processar planilha: {e}")
        camp = db.session.get(Campanha, campanha_id)
        if camp:
            camp.status = 'erro'
            camp.status_msg = str(e)[:200]
            db.session.commit()

        # Limpar arquivo temporário mesmo em caso de erro
        import os
        if os.path.exists(arquivo_path):
            try:
                os.remove(arquivo_path)
                logger.info(f"Arquivo temporário removido após erro: {arquivo_path}")
            except Exception as e2:
                logger.warning(f"Erro ao remover arquivo temporário: {e2}")

        raise
