"""Evolution-API receive endpoint."""

import threading
from datetime import datetime, timedelta

from flask import Blueprint, current_app, jsonify, request

from app.extensions import csrf, db
from app.main import (
    MENSAGEM_PADRAO, RESPOSTAS_DESCONHECO, RESPOSTAS_NAO,
    RESPOSTAS_SIM, AnaliseSentimento, DeepSeekAI, SistemaFAQ,
    logger, verificar_resposta_em_lista,
)
from app.models import (
    AgendamentoConsulta, Campanha, CampanhaConsulta,
    ComprovanteAntecipado, ConfigWhatsApp, Contato,
    LogMsg, LogMsgConsulta, PesquisaSatisfacao, RespostaAutomatica,
    Telefone, TelefoneConsulta, TicketAtendimento, Usuario,
    buscar_comprovante_antecipado,
)
from app.services.mensagem import (
    enviar_e_registrar_consulta,
    formatar_data_consulta,
    formatar_mensagem_cancelamento_sem_resposta,
    formatar_mensagem_comprovante,
    formatar_mensagem_confirmacao_rejeicao,
    formatar_mensagem_consulta_inicial,
    formatar_mensagem_interconsulta_aprovada,
    formatar_mensagem_perguntar_motivo,
    formatar_mensagem_voltar_posto,
)
from app.services.telefone import formatar_numero
from app.services.timezone import obter_agora_fortaleza
from app.services.whatsapp import WhatsApp


bp = Blueprint('webhook', __name__)


@bp.route('/receive/whatsapp', methods=['POST'])
@csrf.exempt
def receive():
    try:
        data = request.get_json()
        if not data:
            return jsonify({'status': 'ok'}), 200

        # Log do evento recebido (útil para debug)
        logger.debug(f"Webhook evento recebido: {data.get('event')}")

        # Normalizar nome do evento (aceita MESSAGES_UPSERT ou messages.upsert)
        event = data.get('event', '').upper().replace('.', '_')
        if event != 'MESSAGES_UPSERT':
            logger.debug(f"Evento ignorado: {event}")
            return jsonify({'status': 'ok'}), 200

        # CRÍTICO: Extrair nome da instância para filtrar por usuário
        # Isso evita que respostas sejam processadas no contexto errado quando
        # múltiplos usuários (com WhatsApps diferentes) contactam o mesmo paciente
        instance_name = data.get('instance')
        if not instance_name:
            logger.warning("Webhook sem informação de instância - ignorando por segurança")
            return jsonify({'status': 'ok'}), 200

        # Buscar usuário dono desta instância
        config_usuario = ConfigWhatsApp.query.filter_by(instance_name=instance_name).first()
        if not config_usuario:
            logger.warning(f"Instância {instance_name} não encontrada no sistema")
            return jsonify({'status': 'ok'}), 200

        usuario_id = config_usuario.usuario_id
        logger.debug(f"Webhook da instância {instance_name} (usuário ID: {usuario_id})")

        msg_data = data.get('data', {})
        key = msg_data.get('key', {})
        if key.get('fromMe'):
            return jsonify({'status': 'ok'}), 200

        # Extrair o número real do WhatsApp
        # O número correto sempre termina com @s.whatsapp.net
        # O LID (Local ID) termina com @lid e deve ser ignorado
        remote_jid = key.get('remoteJid', '')
        remote_jid_alt = key.get('remoteJidAlt', '')

        # Priorizar o JID que termina com @s.whatsapp.net (número real)
        if remote_jid.endswith('@s.whatsapp.net'):
            jid = remote_jid
        elif remote_jid_alt.endswith('@s.whatsapp.net'):
            jid = remote_jid_alt
        else:
            # Fallback: se nenhum termina com @s.whatsapp.net, usa o que não é LID
            if not remote_jid.endswith('@lid'):
                jid = remote_jid
            elif not remote_jid_alt.endswith('@lid'):
                jid = remote_jid_alt
            else:
                jid = remote_jid  # Último recurso

        numero = ''.join(filter(str.isdigit, jid.replace('@s.whatsapp.net', '').replace('@lid', '')))

        # Validar se conseguiu extrair um numero valido
        if not numero:
            logger.warning(f"Webhook: Numero de telefone invalido ou vazio. JID: {jid}")
            return jsonify({'status': 'ok'}), 200

        message = msg_data.get('message', {})
        texto = (message.get('conversation') or message.get('extendedTextMessage', {}).get('text') or '').strip()

        if not texto:
            return jsonify({'status': 'ok'}), 200

        texto_up = texto.upper()

        # =====================================================================
        # PROTEÇÃO GLOBAL: Evitar duplicação quando mesmo telefone está em múltiplos usuários
        # =====================================================================
        # Buscar TODAS as variações do número
        numeros_buscar = [numero]
        if len(numero) == 12:
            numeros_buscar.append(numero[:4] + '9' + numero[4:])  # Com 9º dígito
        elif len(numero) == 13:
            numeros_buscar.append(numero[:4] + numero[5:])  # Sem 9º dígito

        # Verificar se esta mensagem já foi processada por OUTRO receive (outro usuário)
        from datetime import timedelta
        cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)

        # Buscar log global por telefone (qualquer consulta)
        log_global_consulta = LogMsgConsulta.query.filter(
            LogMsgConsulta.telefone.in_(numeros_buscar),
            LogMsgConsulta.direcao == 'recebida',
            LogMsgConsulta.mensagem == texto[:500],
            LogMsgConsulta.data >= cinco_segundos_atras
        ).first()

        if log_global_consulta:
            logger.debug(f"Webhook: Mensagem já processada por outro receive de consulta. Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # Buscar log global por telefone (qualquer cirurgia/fila)
        log_global_fila = LogMsg.query.filter(
            LogMsg.telefone.in_(numeros_buscar),
            LogMsg.direcao == 'recebida',
            LogMsg.mensagem == texto[:500],
            LogMsg.data >= cinco_segundos_atras
        ).first()

        if log_global_fila:
            logger.debug(f"Webhook: Mensagem já processada por outro receive de fila. Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # DETECÇÃO DE MÚLTIPLAS PENDÊNCIAS (Consultas + Cirurgias)
        # =====================================================================
        # Se é resposta de confirmação (1, SIM, etc), verificar se tem múltiplas pendências
        resposta_confirmacao = verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM)
        resposta_rejeicao = verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO)

        if resposta_confirmacao or resposta_rejeicao:
            # Só consideramos pendências do MESMO usuário/instância e cuja mensagem
            # de confirmação foi enviada nas últimas 24h (consultas mais antigas
            # não são fluxo ativo, mesmo que tenham ficado em AGUARDANDO_CONFIRMACAO).
            vinte_quatro_horas_atras = datetime.utcnow() - timedelta(hours=24)

            consultas_pendentes = []
            for num in numeros_buscar:
                tels = TelefoneConsulta.query.filter_by(numero=num).all()
                for tel in tels:
                    consulta = tel.consulta
                    if not consulta or consulta.status != 'AGUARDANDO_CONFIRMACAO':
                        continue
                    if not consulta.campanha or consulta.campanha.criador_id != usuario_id:
                        continue
                    if not consulta.data_envio_mensagem or consulta.data_envio_mensagem < vinte_quatro_horas_atras:
                        continue
                    consultas_pendentes.append(consulta)

            cirurgias_pendentes = []
            for num in numeros_buscar:
                tels_fila = Telefone.query.filter_by(numero_fmt=num).all()
                for tel in tels_fila:
                    contato = tel.contato
                    if not contato or contato.status not in ['enviado', 'pronto_envio']:
                        continue
                    if not contato.campanha or contato.campanha.criador_id != usuario_id:
                        continue
                    cirurgias_pendentes.append(contato)

            # Remover duplicados (mesmo ID)
            consultas_pendentes = list({c.id: c for c in consultas_pendentes}.values())
            cirurgias_pendentes = list({c.id: c for c in cirurgias_pendentes}.values())

            total_pendencias = len(consultas_pendentes) + len(cirurgias_pendentes)

            # Se tem múltiplas pendências E a resposta é de confirmação/rejeição
            if total_pendencias > 1:
                # Verificar se já enviamos menu nos últimos 2 minutos
                dois_minutos_atras = datetime.utcnow() - timedelta(minutes=2)
                menu_enviado = LogMsgConsulta.query.filter(
                    LogMsgConsulta.telefone.in_(numeros_buscar),
                    LogMsgConsulta.direcao == 'enviada',
                    LogMsgConsulta.mensagem.like('%Qual agendamento%'),
                    LogMsgConsulta.data >= dois_minutos_atras
                ).first()

                if not menu_enviado:
                    # Também verificar na tabela de logs da fila
                    menu_enviado = LogMsg.query.filter(
                        LogMsg.telefone.in_(numeros_buscar),
                        LogMsg.direcao == 'enviada',
                        LogMsg.mensagem.like('%Qual agendamento%'),
                        LogMsg.data >= dois_minutos_atras
                    ).first()

                if not menu_enviado:
                    # Enviar menu de escolha
                    ws = WhatsApp(usuario_id)

                    menu_texto = "📋 *Você tem múltiplos agendamentos pendentes:*\n\n"
                    opcao = 1

                    # Ordenar por data (mais próxima primeiro)
                    for consulta in sorted(consultas_pendentes, key=lambda c: c.data_aghu or ''):
                        data_str = formatar_data_consulta(consulta.data_aghu) if consulta.data_aghu else 'Data não informada'
                        menu_texto += f"{opcao}️⃣ *CONSULTA* - {consulta.especialidade or 'Especialidade'}\n"
                        menu_texto += f"   📅 {data_str}\n"
                        menu_texto += f"   👨‍⚕️ {consulta.medico_solicitante or consulta.grade_aghu or 'Médico não informado'}\n\n"
                        opcao += 1

                    for cirurgia in cirurgias_pendentes:
                        proc = cirurgia.procedimento_normalizado or cirurgia.procedimento or 'Procedimento'
                        menu_texto += f"{opcao}️⃣ *CIRURGIA* - {proc}\n"
                        menu_texto += f"   📅 Fila cirúrgica\n\n"
                        opcao += 1

                    menu_texto += f"*Qual agendamento deseja {'confirmar' if resposta_confirmacao else 'recusar'}?*\n"
                    menu_texto += f"Responda com o número (1 a {total_pendencias}) ou *TODOS* para confirmar todos."

                    ws.enviar(numero, menu_texto)

                    # Registrar que enviamos o menu (para não enviar de novo)
                    if consultas_pendentes:
                        log = LogMsgConsulta(
                            campanha_id=consultas_pendentes[0].campanha_id,
                            consulta_id=consultas_pendentes[0].id,
                            direcao='enviada',
                            telefone=numero,
                            mensagem=menu_texto[:500],
                            status='sucesso'
                        )
                        db.session.add(log)
                    elif cirurgias_pendentes:
                        log = LogMsg(
                            campanha_id=cirurgias_pendentes[0].campanha_id,
                            contato_id=cirurgias_pendentes[0].id,
                            direcao='enviada',
                            telefone=numero,
                            mensagem=menu_texto[:500],
                            status='ok'
                        )
                        db.session.add(log)

                    db.session.commit()
                    logger.info(f"Menu de múltiplas pendências enviado para {numero} ({total_pendencias} pendências)")
                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # PROCESSAR RESPOSTA DO MENU DE MÚLTIPLAS PENDÊNCIAS
        # =====================================================================
        # Verificar se paciente recebeu menu recentemente e está respondendo
        dois_minutos_atras = datetime.utcnow() - timedelta(minutes=2)

        # Verificar se existe menu enviado recentemente
        menu_recente_consulta = LogMsgConsulta.query.filter(
            LogMsgConsulta.telefone.in_(numeros_buscar),
            LogMsgConsulta.direcao == 'enviada',
            LogMsgConsulta.mensagem.like('%Qual agendamento%'),
            LogMsgConsulta.data >= dois_minutos_atras
        ).first()

        menu_recente_fila = None
        if not menu_recente_consulta:
            menu_recente_fila = LogMsg.query.filter(
                LogMsg.telefone.in_(numeros_buscar),
                LogMsg.direcao == 'enviada',
                LogMsg.mensagem.like('%Qual agendamento%'),
                LogMsg.data >= dois_minutos_atras
            ).first()

        if menu_recente_consulta or menu_recente_fila:
            # Paciente está respondendo ao menu - processar escolha
            escolha = texto_up.strip()

            # Buscar novamente as pendências (podem ter mudado).
            # Mesmos filtros do bloco que envia o menu: usuário da instância +
            # mensagem enviada nas últimas 24h.
            vinte_quatro_horas_atras = datetime.utcnow() - timedelta(hours=24)

            consultas_pendentes = []
            for num in numeros_buscar:
                tels = TelefoneConsulta.query.filter_by(numero=num).all()
                for tel in tels:
                    consulta = tel.consulta
                    if not consulta or consulta.status != 'AGUARDANDO_CONFIRMACAO':
                        continue
                    if not consulta.campanha or consulta.campanha.criador_id != usuario_id:
                        continue
                    if not consulta.data_envio_mensagem or consulta.data_envio_mensagem < vinte_quatro_horas_atras:
                        continue
                    consultas_pendentes.append((consulta, tel.numero))

            cirurgias_pendentes = []
            for num in numeros_buscar:
                tels_fila = Telefone.query.filter_by(numero_fmt=num).all()
                for tel in tels_fila:
                    contato = tel.contato
                    if not contato or contato.status not in ['enviado', 'pronto_envio']:
                        continue
                    if not contato.campanha or contato.campanha.criador_id != usuario_id:
                        continue
                    cirurgias_pendentes.append((contato, tel.numero_fmt))

            # Remover duplicados
            consultas_pendentes = list({c[0].id: c for c in consultas_pendentes}.values())
            cirurgias_pendentes = list({c[0].id: c for c in cirurgias_pendentes}.values())

            # Ordenar igual ao menu
            consultas_pendentes = sorted(consultas_pendentes, key=lambda c: c[0].data_aghu or '')

            todas_pendencias = consultas_pendentes + cirurgias_pendentes

            if escolha == 'TODOS' or escolha == 'TODAS':
                # Confirmar/rejeitar TODAS as pendências
                ws = WhatsApp(usuario_id)
                confirmados = 0

                for item, tel_numero in todas_pendencias:
                    if hasattr(item, 'campanha_id') and hasattr(item, 'paciente'):
                        # É uma consulta
                        item.status = 'AGUARDANDO_COMPROVANTE'
                        item.data_confirmacao = datetime.utcnow()
                        item.telefone_confirmacao = tel_numero
                        db.session.commit()
                        item.campanha.atualizar_stats()
                        confirmados += 1

                        # [COMPROVANTE ANTECIPADO] Verificar se existe arquivo pré-carregado
                        comp_ant_todos = buscar_comprovante_antecipado(item.campanha_id, item.paciente)
                        if comp_ant_todos:
                            try:
                                from sqlalchemy import update as sa_update
                                rows_todos = db.session.execute(
                                    sa_update(ComprovanteAntecipado)
                                    .where(ComprovanteAntecipado.id == comp_ant_todos.id, ComprovanteAntecipado.usado == False)
                                    .values(usado=True, consulta_id=item.id)
                                ).rowcount
                                db.session.commit()
                                if rows_todos > 0:
                                    db.session.refresh(comp_ant_todos)
                                    item.comprovante_path = comp_ant_todos.filepath
                                    item.comprovante_nome = comp_ant_todos.filename
                                    item.status = 'CONFIRMADO'
                                    db.session.commit()
                                    item.campanha.atualizar_stats()
                                    db.session.commit()
                                    send_fn_todos = current_app.extensions.get('enviar_comprovante_background')
                                    if send_fn_todos:
                                        base_url_todos = request.host_url.rstrip('/')
                                        threading.Thread(
                                            target=send_fn_todos,
                                            args=(item.campanha.criador_id, item.id, comp_ant_todos.filepath, tel_numero, base_url_todos),
                                            daemon=True
                                        ).start()
                            except Exception as e_todos:
                                logger.error(f"[AUTO] Erro ao processar comprovante antecipado (TODOS) para {item.paciente}: {e_todos}")
                    else:
                        # É uma cirurgia - iniciar fluxo de data de nascimento
                        item.status = 'aguardando_nascimento'
                        item.resposta = '1'
                        item.data_resposta = datetime.utcnow()
                        confirmados += 1

                db.session.commit()

                if confirmados > 0:
                    ws.enviar(numero, f"✅ *{confirmados} agendamento(s) confirmado(s)!*\n\nAguarde o envio dos comprovantes.")
                    logger.info(f"Múltiplas pendências confirmadas para {numero}: {confirmados} itens")

                return jsonify({'status': 'ok'}), 200

            elif escolha.isdigit():
                opcao_num = int(escolha)
                if 1 <= opcao_num <= len(todas_pendencias):
                    item, tel_numero = todas_pendencias[opcao_num - 1]
                    ws = WhatsApp(usuario_id)

                    if hasattr(item, 'campanha_id') and hasattr(item, 'paciente'):
                        # É uma consulta
                        item.status = 'AGUARDANDO_COMPROVANTE'
                        item.data_confirmacao = datetime.utcnow()
                        item.telefone_confirmacao = tel_numero
                        db.session.commit()
                        item.campanha.atualizar_stats()
                        db.session.commit()

                        # [COMPROVANTE ANTECIPADO] Verificar se existe arquivo pré-carregado
                        comp_ant_menu = buscar_comprovante_antecipado(item.campanha_id, item.paciente)
                        if comp_ant_menu:
                            try:
                                from sqlalchemy import update as sa_update
                                rows_menu = db.session.execute(
                                    sa_update(ComprovanteAntecipado)
                                    .where(ComprovanteAntecipado.id == comp_ant_menu.id, ComprovanteAntecipado.usado == False)
                                    .values(usado=True, consulta_id=item.id)
                                ).rowcount
                                db.session.commit()
                                if rows_menu > 0:
                                    db.session.refresh(comp_ant_menu)
                                    item.comprovante_path = comp_ant_menu.filepath
                                    item.comprovante_nome = comp_ant_menu.filename
                                    item.status = 'CONFIRMADO'
                                    db.session.commit()
                                    item.campanha.atualizar_stats()
                                    db.session.commit()
                                    send_fn_menu = current_app.extensions.get('enviar_comprovante_background')
                                    if send_fn_menu:
                                        base_url_menu = request.host_url.rstrip('/')
                                        threading.Thread(
                                            target=send_fn_menu,
                                            args=(item.campanha.criador_id, item.id, comp_ant_menu.filepath, tel_numero, base_url_menu),
                                            daemon=True
                                        ).start()
                            except Exception as e_menu:
                                logger.error(f"[AUTO] Erro ao processar comprovante antecipado (menu) para {item.paciente}: {e_menu}")

                        ws.enviar(numero, f"✅ *Consulta confirmada!*\n\n📅 {formatar_data_consulta(item.data_aghu) if item.data_aghu else 'Data não informada'}\n👨‍⚕️ {item.especialidade or 'Especialidade'}\n\nAguarde o envio do comprovante.")
                        logger.info(f"Consulta {item.id} confirmada via menu por {item.paciente}")

                        # Log da mensagem recebida
                        log = LogMsgConsulta(
                            campanha_id=item.campanha_id,
                            consulta_id=item.id,
                            direcao='recebida',
                            telefone=numero,
                            mensagem=texto[:500],
                            status='sucesso'
                        )
                        db.session.add(log)
                        db.session.commit()

                    else:
                        # É uma cirurgia - iniciar fluxo de data de nascimento
                        item.status = 'aguardando_nascimento'
                        item.resposta = '1'
                        item.data_resposta = datetime.utcnow()
                        db.session.commit()

                        ws.enviar(numero, "🔒 Por segurança, por favor digite sua *Data de Nascimento* (ex: 03/09/1954).")
                        logger.info(f"Cirurgia selecionada via menu para {item.nome}, aguardando nascimento")

                        # Log da mensagem recebida
                        log = LogMsg(
                            campanha_id=item.campanha_id,
                            contato_id=item.id,
                            direcao='recebida',
                            telefone=numero,
                            mensagem=texto[:500],
                            status='ok'
                        )
                        db.session.add(log)
                        db.session.commit()

                    # Verificar se ainda há outras pendências
                    pendencias_restantes = len(todas_pendencias) - 1
                    if pendencias_restantes > 0:
                        ws.enviar(numero, f"📋 Você ainda tem *{pendencias_restantes}* agendamento(s) pendente(s). Responda *1* para confirmar ou *2* para recusar.")

                    return jsonify({'status': 'ok'}), 200

                else:
                    # Número inválido
                    ws = WhatsApp(usuario_id)
                    ws.enviar(numero, f"❌ Opção inválida. Por favor, responda com um número de 1 a {len(todas_pendencias)} ou *TODOS*.")
                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # MODO CONSULTA - Processar PRIMEIRO (tem prioridade)
        # =====================================================================
        # Verificar se é uma resposta de consulta ANTES de processar fila cirúrgica
        # Isso garante que ambos os sistemas (Consultas e Fila) funcionem independentemente
        # Busca por telefone do usuário correto (mesmo filtro de instância)
        # IMPORTANTE: Tentar variações do número (com/sem 9º dígito)
        consulta_telefones = TelefoneConsulta.query.filter_by(numero=numero).all()

        if not consulta_telefones:
            # Tenta variação 9º dígito (mesmo código usado para fila cirúrgica)
            if len(numero) == 12:
                # Número sem 9, tentar com 9
                num9 = numero[:4] + '9' + numero[4:]
                consulta_telefones = TelefoneConsulta.query.filter_by(numero=num9).all()
            elif len(numero) == 13:
                # Número com 9, tentar sem 9
                num_sem9 = numero[:4] + numero[5:]
                consulta_telefones = TelefoneConsulta.query.filter_by(numero=num_sem9).all()

        # Priorizar consulta mais apropriada quando há múltiplas consultas do mesmo telefone
        # PRIORIDADE:
        # 1. Consultas do usuário correto (filtro de instância)
        # 2. Consultas em fluxo ativo (AGUARDANDO_CONFIRMACAO, AGUARDANDO_MOTIVO_REJEICAO)
        # 3. Consultas da campanha mais recente (maior ID de campanha)
        # 4. Consultas mais recentes (maior ID de consulta)
        consulta_telefone = None
        if consulta_telefones:
            # Filtrar apenas consultas do usuário correto
            consultas_validas = [
                tel for tel in consulta_telefones
                if tel.consulta and tel.consulta.campanha and tel.consulta.campanha.criador_id == usuario_id
            ]

            if consultas_validas:
                # IMPORTANTE: Filtrar apenas consultas enviadas recentemente (últimas 24h)
                # Isso evita processar consultas antigas quando o mesmo telefone está em múltiplas campanhas/usuários
                from datetime import timedelta
                vinte_quatro_horas_atras = datetime.utcnow() - timedelta(hours=24)
                consultas_recentes = [
                    tel for tel in consultas_validas
                    if tel.consulta.data_envio_mensagem and tel.consulta.data_envio_mensagem >= vinte_quatro_horas_atras
                ]

                # Se não há consultas recentes, usar todas (fallback para casos onde data_envio não está setada)
                if not consultas_recentes:
                    consultas_recentes = consultas_validas

                # Separar por status
                em_fluxo = [
                    tel for tel in consultas_recentes
                    if tel.consulta.status in ['AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_MOTIVO_REJEICAO', 'AGUARDANDO_OPCAO_REJEICAO', 'REAGENDADO']
                ]
                outras = [
                    tel for tel in consultas_recentes
                    if tel.consulta.status not in ['AGUARDANDO_CONFIRMACAO', 'AGUARDANDO_MOTIVO_REJEICAO', 'AGUARDANDO_OPCAO_REJEICAO', 'REAGENDADO']
                ]

                # Priorizar consultas em fluxo ativo, depois as mais recentes
                if em_fluxo:
                    # Pegar a mais recente em fluxo (maior ID de campanha, depois maior ID de consulta)
                    consulta_telefone = max(em_fluxo, key=lambda t: (t.consulta.campanha_id, t.consulta.id))
                elif outras:
                    # Pegar a mais recente das outras (maior ID de campanha, depois maior ID de consulta)
                    consulta_telefone = max(outras, key=lambda t: (t.consulta.campanha_id, t.consulta.id))

        if consulta_telefone:
            consulta = consulta_telefone.consulta
            # Verificar se pertence ao usuário correto (mesmo filtro de instância)
            if consulta and consulta.campanha and consulta.campanha.criador_id == usuario_id:
                logger.info(f"Webhook Consulta: [{instance_name}] Mensagem de {consulta.paciente} ({numero} → {consulta_telefone.numero}). "
                           f"Campanha: {consulta.campanha_id}. Status: {consulta.status}. Texto: {texto}")

                # PROTEÇÃO CONTRA DUPLICAÇÃO (múltiplos workers do Gunicorn)
                # IMPORTANTE: Criar log IMEDIATAMENTE com commit para bloquear outros workers
                from datetime import timedelta
                cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)

                # Usar with_for_update para lock otimista na consulta
                log_recente = LogMsgConsulta.query.filter(
                    LogMsgConsulta.consulta_id == consulta.id,
                    LogMsgConsulta.direcao == 'recebida',
                    LogMsgConsulta.mensagem == texto[:500],
                    LogMsgConsulta.data >= cinco_segundos_atras
                ).first()

                if log_recente:
                    logger.info(f"Mensagem duplicada detectada (já processada há {(datetime.utcnow() - log_recente.data).total_seconds():.1f}s). Ignorando.")
                    return jsonify({'status': 'ok'}), 200

                # =====================================================
                # VALIDAÇÃO: Bloquear respostas fora do prazo ou já finalizadas
                # =====================================================
                STATUS_FINAIS = ['CANCELADO', 'CONFIRMADO', 'REJEITADO', 'INFORMADO']

                # 1. Verificar se consulta já está em status final
                # EXCEÇÃO: Se tem pesquisa ativa, permite continuar o fluxo
                if consulta.status in STATUS_FINAIS:
                    # Verificar se há pesquisa de satisfação em andamento
                    if consulta.etapa_pesquisa and consulta.etapa_pesquisa not in ['CONCLUIDA', 'PULOU']:
                        # Pesquisa ativa - deixa passar para processar a resposta
                        logger.info(f"Consulta {consulta.id} com pesquisa ativa (etapa: {consulta.etapa_pesquisa}). Processando resposta: {texto[:50]}")
                    else:
                        # Sem pesquisa ativa - ignorar mensagem
                        logger.info(f"Consulta {consulta.id} já finalizada (status: {consulta.status}). Resposta ignorada: {texto[:50]}")
                        return jsonify({'status': 'ok'}), 200

                # 2. Verificar se passou mais de 48h desde o envio da mensagem
                if consulta.data_envio_mensagem:
                    quarenta_oito_horas_atras = datetime.utcnow() - timedelta(hours=48)
                    if consulta.data_envio_mensagem < quarenta_oito_horas_atras:
                        logger.info(f"Consulta {consulta.id} expirada (enviada há mais de 48h em {consulta.data_envio_mensagem}). Resposta ignorada: {texto[:50]}")
                        return jsonify({'status': 'ok'}), 200

                # IMPORTANTE: Usar o número cadastrado na consulta para garantir que respondemos no formato correto
                numero_resposta = consulta_telefone.numero

                # Criar log IMEDIATAMENTE e commitar ANTES de processar
                # Isso garante que outros workers vejam que já está sendo processado
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='recebida',
                    telefone=numero_resposta,
                    mensagem=texto[:500],
                    status='processando'  # Marca como processando primeiro
                )
                db.session.add(log)
                db.session.commit()  # COMMIT IMEDIATO para bloquear outros workers

                ws = WhatsApp(consulta.campanha.criador_id)

                # ESTADO 1: AGUARDANDO_CONFIRMACAO (resposta à MSG 1)
                if consulta.status == 'AGUARDANDO_CONFIRMACAO':
                    # Verificar se é SIM, NÃO ou DESCONHEÇO
                    if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM):
                        # Paciente confirmou!
                        consulta.data_confirmacao = datetime.utcnow()
                        
                        # Verificar se é INTERCONSULTA que NÃO precisa ir ao posto
                        if (consulta.tipo == 'INTERCONSULTA' and 
                            consulta.paciente_voltar_posto_sms and 
                            consulta.paciente_voltar_posto_sms.upper() == 'NÃO'):
                            # INTERCONSULTA aprovada sem necessidade de ir ao posto
                            # Pula o passo de aguardar comprovante e vai direto para CONFIRMADO
                            consulta.status = 'CONFIRMADO'
                            db.session.commit()
                            
                            consulta.campanha.atualizar_stats()
                            db.session.commit()
                            
                            # Enviar mensagem de aprovação da interconsulta
                            msg_aprovacao = formatar_mensagem_interconsulta_aprovada(consulta)
                            enviar_e_registrar_consulta(ws, numero_resposta, msg_aprovacao, consulta)
                            logger.info(f"Interconsulta {consulta.id} aprovada diretamente (não precisa ir ao posto) - {consulta.paciente}")
                        else:
                            # Fluxo normal: aguardar comprovante
                            consulta.status = 'AGUARDANDO_COMPROVANTE'
                            consulta.telefone_confirmacao = numero_resposta  # Salvar qual telefone confirmou
                            db.session.commit()

                            consulta.campanha.atualizar_stats()
                            db.session.commit()

                            # [COMPROVANTE ANTECIPADO] Verificar se existe arquivo pré-carregado para este paciente
                            comp_ant = buscar_comprovante_antecipado(consulta.campanha_id, consulta.paciente)
                            if comp_ant:
                                try:
                                    # UPDATE atômico para evitar race condition entre webhooks simultâneos
                                    from sqlalchemy import update as sa_update
                                    rows = db.session.execute(
                                        sa_update(ComprovanteAntecipado)
                                        .where(ComprovanteAntecipado.id == comp_ant.id, ComprovanteAntecipado.usado == False)
                                        .values(usado=True, consulta_id=consulta.id)
                                    ).rowcount
                                    db.session.commit()
                                    if rows == 0:
                                        # Outro receive já reivindicou este comprovante — fluxo normal
                                        enviar_e_registrar_consulta(ws, numero_resposta, "✅ Consulta confirmada! Aguarde o envio do comprovante.", consulta)
                                    else:
                                        db.session.refresh(comp_ant)
                                        consulta.comprovante_path = comp_ant.filepath
                                        consulta.comprovante_nome = comp_ant.filename
                                        consulta.status = 'CONFIRMADO'
                                        db.session.commit()
                                        consulta.campanha.atualizar_stats()
                                        db.session.commit()
                                        send_fn = current_app.extensions.get('enviar_comprovante_background')
                                        if send_fn:
                                            base_url = request.host_url.rstrip('/')
                                            t = threading.Thread(
                                                target=send_fn,
                                                args=(consulta.campanha.criador_id, consulta.id, comp_ant.filepath, numero_resposta, base_url),
                                                daemon=True
                                            )
                                            t.start()
                                        enviar_e_registrar_consulta(ws, numero_resposta, "✅ Consulta confirmada! Seu comprovante está sendo enviado agora.", consulta)
                                        logger.info(f"[AUTO] Comprovante antecipado enviado automaticamente para {consulta.paciente}")
                                except Exception as e_ant:
                                    logger.error(f"[AUTO] Erro ao processar comprovante antecipado para {consulta.paciente}: {e_ant}")
                                    enviar_e_registrar_consulta(ws, numero_resposta, "✅ Consulta confirmada! Aguarde o envio do comprovante.", consulta)
                            else:
                                enviar_e_registrar_consulta(ws, numero_resposta, "✅ Consulta confirmada! Aguarde o envio do comprovante.", consulta)
                            logger.info(f"Consulta {consulta.id} confirmada por {consulta.paciente}")

                        # Notificar OUTROS telefones que a consulta já foi confirmada
                        # (exceto os que responderam DESCONHEÇO)
                        for tel in consulta.telefones:
                            if tel.numero != numero_resposta and tel.enviado and not tel.invalido and not tel.nao_pertence:
                                try:
                                    ws.enviar(tel.numero, f"ℹ️ A consulta de *{consulta.paciente}* já foi confirmada em outro telefone.\n\nNão é necessário responder por este número.")
                                    logger.info(f"Notificação enviada para {tel.numero} sobre confirmação em {numero_resposta}")
                                except Exception as e:
                                    logger.warning(f"Erro ao notificar {tel.numero}: {e}")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                        # Paciente respondeu NÃO (Opção 2)
                        # Ir direto para perguntar motivo (reagendamento desativado)
                        consulta.status = 'AGUARDANDO_MOTIVO_REJEICAO'
                        db.session.commit()

                        msg_perguntar_motivo = formatar_mensagem_perguntar_motivo()
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_perguntar_motivo, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu opção 2 (NÃO), aguardando motivo da rejeição")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO):
                        # Paciente não conhece → Marcar APENAS este telefone como "não pertence"
                        # Só rejeita a consulta se TODOS os telefones forem marcados assim

                        # Marcar este telefone como "não pertence ao paciente"
                        consulta_telefone.nao_pertence = True
                        db.session.commit()

                        # Verificar se TODOS os telefones válidos (enviados e não inválidos) foram marcados como "não pertence"
                        telefones_validos = [t for t in consulta.telefones if t.enviado and not t.invalido]
                        telefones_nao_pertence = [t for t in telefones_validos if t.nao_pertence]

                        todos_nao_pertencem = len(telefones_validos) > 0 and len(telefones_nao_pertence) == len(telefones_validos)

                        if todos_nao_pertencem:
                            # TODOS os telefones responderam "DESCONHEÇO" → Rejeitar consulta
                            consulta.status = 'REJEITADO'
                            consulta.motivo_rejeicao = 'Paciente não localizado - todos os telefones responderam DESCONHEÇO'
                            consulta.data_rejeicao = datetime.utcnow()
                            db.session.commit()

                            consulta.campanha.atualizar_stats()
                            db.session.commit()

                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela informação!*

Vamos atualizar nossos registros.

_Hospital Universitário Walter Cantídio_""", consulta)
                            logger.info(f"Consulta {consulta.id} rejeitada - TODOS os telefones responderam DESCONHEÇO (paciente não localizado)")
                        else:
                            # Ainda há outros telefones que podem responder
                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela informação!*

Este número foi marcado como não pertencente ao paciente.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""", consulta)
                            logger.info(f"Consulta {consulta.id}: telefone {numero_resposta} marcado como 'não pertence ao paciente'. Tentando próximo número...")

                            # Enviar IMEDIATAMENTE para o próximo telefone não enviado
                            telefones_pendentes = sorted(
                                [t for t in consulta.telefones if not t.enviado and not t.invalido],
                                key=lambda t: t.prioridade
                            )
                            if telefones_pendentes:
                                proximo = telefones_pendentes[0]
                                msg_proximo = formatar_mensagem_consulta_inicial(consulta)
                                ok_prox, result_prox = ws.enviar(proximo.numero, msg_proximo)
                                if ok_prox:
                                    proximo.enviado = True
                                    proximo.data_envio = datetime.utcnow()
                                    proximo.msg_id = result_prox
                                    proximo.invalido = False
                                    proximo.erro_envio = None
                                    log_prox = LogMsgConsulta(
                                        campanha_id=consulta.campanha_id,
                                        consulta_id=consulta.id,
                                        direcao='enviada',
                                        telefone=proximo.numero,
                                        mensagem=msg_proximo[:500],
                                        status='sucesso',
                                        msg_id=result_prox
                                    )
                                    db.session.add(log_prox)
                                    db.session.commit()
                                    logger.info(f"Consulta {consulta.id}: enviado para próximo número {proximo.numero} (prioridade {proximo.prioridade})")
                                else:
                                    proximo.invalido = True
                                    proximo.erro_envio = str(result_prox)[:200]
                                    db.session.commit()
                                    logger.warning(f"Consulta {consulta.id}: erro ao enviar para {proximo.numero}: {result_prox}")

                    else:
                        # Resposta não reconhecida
                        enviar_e_registrar_consulta(ws, numero_resposta, """⚠️ *Não entendi sua resposta.*

Por favor, responda *APENAS* com:

*1* ou *SIM* ✅ para confirmar
*2* ou *NÃO* ❌ para cancelar
*3* ou *DESCONHEÇO* se não é você""", consulta)

                    return jsonify({'status': 'ok'}), 200

                # ESTADO 1.5: AGUARDANDO_OPCAO_REJEICAO (resposta se quer cancelar ou reagendar)
                elif consulta.status == 'AGUARDANDO_OPCAO_REJEICAO':
                    # Verificar resposta (deve ser EXATAMENTE: 1, UM ou CANCELAR como mensagem completa)
                    
                    if verificar_resposta_em_lista(texto_up, ['1', 'UM']):
                        # Quer CANCELAR → Perguntar motivo (fluxo antigo)
                        consulta.status = 'AGUARDANDO_MOTIVO_REJEICAO'
                        db.session.commit()

                        msg_perguntar_motivo = formatar_mensagem_perguntar_motivo()
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_perguntar_motivo, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu CANCELAR, aguardando motivo")
                        
                    elif verificar_resposta_em_lista(texto_up, ['2', 'DOIS']):
                        # Quer REAGENDAR → Status especial para equipe atuar
                        consulta.status = 'AGUARDANDO_REAGENDAMENTO'
                        db.session.commit()
                        
                        enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Entendido!*
                        
Nossa equipe foi notificada e entrará em contato em breve para verificar uma nova data disponível para você.

Por favor, aguarde nosso retorno.

_Hospital Universitário Walter Cantídio_""", consulta)
                        logger.info(f"Consulta {consulta.id}: paciente escolheu REAGENDAR (aguardando equipe)")
                        
                    else:
                        # Resposta inválida
                        enviar_e_registrar_consulta(ws, numero_resposta, """Por favor, digite o número da opção desejada:

1️⃣ *CANCELAR* - Não quero mais a consulta
2️⃣ *REAGENDAR* - Quero mudar a data/horário""", consulta)
                        
                    return jsonify({'status': 'ok'}), 200

                # ESTADO 2: AGUARDANDO_MOTIVO_REJEICAO (resposta à MSG 3A)
                elif consulta.status == 'AGUARDANDO_MOTIVO_REJEICAO':
                    # Armazenar motivo da rejeição
                    consulta.motivo_rejeicao = texto
                    consulta.status = 'REJEITADO'
                    consulta.data_rejeicao = datetime.utcnow()
                    db.session.commit()

                    logger.info(f"Consulta {consulta.id} rejeitada. Motivo: {texto}")

                    # Verificar se deve enviar MSG 3B (voltar ao posto)
                    # Só envia se: INTERCONSULTA + PACIENTE_VOLTAR_POSTO_SMS = SIM
                    if (consulta.tipo == 'INTERCONSULTA' and
                        consulta.paciente_voltar_posto_sms and
                        consulta.paciente_voltar_posto_sms.upper() == 'SIM'):

                        msg_voltar_posto = formatar_mensagem_voltar_posto(consulta)
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_voltar_posto, consulta)
                        logger.info(f"MSG 3B enviada para {consulta.paciente} (INTERCONSULTA + voltar posto)")
                    else:
                        # Outros casos: enviar mensagem de confirmação de cancelamento
                        msg_confirmacao = formatar_mensagem_confirmacao_rejeicao(consulta)
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_confirmacao, consulta)
                        logger.info(f"Consulta {consulta.id} cancelada - confirmação enviada")

                    consulta.campanha.atualizar_stats()
                    db.session.commit()

                    return jsonify({'status': 'ok'}), 200

                # ESTADO 3: REAGENDADO (resposta à mensagem de reagendamento)
                elif consulta.status == 'REAGENDADO':
                    # Paciente recebeu nova data e está confirmando
                    if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM):
                        # Paciente confirmou o reagendamento! → AGUARDANDO_COMPROVANTE
                        consulta.status = 'AGUARDANDO_COMPROVANTE'
                        consulta.data_confirmacao = datetime.utcnow()
                        db.session.commit()

                        consulta.campanha.atualizar_stats()
                        db.session.commit()

                        # Mensagem de confirmação com a nova data
                        nova_data = consulta.nova_data or consulta.data_aghu or 'data agendada'
                        nova_hora = consulta.nova_hora or ''

                        # [COMPROVANTE ANTECIPADO] Verificar arquivo pré-carregado no reagendamento
                        comp_ant_reag = buscar_comprovante_antecipado(consulta.campanha_id, consulta.paciente)
                        if comp_ant_reag:
                            try:
                                # UPDATE atômico para evitar race condition
                                from sqlalchemy import update as sa_update
                                rows_reag = db.session.execute(
                                    sa_update(ComprovanteAntecipado)
                                    .where(ComprovanteAntecipado.id == comp_ant_reag.id, ComprovanteAntecipado.usado == False)
                                    .values(usado=True, consulta_id=consulta.id)
                                ).rowcount
                                db.session.commit()
                                if rows_reag > 0:
                                    db.session.refresh(comp_ant_reag)
                                    consulta.comprovante_path = comp_ant_reag.filepath
                                    consulta.comprovante_nome = comp_ant_reag.filename
                                    consulta.status = 'CONFIRMADO'
                                    db.session.commit()
                                    consulta.campanha.atualizar_stats()
                                    db.session.commit()
                                send_fn = current_app.extensions.get('enviar_comprovante_background')
                                if rows_reag > 0 and send_fn:
                                    base_url = request.host_url.rstrip('/')
                                    t = threading.Thread(
                                        target=send_fn,
                                        args=(consulta.campanha.criador_id, consulta.id, comp_ant_reag.filepath, numero_resposta, base_url),
                                        daemon=True
                                    )
                                    t.start()
                                    msg_confirmacao = f"""✅ *Reagendamento confirmado!*

📅 Data: {nova_data}
⏰ Horário: {nova_hora}
👨‍⚕️ Especialidade: {consulta.especialidade}

Seu comprovante está sendo enviado agora.

_Hospital Universitário Walter Cantídio_"""
                                    logger.info(f"[AUTO] Comprovante antecipado enviado (reagendamento) para {consulta.paciente}")
                                else:
                                    msg_confirmacao = f"""✅ *Reagendamento confirmado!*

📅 Data: {nova_data}
⏰ Horário: {nova_hora}
👨‍⚕️ Especialidade: {consulta.especialidade}

Aguarde o envio do comprovante.

_Hospital Universitário Walter Cantídio_"""
                            except Exception as e_ant:
                                logger.error(f"[AUTO] Erro comprovante antecipado reagendamento {consulta.paciente}: {e_ant}")
                                msg_confirmacao = f"""✅ *Reagendamento confirmado!*

📅 Data: {nova_data}
⏰ Horário: {nova_hora}
👨‍⚕️ Especialidade: {consulta.especialidade}

Aguarde o envio do comprovante.

_Hospital Universitário Walter Cantídio_"""
                        else:
                            msg_confirmacao = f"""✅ *Reagendamento confirmado!*

📅 Data: {nova_data}
⏰ Horário: {nova_hora}
👨‍⚕️ Especialidade: {consulta.especialidade}

Aguarde o envio do comprovante.

_Hospital Universitário Walter Cantídio_"""
                        enviar_e_registrar_consulta(ws, numero_resposta, msg_confirmacao, consulta)
                        logger.info(f"Consulta {consulta.id} reagendamento confirmado por {consulta.paciente}")

                        # Notificar OUTROS telefones que a consulta já foi confirmada
                        # (exceto os que responderam DESCONHEÇO)
                        for tel in consulta.telefones:
                            if tel.numero != numero_resposta and tel.enviado and not tel.invalido and not tel.nao_pertence:
                                try:
                                    ws.enviar(tel.numero, f"ℹ️ A consulta de *{consulta.paciente}* já foi confirmada em outro telefone.\n\nNão é necessário responder por este número.")
                                    logger.info(f"Notificação enviada para {tel.numero} sobre confirmação em {numero_resposta}")
                                except Exception as e:
                                    logger.warning(f"Erro ao notificar {tel.numero}: {e}")

                    elif verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                        # Paciente não pode ir na nova data → perguntar o que quer fazer
                        consulta.status = 'AGUARDANDO_OPCAO_REJEICAO'
                        db.session.commit()

                        msg_opcao = """Entendemos! O que você deseja fazer?

1️⃣ *CANCELAR* - Não quero mais a consulta
2️⃣ *REAGENDAR* - Quero outra data/horário"""

                        enviar_e_registrar_consulta(ws, numero_resposta, msg_opcao, consulta)
                        logger.info(f"Consulta {consulta.id}: paciente não confirmou reagendamento, oferecendo opções")

                    else:
                        # Resposta não reconhecida
                        enviar_e_registrar_consulta(ws, numero_resposta, """Por favor, responda com uma das opções:

1️⃣ *SIM* - Confirmar a nova data
2️⃣ *NÃO* - Não posso ir nessa data""", consulta)

                    return jsonify({'status': 'ok'}), 200

                # Outros status (CONFIRMADO, REJEITADO, etc.)
                else:
                    # =========================================================
                    # PESQUISA DE SATISFAÇÃO - Processar se etapa_pesquisa ativa
                    # =========================================================
                    if consulta.status == 'CONFIRMADO' and consulta.etapa_pesquisa:

                        # ETAPA 1: NOTA (1-10)
                        if consulta.etapa_pesquisa == 'NOTA':
                            texto_limpo = texto_up.strip()

                            # Verificar se pulou
                            if texto_limpo in ['PULAR', 'NAO', 'NÃO', 'N', 'SKIP']:
                                consulta.etapa_pesquisa = 'CONCLUIDA'
                                pesquisa = PesquisaSatisfacao(
                                    consulta_id=consulta.id,
                                    usuario_id=consulta.usuario_id,
                                    tipo_agendamento=consulta.tipo,
                                    especialidade=consulta.especialidade,
                                    pulou=True
                                )
                                db.session.add(pesquisa)
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, "✅ Obrigado! Pesquisa finalizada.", consulta)
                                return jsonify({'status': 'ok'}), 200

                            try:
                                nota = int(texto_limpo.replace('.', '').replace(',', '')[:2])
                                if 1 <= nota <= 10:
                                    pesquisa = PesquisaSatisfacao(
                                        consulta_id=consulta.id,
                                        usuario_id=consulta.usuario_id,
                                        tipo_agendamento=consulta.tipo,
                                        especialidade=consulta.especialidade,
                                        nota_satisfacao=nota
                                    )
                                    db.session.add(pesquisa)
                                    consulta.etapa_pesquisa = 'ATENDIMENTO'
                                    db.session.commit()
                                    enviar_e_registrar_consulta(ws, numero_resposta, """A equipe foi atenciosa e o processo foi ágil?

*1* - Sim ✅
*2* - Não ❌

_(ou "pular" para finalizar)_""", consulta)
                                    return jsonify({'status': 'ok'}), 200
                                else:
                                    enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, digite um número de *1 a 10*:", consulta)
                                    return jsonify({'status': 'ok'}), 200
                            except:
                                enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, digite um número de *1 a 10*:", consulta)
                                return jsonify({'status': 'ok'}), 200

                        # ETAPA 2: ATENDIMENTO (Sim/Não)
                        elif consulta.etapa_pesquisa == 'ATENDIMENTO':
                            texto_limpo = texto_up.strip()
                            pesquisa = PesquisaSatisfacao.query.filter_by(consulta_id=consulta.id).first()

                            if texto_limpo in ['PULAR', 'NAO', 'N', 'SKIP', 'FINALIZAR']:
                                consulta.etapa_pesquisa = 'CONCLUIDA'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, "✅ Obrigado pela sua avaliação! Sua opinião é muito importante para nós.", consulta)
                                return jsonify({'status': 'ok'}), 200

                            if texto_limpo in ['1', 'SIM', 'S', 'YES']:
                                if pesquisa:
                                    pesquisa.equipe_atenciosa = True
                                consulta.etapa_pesquisa = 'COMENTARIO'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, """Tem algum comentário ou sugestão?

_(Digite sua mensagem ou "N" para finalizar)_""", consulta)
                                return jsonify({'status': 'ok'}), 200

                            elif texto_limpo in ['2', 'NÃO', 'NAO']:
                                if pesquisa:
                                    pesquisa.equipe_atenciosa = False
                                consulta.etapa_pesquisa = 'COMENTARIO'
                                db.session.commit()
                                enviar_e_registrar_consulta(ws, numero_resposta, """Tem algum comentário ou sugestão?

_(Digite sua mensagem ou "N" para finalizar)_""", consulta)
                                return jsonify({'status': 'ok'}), 200

                            else:
                                enviar_e_registrar_consulta(ws, numero_resposta, "Por favor, responda *1* (Sim) ou *2* (Não):", consulta)
                                return jsonify({'status': 'ok'}), 200

                        # ETAPA 3: COMENTÁRIO
                        elif consulta.etapa_pesquisa == 'COMENTARIO':
                            texto_limpo = texto_up.strip()
                            pesquisa = PesquisaSatisfacao.query.filter_by(consulta_id=consulta.id).first()

                            if texto_limpo not in ['N', 'NAO', 'NÃO', 'PULAR', 'SKIP', 'FINALIZAR']:
                                if pesquisa:
                                    pesquisa.comentario = texto[:500]

                            consulta.etapa_pesquisa = 'CONCLUIDA'
                            db.session.commit()
                            enviar_e_registrar_consulta(ws, numero_resposta, """✅ *Obrigado pela sua avaliação!*

Sua opinião é muito importante para continuarmos melhorando nosso atendimento.

_Hospital Universitário Walter Cantídio_""", consulta)
                            return jsonify({'status': 'ok'}), 200

                        # Pesquisa já concluída - ignorar
                        elif consulta.etapa_pesquisa == 'CONCLUIDA':
                            return jsonify({'status': 'ok'}), 200

                    # CONFIRMADO sem pesquisa ativa
                    elif consulta.status == 'CONFIRMADO':
                        msg_ja_enviada = LogMsgConsulta.query.filter(
                            LogMsgConsulta.consulta_id == consulta.id,
                            LogMsgConsulta.direcao == 'enviada',
                            LogMsgConsulta.mensagem.like('%já foi confirmada%')
                        ).first()
                        
                        if not msg_ja_enviada:
                            enviar_e_registrar_consulta(ws, numero_resposta, "✅ Sua consulta já foi confirmada. Obrigado!", consulta)
                        # Se já enviou, ignora silenciosamente (fluxo encerrado)
                        
                    elif consulta.status == 'REJEITADO':
                        msg_ja_enviada = LogMsgConsulta.query.filter(
                            LogMsgConsulta.consulta_id == consulta.id,
                            LogMsgConsulta.direcao == 'enviada',
                            LogMsgConsulta.mensagem.like('%foi cancelada%')
                        ).first()
                        if not msg_ja_enviada:
                            enviar_e_registrar_consulta(ws, numero_resposta, """📋 *Registro atualizado!*

Nossa equipe analisará sua resposta e, se necessário, entrará em contato para verificar a melhor opção para você.

Obrigado pelo retorno!

_Hospital Universitário Walter Cantídio_""", consulta)
                        # Se já enviou, ignora silenciosamente (fluxo encerrado)
                        
                    elif consulta.status == 'AGUARDANDO_COMPROVANTE':
                        # Verificar se já enviou mensagem de confirmação para evitar duplicatas
                        msg_ja_enviada = LogMsgConsulta.query.filter(
                            LogMsgConsulta.consulta_id == consulta.id,
                            LogMsgConsulta.direcao == 'enviada',
                            LogMsgConsulta.mensagem.like('%confirmada%Aguarde%comprovante%')
                        ).first()
                        
                        if not msg_ja_enviada:
                            enviar_e_registrar_consulta(ws, numero_resposta, "✅ Sua consulta está confirmada! Aguarde o envio do comprovante.", consulta)
                        # Se já enviou, ignora silenciosamente (não envia duplicatas)
                    else:
                        enviar_e_registrar_consulta(ws, numero_resposta, "Recebemos sua mensagem. Obrigado!", consulta)

                    return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # FILA CIRÚRGICA - Processar apenas se NÃO for consulta
        # =====================================================================

        # Buscar Telefone e Contato
        # Prioriza contatos NAO concluidos, depois os mais recentes
        # Tenta encontrar o telefone exato ou variacoes
        telefones = Telefone.query.filter_by(numero_fmt=numero).all()
        
        if not telefones:
            # Tenta variacao 9o digito
            if len(numero) == 12:
                num9 = numero[:4] + '9' + numero[4:]
                telefones = Telefone.query.filter_by(numero_fmt=num9).all()
            elif len(numero) == 13:
                num_sem9 = numero[:4] + numero[5:]
                telefones = Telefone.query.filter_by(numero_fmt=num_sem9).all()
        
        if not telefones:
            logger.warning(f"Webhook: Telefone nao encontrado para {numero}")
            return jsonify({'status': 'ok'}), 200
        
        # Priorizar o contato mais apropriado para responder
        # PRIORIDADE:
        # 0. FILTRAR apenas campanhas do usuário dono da instância (CRÍTICO para multi-usuário)
        # 1. Se a mensagem NÃO é uma resposta válida (1, 2, 3), priorizar campanha concluída recentemente
        # 2. Contatos em fluxo ativo (enviado, aguardando_nascimento) da campanha mais recente
        # 3. Contatos com data_envio mais recente (último a receber mensagem)
        # 4. Contatos com data_resposta mais recente (última interação)
        # 5. Contato mais recente por ID
        c = None

        # CRÍTICO: Filtrar apenas contatos de campanhas do usuário correto
        # Isso evita processar respostas no contexto de outro usuário quando
        # dois usuários diferentes contactam o mesmo paciente
        contatos_validos = [
            t.contato for t in telefones
            if t.contato and t.contato.campanha and t.contato.campanha.criador_id == usuario_id
        ]

        if contatos_validos:
            # Buscar campanhas concluídas e em fluxo ativo
            contatos_concluidos = [ct for ct in contatos_validos if ct.status == 'concluido' and ct.data_resposta]
            contatos_em_fluxo = [ct for ct in contatos_validos if ct.status in ['enviado', 'aguardando_nascimento', 'aguardando_motivo_rejeicao', 'pronto_envio']]

            # LÓGICA DE PRIORIZAÇÃO:
            # 1. Se há campanha concluída E campanha em fluxo ativo, comparar datas
            # 2. Prioriza a interação mais recente (data_resposta vs data_envio)
            # 3. Se só há uma ou outra, usa a disponível

            if contatos_concluidos and contatos_em_fluxo:
                # Pegar mais recente de cada tipo
                concluido_recente = max(contatos_concluidos, key=lambda ct: (ct.data_resposta, ct.id))

                def get_ultima_data_envio(contato):
                    datas = [t.data_envio for t in contato.telefones if t.data_envio]
                    return max(datas) if datas else datetime.min

                fluxo_recente = max(contatos_em_fluxo, key=lambda ct: (get_ultima_data_envio(ct), ct.id))

                # Comparar: se campanha concluída é mais recente, usar ela
                # Isso garante que "1" após conclusão responde "já confirmou"
                if concluido_recente.data_resposta > get_ultima_data_envio(fluxo_recente):
                    c = concluido_recente
                else:
                    c = fluxo_recente
            elif contatos_concluidos:
                # Só tem concluídas
                c = max(contatos_concluidos, key=lambda ct: (ct.data_resposta, ct.id))
            elif contatos_em_fluxo:
                # Só tem fluxo ativo
                def get_ultima_data_envio(contato):
                    datas = [t.data_envio for t in contato.telefones if t.data_envio]
                    return max(datas) if datas else datetime.min

                c = max(contatos_em_fluxo, key=lambda ct: (get_ultima_data_envio(ct), ct.id))
            else:
                # Nenhuma concluída nem em fluxo, pegar qualquer uma por data_resposta
                c = max(contatos_validos, key=lambda ct: (ct.data_resposta or datetime.min, ct.id))

        if not c:
            # Verificar se existem contatos de outros usuários (para debug)
            todos_contatos = [t.contato for t in telefones if t.contato]
            if todos_contatos:
                outros_usuarios = set(ct.campanha.criador_id for ct in todos_contatos if ct.campanha)
                logger.warning(f"Webhook: Telefone {numero} não tem campanhas do usuário {usuario_id}. "
                             f"Campanhas existem para usuários: {outros_usuarios}")
            else:
                logger.warning(f"Webhook: Telefone {numero} não encontrado em nenhuma campanha")
            return jsonify({'status': 'ok'}), 200

        # =====================================================================
        # FILA CIRÚRGICA - Processar respostas (código original continua abaixo)
        # =====================================================================

        logger.info(f"Webhook: [{instance_name}] Mensagem de {c.nome} ({numero}). "
                   f"Campanha: {c.campanha_id} (User {usuario_id}). Status: {c.status}. Texto: {texto}")

        # PROTEÇÃO CONTRA DUPLICAÇÃO (múltiplos workers do Gunicorn)
        # IMPORTANTE: Criar log IMEDIATAMENTE com commit para bloquear outros workers
        from datetime import timedelta
        cinco_segundos_atras = datetime.utcnow() - timedelta(seconds=5)
        log_recente = LogMsg.query.filter(
            LogMsg.contato_id == c.id,
            LogMsg.direcao == 'recebida',
            LogMsg.mensagem == texto[:500],
            LogMsg.data >= cinco_segundos_atras
        ).first()

        if log_recente:
            logger.info(f"Mensagem duplicada detectada (já processada há {(datetime.utcnow() - log_recente.data).total_seconds():.1f}s). Ignorando.")
            return jsonify({'status': 'ok'}), 200

        # Análise de sentimento
        analise = AnaliseSentimento.analisar(texto)

        # Criar log IMEDIATAMENTE e commitar ANTES de processar
        # Isso garante que outros workers vejam que já está sendo processado
        log = LogMsg(
            campanha_id=c.campanha_id,
            contato_id=c.id,
            direcao='recebida',
            telefone=numero,
            mensagem=texto[:500],
            status='ok',
            sentimento=analise['sentimento'],
            sentimento_score=analise['score']
        )
        db.session.add(log)
        db.session.commit()  # COMMIT IMEDIATO para bloquear outros workers

        ws = WhatsApp(c.campanha.criador_id)

        # Verificar primeiro se é uma resposta válida da campanha (1, 2, 3)
        # Isso impede que respostas válidas sejam tratadas como FAQ ou tickets
        respostas_validas = (verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM) or
                            verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO) or
                            verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO))

        # Primeiro, tentar responder com FAQ automático
        # IMPORTANTE: NÃO processar FAQ se contato está em fluxo ativo da campanha
        # (status enviado/pronto_envio/aguardando_nascimento/aguardando_motivo_rejeicao devem ir direto para a máquina de estados)
        # EXCEÇÃO: Se status é 'concluido', SEMPRE permitir FAQ (mesmo para respostas válidas como 1, 2, 3)
        ESTADOS_FLUXO_ATIVO = ['aguardando_nascimento', 'aguardando_motivo_rejeicao', 'enviado', 'pronto_envio']
        resposta_faq = None
        if c.status == 'concluido' or (c.status not in ESTADOS_FLUXO_ATIVO and not respostas_validas):
            # Buscar FAQs globais + FAQs do criador da campanha
            usuario_id = c.campanha.criador_id if c.campanha else None
            resposta_faq = SistemaFAQ.buscar_resposta(texto, usuario_id)

        # Se tem FAQ, responde
        if resposta_faq:
            ws.enviar(numero, resposta_faq)
            logger.info(f"FAQ automático enviado para {c.nome}")
            return jsonify({'status': 'ok'}), 200

        # Maquina de Estados
        # Aceita 'pronto_envio' tambem pois pode haver race condition (usuario responde antes do loop de envio terminar)
        # Aceita 'pendente' se a resposta é válida (1, 2, 3) - útil para testes e recuperação de erros
        if c.status in ['enviado', 'pronto_envio'] or (c.status == 'pendente' and respostas_validas):
            # Se era pendente e recebeu resposta válida, atualiza para enviado automaticamente
            if c.status == 'pendente' and respostas_validas:
                c.status = 'enviado'
                db.session.commit()
                logger.info(f"Status de {c.nome} atualizado de 'pendente' para 'enviado' após receber resposta válida")

            # Encontrar o telefone específico que enviou esta resposta
            telefone_respondente = None
            for t in telefones:
                if t.contato_id == c.id:
                    telefone_respondente = t
                    break

            if verificar_resposta_em_lista(texto_up, RESPOSTAS_SIM):
                c.resposta = texto
                c.data_resposta = datetime.utcnow()

                if telefone_respondente:
                    telefone_respondente.resposta = texto
                    telefone_respondente.data_resposta = datetime.utcnow()
                    telefone_respondente.tipo_resposta = 'confirmado'
                    telefone_respondente.validacao_pendente = False
                    telefone_respondente.whatsapp_valido = True

                c.calcular_status_final()
                db.session.commit()
                c.campanha.atualizar_stats()
                db.session.commit()

                ws.enviar(numero, """✅ *Confirmação Registrada com Sucesso!*

Obrigado por confirmar seu interesse no procedimento.

📞 *Próximos Passos:*
• Nossa equipe entrará em contato em breve
• Mantenha seu telefone com notificações ativas
• Fique atento às ligações do hospital

❓ *Tem dúvidas?*
Digite sua pergunta a qualquer momento que responderemos!

_Hospital Universitário Walter Cantídio_""")

            elif verificar_resposta_em_lista(texto_up, RESPOSTAS_NAO):
                # Guarda intenção e pergunta o motivo antes de concluir
                c.resposta = texto
                c.data_resposta = datetime.utcnow()
                c.status = 'aguardando_motivo_rejeicao'

                if telefone_respondente:
                    telefone_respondente.resposta = texto
                    telefone_respondente.data_resposta = datetime.utcnow()
                    telefone_respondente.tipo_resposta = 'rejeitado'
                    telefone_respondente.validacao_pendente = False
                    telefone_respondente.whatsapp_valido = True

                db.session.commit()

                ws.enviar(numero, """Entendemos sua decisão.

Para nos ajudar a melhorar, poderia informar o *motivo*?

1️⃣ Já realizei em outro hospital
2️⃣ Problemas de saúde / Não tenho condições
3️⃣ Não quero mais a cirurgia
4️⃣ Outro motivo

_(Responda com o número ou descreva o motivo)_""")

            elif verificar_resposta_em_lista(texto_up, RESPOSTAS_DESCONHECO):
                c.resposta = texto
                c.data_resposta = datetime.utcnow()

                if telefone_respondente:
                    telefone_respondente.resposta = texto
                    telefone_respondente.data_resposta = datetime.utcnow()
                    telefone_respondente.tipo_resposta = 'desconheco'
                    telefone_respondente.nao_pertence = True
                    telefone_respondente.validacao_pendente = False
                    telefone_respondente.whatsapp_valido = True

                db.session.commit()

                # Verificar se TODOS os telefones válidos (enviados e não inválidos) foram marcados como nao_pertence
                telefones_validos = [t for t in c.telefones if t.enviado and not t.invalido]
                todos_nao_pertencem = (
                    len(telefones_validos) > 0 and
                    all(t.nao_pertence for t in telefones_validos)
                )

                if todos_nao_pertencem:
                    # TODOS os telefones responderam DESCONHEÇO → rejeitar contato
                    c.rejeitado = True
                    c.motivo_rejeicao = 'Paciente não localizado - todos os telefones responderam DESCONHEÇO'
                    c.data_rejeicao = datetime.utcnow()
                    c.status = 'concluido'
                    db.session.commit()
                    c.campanha.atualizar_stats()
                    db.session.commit()

                    logger.info(f"Contato {c.id} rejeitado - TODOS os telefones responderam DESCONHEÇO (paciente não localizado)")

                    ws.enviar(numero, """✅ *Obrigado pela informação!*

Vamos atualizar nossos registros.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""")
                else:
                    # Ainda há outros telefones que podem responder
                    c.calcular_status_final()
                    db.session.commit()

                    logger.info(f"Contato {c.id}: telefone {numero} marcado como não pertence ao paciente. Aguardando outros telefones.")

                    ws.enviar(numero, """✅ *Obrigado pela informação!*

Este número foi marcado como não pertencente ao paciente.

Desculpe pelo transtorno.

_Hospital Universitário Walter Cantídio_""")

            else:
                # Resposta inválida — orienta o paciente
                ws.enviar(numero, """⚠️ Não entendi sua resposta.

Por favor, responda com:

*1* — Tenho interesse ✅
*2* — Não tenho mais interesse ❌
*3* — Não sou essa pessoa 🔄""")
                
        elif c.status == 'aguardando_nascimento':
            # Validação de data de nascimento removida - finalizar direto com base na intenção gravada
            telefone_validando = None
            for t in telefones:
                if t.contato_id == c.id and t.validacao_pendente:
                    telefone_validando = t
                    break

            # Fallback: se nenhum tem validacao_pendente, usar o primeiro telefone do contato
            if not telefone_validando:
                telefone_validando = next((t for t in telefones if t.contato_id == c.id), None)

            if telefone_validando:
                telefone_validando.validacao_pendente = False
                telefone_validando.whatsapp_valido = True

            intent_up = (c.resposta or '').upper()
            msg_final = "✅ Obrigado."

            if verificar_resposta_em_lista(intent_up, RESPOSTAS_SIM):
                msg_final = """✅ *Confirmação Registrada com Sucesso!*

Obrigado por confirmar seu interesse no procedimento.

📞 *Próximos Passos:*
• Nossa equipe entrará em contato em breve
• Mantenha seu telefone com notificações ativas
• Fique atento às ligações do hospital

❓ *Tem dúvidas?*
Digite sua pergunta a qualquer momento que responderemos!

_Hospital Universitário Walter Cantídio_"""
            elif verificar_resposta_em_lista(intent_up, RESPOSTAS_NAO):
                msg_final = """✅ *Registro Atualizado*

Obrigado por sua resposta.

Registramos que você não tem mais interesse no procedimento. Seus dados serão atualizados em nosso sistema.

Se mudar de ideia ou tiver alguma dúvida, pode entrar em contato conosco.

_Hospital Universitário Walter Cantídio_"""

            c.calcular_status_final()
            db.session.commit()
            c.campanha.atualizar_stats()
            db.session.commit()

            ws.enviar(numero, msg_final)

        elif c.status == 'aguardando_motivo_rejeicao':
            # Processar motivo de rejeição — qualquer resposta finaliza o fluxo
            MOTIVOS_REJEICAO = {
                '1': 'Já realizei em outro hospital',
                '2': 'Problemas de saúde / Não tenho condições',
                '3': 'Não quero mais a cirurgia',
                '4': 'Outro motivo',
            }
            motivo = MOTIVOS_REJEICAO.get(texto_up.strip(), texto[:200] if texto.strip() else 'Não informado')
            c.motivo_rejeicao = motivo
            c.data_rejeicao = datetime.utcnow()
            c.calcular_status_final()
            db.session.commit()
            c.campanha.atualizar_stats()
            db.session.commit()

            logger.info(f"Contato {c.id} rejeitado. Motivo: {motivo}")

            ws.enviar(numero, """✅ *Registro Atualizado*

Obrigado por sua resposta.

Registramos que você não tem mais interesse no procedimento. Seus dados serão atualizados em nosso sistema.

Se mudar de ideia ou tiver alguma dúvida, pode entrar em contato conosco.

_Hospital Universitário Walter Cantídio_""")

        elif c.status == 'concluido':
            # Se o usuario mandar mensagem depois de concluido, reforcar o status uma única vez
            # (FAQ já foi verificado no início do receive)
            # Cooldown de 24h POR NÚMERO para evitar spam e bloqueio no WhatsApp
            um_dia_atras = datetime.utcnow() - timedelta(hours=24)
            msg_concluido_recente = LogMsg.query.filter(
                LogMsg.contato_id == c.id,
                LogMsg.direcao == 'enviada',
                LogMsg.telefone == numero,
                LogMsg.data >= um_dia_atras
            ).first()

            if not msg_concluido_recente:
                # Verificar se este número foi o que respondeu ou se é outro número do mesmo contato
                tel_respondente = next((t for t in telefones if t.contato_id == c.id), None)
                este_numero_respondeu = tel_respondente and tel_respondente.tipo_resposta is not None

                if este_numero_respondeu:
                    if c.confirmado:
                        msg_concluido = "✅ Você já confirmou seu interesse. Obrigado!"
                    elif c.rejeitado:
                        msg_concluido = "✅ Você já informou que não tem interesse. Obrigado!"
                    else:
                        msg_concluido = "✅ Seu atendimento já foi concluído. Obrigado!"
                else:
                    # Outro número do mesmo contato tentando responder após já concluído
                    msg_concluido = "✅ Este atendimento já foi respondido em outro número. Obrigado!"

                ws.enviar(numero, msg_concluido)

                # Registrar mensagem enviada para evitar spam nas próximas 24h (por número)
                log_enviado = LogMsg(
                    campanha_id=c.campanha_id,
                    contato_id=c.id,
                    direcao='enviada',
                    telefone=numero,
                    mensagem=msg_concluido[:500],
                    status='ok'
                )
                db.session.add(log_enviado)
                db.session.commit()
                logger.info(f"Resposta de concluído enviada para {c.nome} ({numero})")
            else:
                logger.info(f"Mensagem de {c.nome} ({numero}) ignorada - resposta já enviada nas últimas 24h")

        return jsonify({'status': 'ok'}), 200

    except Exception as e:
        logger.error(f"Webhook erro: {e}")
        return jsonify({'status': 'error'}), 500
@bp.route('/receive/whatsapp', methods=['GET'])
def check():
    return jsonify({'status': 'ok', 'app': 'Busca Ativa HUWC'}), 200
