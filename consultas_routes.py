"""
=============================================================================
ROTAS - MODO CONSULTA (Agendamento de Consultas)
=============================================================================
Endpoints Flask para o sistema de agendamento de consultas
Separado da fila cirúrgica (BUSCA_ATIVA)
"""

from flask import render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from datetime import datetime, date
import pandas as pd
import os
import time
import threading
import logging

logger = logging.getLogger(__name__)


def init_consultas_routes(app, db):
    """
    Inicializa todas as rotas do modo consulta

    Args:
        app: Flask app instance
        db: SQLAlchemy database instance
    """

    # Importar modelos e funções (evita circular import)
    from app import (
        CampanhaConsulta, AgendamentoConsulta, TelefoneConsulta,
        LogMsgConsulta, WhatsApp, formatar_numero,
        formatar_mensagem_comprovante, formatar_mensagem_voltar_posto,
        extrair_dados_comprovante, PesquisaSatisfacao, enviar_e_registrar_consulta,
        Paciente, HistoricoConsulta
    )

    try:
        from celery.result import AsyncResult
        from tasks import enviar_campanha_consultas_task
    except ImportError:
        AsyncResult = None
        enviar_campanha_consultas_task = None
        logger.warning("Celery não disponível para modo consulta")


    # =========================================================================
    # FUNÇÃO AUXILIAR - Envio de comprovante em background
    # =========================================================================
    def enviar_comprovante_background(usuario_id, consulta_id, filepath, telefone, base_url):
        """
        Envia comprovante em background (OCR + mensagem + arquivo + pesquisa).
        Executado em thread separada para não bloquear a interface do usuário.
        """
        try:
            logger.info(f"[BG] Iniciando envio de comprovante para consulta {consulta_id}")

            with app.app_context():
                consulta = AgendamentoConsulta.query.get(consulta_id)
                if not consulta:
                    logger.error(f"[BG] Consulta {consulta_id} não encontrada")
                    return

                # Extrair dados do comprovante via OCR
                dados_ocr = None
                try:
                    dados_ocr = extrair_dados_comprovante(filepath)
                    if dados_ocr:
                        logger.info(f"[BG] Dados extraídos do comprovante via OCR: {dados_ocr}")
                except Exception as ocr_err:
                    logger.warning(f"[BG] Erro ao extrair dados via OCR (continuando sem): {ocr_err}")
                    dados_ocr = {}

                if not dados_ocr:
                    dados_ocr = {}

                # Configurar WhatsApp
                ws = WhatsApp(usuario_id)
                if not ws.ok():
                    logger.error(f"[BG] WhatsApp não configurado para usuário {usuario_id}")
                    return

                # Gerar link público do comprovante
                link_comprovante = f"{base_url}/consulta/comprovante/{consulta_id}"

                # Enviar mensagem de texto (personalizada com dados do OCR + link)
                msg = formatar_mensagem_comprovante(consulta=consulta, dados_ocr=dados_ocr, link_comprovante=link_comprovante)
                ok_msg, result_msg = ws.enviar(telefone, msg)

                if not ok_msg:
                    logger.error(f"[BG] Erro ao enviar mensagem: {result_msg}")
                    return

                # Log da mensagem
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='enviada',
                    telefone=telefone,
                    mensagem=f'{msg[:200]}... [COMPROVANTE ANEXO]',
                    status='sucesso',
                    msg_id=result_msg
                )
                db.session.add(log)
                db.session.commit()

                # Aguardar antes de enviar o arquivo
                time.sleep(7)

                # Enviar arquivo
                ok_file, result_file = ws.enviar_arquivo(telefone, filepath)
                if not ok_file:
                    logger.warning(f"[BG] Erro ao enviar arquivo: {result_file}")

                # =====================================================
                # HISTÓRICO DO PACIENTE
                # =====================================================
                try:
                    paciente_db = Paciente.query.filter_by(usuario_id=usuario_id, telefone=telefone).first()
                    if not paciente_db:
                        paciente_db = Paciente.query.filter_by(usuario_id=usuario_id, nome=dados_ocr.get('paciente', consulta.paciente)).first()

                    if not paciente_db:
                        paciente_db = Paciente(
                            usuario_id=usuario_id,
                            nome=dados_ocr.get('paciente', consulta.paciente),
                            telefone=telefone,
                            data_nascimento=dados_ocr.get('data_nascimento'),
                            prontuario=dados_ocr.get('prontuario'),
                            codigo=dados_ocr.get('codigo')
                        )
                        db.session.add(paciente_db)
                        db.session.commit()
                    else:
                        if dados_ocr.get('data_nascimento'): paciente_db.data_nascimento = dados_ocr.get('data_nascimento')
                        if dados_ocr.get('prontuario'): paciente_db.prontuario = dados_ocr.get('prontuario')
                        if dados_ocr.get('codigo'): paciente_db.codigo = dados_ocr.get('codigo')
                        db.session.commit()

                    historico = HistoricoConsulta(
                        paciente_id=paciente_db.id,
                        consulta_id=consulta.id,
                        usuario_id=usuario_id,
                        nro_consulta=dados_ocr.get('nro_consulta'),
                        data_consulta=dados_ocr.get('data'),
                        hora_consulta=dados_ocr.get('hora'),
                        dia_semana=dados_ocr.get('dia'),
                        grade=dados_ocr.get('grade'),
                        unidade_funcional=dados_ocr.get('unidade_funcional'),
                        andar=dados_ocr.get('andar'),
                        ala_bloco=dados_ocr.get('ala_bloco'),
                        setor=dados_ocr.get('setor'),
                        sala=dados_ocr.get('sala'),
                        tipo_consulta=dados_ocr.get('consulta'),
                        tipo_demanda=dados_ocr.get('tipo'),
                        equipe=dados_ocr.get('equipe'),
                        profissional=dados_ocr.get('profissional'),
                        especialidade=consulta.especialidade,
                        exames=consulta.exames,
                        marcado_por=dados_ocr.get('marcado_por'),
                        observacao=dados_ocr.get('observacao'),
                        nro_autorizacao=dados_ocr.get('nro_autorizacao'),
                        status='CONFIRMADA',
                        comprovante_path=filepath
                    )
                    db.session.add(historico)
                    db.session.commit()
                    logger.info(f"[BG] Histórico salvo para paciente {paciente_db.nome}")
                except Exception as e:
                    logger.error(f"[BG] Erro ao salvar histórico: {e}")

                # =====================================================
                # PESQUISA DE SATISFAÇÃO
                # =====================================================
                try:
                    time.sleep(7)
                    msg_pesquisa = """📊 *Pesquisa de Satisfação* (opcional)

De *1 a 10*, qual sua satisfação com a marcação de consulta por WhatsApp?

_(Digite um número de 1 a 10, ou "pular" para não responder)_"""

                    ok_pesq, _ = ws.enviar(telefone, msg_pesquisa)
                    if ok_pesq:
                        consulta.etapa_pesquisa = 'NOTA'
                        db.session.commit()
                        logger.info(f"[BG] Pesquisa iniciada para consulta {consulta.id}")
                except Exception as e:
                    logger.warning(f"[BG] Erro ao iniciar pesquisa: {e}")

                logger.info(f"[BG] Envio de comprovante concluído para consulta {consulta_id}")

        except Exception as e:
            logger.error(f"[BG] Erro ao enviar comprovante para consulta {consulta_id}: {e}")


    # =========================================================================
    # DASHBOARD - Lista de campanhas de consultas
    # =========================================================================

    @app.route('/consultas/dashboard')
    @login_required
    def consultas_dashboard():
        """Dashboard principal - lista de campanhas de consultas"""
        tipo_sistema = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
        if tipo_sistema != 'AGENDAMENTO_CONSULTA':
            flash('Acesso negado. Usuário configurado para Fila Cirúrgica.', 'warning')
            return redirect(url_for('dashboard'))

        campanhas = CampanhaConsulta.query.filter_by(
            criador_id=current_user.id
        ).order_by(CampanhaConsulta.data_criacao.desc()).all()

        # Atualizar estatísticas de cada campanha
        for camp in campanhas:
            camp.atualizar_stats()
        db.session.commit()

        # VALIDAÇÃO: Verificar se usuário tem WhatsApp configurado
        from app import ConfigWhatsApp
        config_whatsapp = ConfigWhatsApp.query.filter_by(usuario_id=current_user.id).first()
        if not config_whatsapp and campanhas:
            flash('⚠️ ATENÇÃO: Você possui campanhas mas não tem WhatsApp configurado! '
                  'Configure o WhatsApp para poder enviar mensagens.', 'warning')

        return render_template('consultas_dashboard.html', campanhas=campanhas)


    # =========================================================================
    # TUTORIAL
    # =========================================================================

    @app.route('/consultas/tutorial')
    @login_required
    def consultas_tutorial():
        """Tutorial completo do Modo Consulta"""
        return render_template('tutorial_consultas.html')


    # =========================================================================
    # IMPORTAR PLANILHA
    # =========================================================================

    @app.route('/consultas/importar', methods=['GET', 'POST'])
    @login_required
    def consultas_importar():
        """Importa planilha Excel com consultas"""
        tipo_sistema = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
        if tipo_sistema != 'AGENDAMENTO_CONSULTA':
            flash('Acesso negado. Usuário configurado para Fila Cirúrgica.', 'warning')
            return redirect(url_for('dashboard'))

        if request.method == 'POST':
            try:
                # Validar arquivo
                if 'arquivo' not in request.files:
                    flash('Nenhum arquivo enviado', 'danger')
                    return redirect(request.url)

                arquivo = request.files['arquivo']
                if arquivo.filename == '':
                    flash('Nenhum arquivo selecionado', 'danger')
                    return redirect(request.url)

                if not arquivo.filename.endswith(('.xlsx', '.xls')):
                    flash('Formato inválido. Use .xlsx ou .xls', 'danger')
                    return redirect(request.url)

                # Receber dados do formulário
                nome = request.form.get('nome', '').strip()
                descricao = request.form.get('descricao', '').strip()
                meta_diaria = int(request.form.get('meta_diaria', 50))
                hora_inicio = int(request.form.get('hora_inicio', 8))
                hora_fim = int(request.form.get('hora_fim', 23))
                tempo_entre_envios = int(request.form.get('tempo_entre_envios', 15))

                if not nome:
                    flash('Nome da campanha é obrigatório', 'danger')
                    return redirect(request.url)

                # VALIDAÇÃO CRÍTICA: Verificar se usuário tem WhatsApp configurado
                from app import ConfigWhatsApp
                config_whatsapp = ConfigWhatsApp.query.filter_by(usuario_id=current_user.id).first()
                if not config_whatsapp:
                    flash('❌ ERRO: Você precisa configurar o WhatsApp antes de criar campanhas de consulta! '
                          'Acesse Configurações no menu superior.', 'danger')
                    return redirect(url_for('consultas_dashboard'))

                ws_test = WhatsApp(current_user.id)
                if not ws_test.ok():
                    flash('❌ ERRO: WhatsApp não está configurado corretamente. '
                          'Acesse Configurações no menu superior e configure o WhatsApp.', 'danger')
                    return redirect(url_for('consultas_dashboard'))

                # Ler planilha
                df = pd.read_excel(arquivo, dtype=str)
                df = df.fillna('')

                # Validar colunas obrigatórias
                colunas_obrigatorias = ['PACIENTE', 'TIPO']
                colunas_faltando = [c for c in colunas_obrigatorias if c not in df.columns]
                if colunas_faltando:
                    flash(f'Colunas obrigatórias faltando: {", ".join(colunas_faltando)}', 'danger')
                    return redirect(request.url)

                # Criar campanha
                campanha = CampanhaConsulta(
                    criador_id=current_user.id,
                    nome=nome,
                    descricao=descricao,
                    meta_diaria=meta_diaria,
                    hora_inicio=hora_inicio,
                    hora_fim=hora_fim,
                    tempo_entre_envios=tempo_entre_envios,
                    status='pendente'
                )
                db.session.add(campanha)
                db.session.flush()  # Para obter o ID

                # Processar cada linha
                consultas_criadas = 0
                for idx, row in df.iterrows():
                    try:
                        # Criar agendamento
                        consulta = AgendamentoConsulta(
                            campanha_id=campanha.id,
                            usuario_id=current_user.id,
                            # Dados da planilha
                            posicao=str(row.get('POSICAO', '')).strip(),
                            cod_master=str(row.get('COD MASTER', '')).strip(),
                            codigo_aghu=str(row.get('CODIGO AGHU', '')).strip(),
                            paciente=str(row.get('PACIENTE', '')).strip(),
                            telefone_cadastro=str(row.get('TELEFONE CADASTRO', '')).strip(),
                            telefone_registro=str(row.get('TELEFONE REGISTRO', '')).strip(),
                            data_registro=str(row.get('DATA DO REGISTRO', '')).strip(),
                            procedencia=str(row.get('PROCEDÊNCIA', '')).strip(),
                            medico_solicitante=str(row.get('MEDICO_SOLICITANTE', '') or row.get('MEDICO SOLICITANTE', '') or row.get('MEDICO', '')).strip(),
                            tipo=str(row.get('TIPO', '')).strip().upper(),  # RETORNO ou INTERCONSULTA
                            observacoes=str(row.get('OBSERVAÇÕES', '')).strip(),
                            exames=str(row.get('EXAMES', '')).strip(),
                            sub_especialidade=str(row.get('SUB-ESPECIALIDADE', '')).strip(),
                            especialidade=str(row.get('ESPECIALIDADE', '')).strip(),
                            grade_aghu=str(row.get('GRADE_AGHU', '')).strip(),
                            prioridade=str(row.get('PRIORIDADE', '')).strip(),
                            indicacao_data=str(row.get('INDICACAO DATA', '')).strip(),
                            data_requisicao=str(row.get('DATA REQUISIÇÃO', '')).strip(),
                            data_exata_ou_dias=str(row.get('DATA EXATA OU DIAS', '')).strip(),
                            estimativa_agendamento=str(row.get('ESTIMATIVA AGENDAMENTO', '')).strip(),
                            data_aghu=str(row.get('DATA AGHU', '')).strip(),
                            paciente_voltar_posto_sms=str(row.get('PACIENTE_VOLTAR_POSTO_SMS', '')).strip().upper(),
                            # Campos específicos para REMARCACAO
                            motivo_remarcacao=str(row.get('MOTIVO_REMARCACAO', '')).strip(),
                            data_anterior=str(row.get('DATA_ANTERIOR', '')).strip(),
                            status='AGUARDANDO_ENVIO',
                            # Campos de retry tracking (inicializar com valores padrão)
                            tentativas_contato=0,
                            data_ultima_tentativa=None,
                            cancelado_sem_resposta=False
                        )

                        if not consulta.paciente:
                            logger.warning(f"Linha {idx+2}: Paciente vazio, pulando")
                            continue

                        # Normalizar tipo INTERCONSULTA (aceitar variações)
                        if 'INTERCONSULTA' in consulta.tipo:
                            consulta.tipo = 'INTERCONSULTA'
                            # Para INTERCONSULTA, ignorar campo EXAMES (pode conter data de registro)
                            consulta.exames = ''
                            logger.info(f"Linha {idx+2}: Tipo normalizado para INTERCONSULTA, campo exames ignorado")

                        # Validar tipo
                        if consulta.tipo not in ['RETORNO', 'INTERCONSULTA', 'REMARCACAO']:
                            logger.warning(f"Linha {idx+2}: Tipo inválido '{consulta.tipo}', ajustando para RETORNO")
                            consulta.tipo = 'RETORNO'

                        db.session.add(consulta)
                        db.session.flush()  # Para obter ID da consulta

                        # Criar telefones (com formatação)
                        # Suporta múltiplos números separados por " / " na mesma célula
                        prioridade_atual = 1
                        numeros_adicionados = set()  # Evitar duplicatas

                        if consulta.telefone_cadastro:
                            # Dividir por " / " caso haja múltiplos números
                            telefones_cadastro = [t.strip() for t in consulta.telefone_cadastro.split('/')]
                            for tel in telefones_cadastro:
                                if tel:
                                    numero_formatado = formatar_numero(tel)
                                    if numero_formatado and numero_formatado not in numeros_adicionados:
                                        tel_obj = TelefoneConsulta(
                                            consulta_id=consulta.id,
                                            numero=numero_formatado,
                                            prioridade=prioridade_atual
                                        )
                                        db.session.add(tel_obj)
                                        numeros_adicionados.add(numero_formatado)
                                        prioridade_atual += 1

                        if consulta.telefone_registro:
                            # Dividir por " / " caso haja múltiplos números
                            telefones_registro = [t.strip() for t in consulta.telefone_registro.split('/')]
                            for tel in telefones_registro:
                                if tel:
                                    numero_formatado = formatar_numero(tel)
                                    if numero_formatado and numero_formatado not in numeros_adicionados:
                                        tel_obj = TelefoneConsulta(
                                            consulta_id=consulta.id,
                                            numero=numero_formatado,
                                            prioridade=prioridade_atual
                                        )
                                        db.session.add(tel_obj)
                                        numeros_adicionados.add(numero_formatado)
                                        prioridade_atual += 1

                        consultas_criadas += 1

                    except Exception as e:
                        logger.error(f"Erro ao processar linha {idx+2}: {e}")
                        continue

                # Atualizar estatísticas da campanha
                campanha.total_consultas = consultas_criadas
                campanha.status = 'pronta' if consultas_criadas > 0 else 'erro'
                campanha.status_msg = f'{consultas_criadas} consultas importadas'

                db.session.commit()

                flash(f'Campanha criada com sucesso! {consultas_criadas} consultas importadas.', 'success')
                return redirect(url_for('consultas_campanha_detalhe', id=campanha.id))

            except Exception as e:
                db.session.rollback()
                logger.exception(f"Erro ao importar planilha: {e}")
                flash(f'Erro ao importar planilha: {str(e)}', 'danger')
                return redirect(request.url)

        return render_template('consultas_importar.html')


    # =========================================================================
    # DETALHES DA CAMPANHA
    # =========================================================================

    @app.route('/consultas/campanha/<int:id>')
    @login_required
    def consultas_campanha_detalhe(id):
        """Detalhes de uma campanha de consultas"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        # Verificar permissão
        if campanha.criador_id != current_user.id and not current_user.is_admin:
            flash('Acesso negado', 'danger')
            return redirect(url_for('consultas_dashboard'))

        # Atualizar estatísticas
        campanha.atualizar_stats()
        db.session.commit()

        # Filtro de status
        filtro = request.args.get('filtro', 'todos')

        # Query base
        query = AgendamentoConsulta.query.filter_by(campanha_id=id)

        # Aplicar filtro
        if filtro == 'aguardando_envio':
            query = query.filter_by(status='AGUARDANDO_ENVIO')
        elif filtro == 'aguardando_confirmacao':
            query = query.filter_by(status='AGUARDANDO_CONFIRMACAO')
        elif filtro == 'aguardando_comprovante':
            query = query.filter_by(status='AGUARDANDO_COMPROVANTE')
        elif filtro == 'confirmados':
            query = query.filter_by(status='CONFIRMADO')
        elif filtro == 'cancelados':
            query = query.filter_by(status='CANCELADO')
        elif filtro == 'rejeitados':
            query = query.filter_by(status='REJEITADO')

        consultas = query.order_by(AgendamentoConsulta.id).all()

        # Progresso da task (se estiver rodando)
        task_progress = None
        if campanha.celery_task_id and AsyncResult:
            try:
                result = AsyncResult(campanha.celery_task_id)
                if result.state == 'PROGRESS':
                    task_progress = result.info
                elif result.state == 'SUCCESS':
                    campanha.celery_task_id = None
                    db.session.commit()
            except Exception as e:
                logger.warning(f"Erro ao verificar progresso da task: {e}")

        return render_template(
            'campanha_consultas_detalhe.html',
            campanha=campanha,
            consultas=consultas,
            task_progress=task_progress,
            filtro=filtro
        )


    # =========================================================================
    # CONTROLE DE ENVIO
    # =========================================================================

    @app.route('/consultas/campanha/<int:id>/iniciar', methods=['POST'])
    @login_required
    def consultas_campanha_iniciar(id):
        """Inicia envio automático da campanha"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        if not enviar_campanha_consultas_task:
            flash('Celery não está disponível', 'danger')
            return redirect(url_for('consultas_campanha_detalhe', id=id))

        try:
            # VALIDAÇÃO CRÍTICA: Verificar se a campanha pertence a usuário com WhatsApp
            from app import ConfigWhatsApp
            config_whatsapp = ConfigWhatsApp.query.filter_by(usuario_id=campanha.criador_id).first()
            if not config_whatsapp:
                flash(f'❌ ERRO CRÍTICO: A campanha foi criada por um usuário (ID {campanha.criador_id}) que não tem WhatsApp configurado! '
                      f'Não é possível enviar mensagens. Contate o administrador.', 'danger')
                return redirect(url_for('consultas_campanha_detalhe', id=id))

            # Verificar WhatsApp do usuário atual (se for diferente do criador)
            if current_user.id != campanha.criador_id:
                # Admin tentando iniciar campanha de outro usuário
                # Usar o WhatsApp do criador da campanha
                ws = WhatsApp(campanha.criador_id)
            else:
                ws = WhatsApp(current_user.id)

            if not ws.ok():
                flash('Configure o WhatsApp antes de iniciar. Acesse Configurações no menu superior.', 'warning')
                return redirect(url_for('consultas_dashboard'))

            conn, _ = ws.conectado()
            if not conn:
                flash('WhatsApp desconectado. Acesse Configurações no menu superior para conectar.', 'warning')
                return redirect(url_for('consultas_dashboard'))

            # Iniciar task
            task = enviar_campanha_consultas_task.delay(campanha.id)
            campanha.celery_task_id = task.id
            campanha.status = 'enviando'
            campanha.status_msg = 'Iniciando envio...'
            db.session.commit()

            flash('Envio iniciado!', 'success')

        except Exception as e:
            logger.exception(f"Erro ao iniciar envio: {e}")
            flash(f'Erro ao iniciar envio: {str(e)}', 'danger')

        return redirect(url_for('consultas_campanha_detalhe', id=id))


    @app.route('/consultas/campanha/<int:id>/pausar', methods=['POST'])
    @login_required
    def consultas_campanha_pausar(id):
        """Pausa envio da campanha"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        campanha.status = 'pausado'
        campanha.status_msg = 'Pausado pelo usuário'
        db.session.commit()

        flash('Campanha pausada', 'info')
        return redirect(url_for('consultas_campanha_detalhe', id=id))


    @app.route('/consultas/campanha/<int:id>/continuar', methods=['POST'])
    @login_required
    def consultas_campanha_continuar(id):
        """Continua envio pausado"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        if not enviar_campanha_consultas_task:
            flash('Celery não está disponível', 'danger')
            return redirect(url_for('consultas_campanha_detalhe', id=id))

        try:
            # Reiniciar task
            task = enviar_campanha_consultas_task.delay(campanha.id)
            campanha.celery_task_id = task.id
            campanha.status = 'enviando'
            campanha.status_msg = 'Retomando envio...'
            db.session.commit()

            flash('Envio retomado!', 'success')

        except Exception as e:
            logger.exception(f"Erro ao continuar envio: {e}")
            flash(f'Erro ao continuar envio: {str(e)}', 'danger')

        return redirect(url_for('consultas_campanha_detalhe', id=id))


    # =========================================================================
    # DETALHES DA CONSULTA INDIVIDUAL
    # =========================================================================

    @app.route('/consultas/consulta/<int:id>')
    @login_required
    def consulta_detalhe(id):
        """Detalhes de uma consulta individual"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        # Verificar permissão
        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            flash('Acesso negado', 'danger')
            return redirect(url_for('consultas_dashboard'))

        # Buscar logs de mensagens
        logs = LogMsgConsulta.query.filter_by(consulta_id=consulta.id).order_by(LogMsgConsulta.data.asc()).all()

        # Buscar telefones
        telefones = TelefoneConsulta.query.filter_by(consulta_id=consulta.id).all()

        return render_template('consulta_detalhe.html', consulta=consulta, logs=logs, telefones=telefones)


    # =========================================================================
    # DOWNLOAD PÚBLICO DE COMPROVANTE (via link)
    # =========================================================================

    @app.route('/consulta/comprovante/<int:consulta_id>')
    def download_comprovante_publico(consulta_id):
        """
        Endpoint PÚBLICO para download de comprovante via link.
        Válido por 7 dias após envio.
        """
        from datetime import timedelta

        consulta = AgendamentoConsulta.query.get_or_404(consulta_id)

        # Verificar se comprovante existe
        if not consulta.comprovante_path or not os.path.exists(consulta.comprovante_path):
            return "Comprovante não encontrado", 404

        # Verificar se tem data de confirmação (obrigatório para link funcionar)
        if not consulta.data_confirmacao:
            return "Comprovante ainda não foi enviado oficialmente", 400

        # Verificar se ainda está dentro do prazo (7 dias)
        sete_dias_atras = datetime.utcnow() - timedelta(days=7)
        if consulta.data_confirmacao < sete_dias_atras:
            return "Link expirado. O comprovante ficou disponível por 7 dias.", 410

        # Servir arquivo
        try:
            return send_file(
                consulta.comprovante_path,
                as_attachment=True,
                download_name=consulta.comprovante_nome or 'comprovante.pdf',
                mimetype='application/pdf'
            )
        except Exception as e:
            logger.error(f"Erro ao enviar comprovante público: {e}")
            return "Erro ao baixar comprovante", 500


    # =========================================================================
    # ENVIAR COMPROVANTE (MSG 2)
    # =========================================================================

    @app.route('/api/consulta/<int:id>/enviar_comprovante', methods=['POST'])
    @login_required
    def consulta_enviar_comprovante(id):
        """Envia comprovante (PDF/JPG) para o paciente (MSG 2) - ASSÍNCRONO"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        if consulta.status != 'AGUARDANDO_COMPROVANTE':
            return jsonify({'erro': f'Status inválido: {consulta.status}. Comprovante já foi enviado?'}), 400

        # PROTEÇÃO CONTRA ENVIO MÚLTIPLO: verificar se já enviou nos últimos 30 segundos
        from datetime import timedelta
        trinta_segundos_atras = datetime.utcnow() - timedelta(seconds=30)
        envio_recente = LogMsgConsulta.query.filter(
            LogMsgConsulta.consulta_id == consulta.id,
            LogMsgConsulta.direcao == 'enviada',
            LogMsgConsulta.mensagem.like('%COMPROVANTE%'),
            LogMsgConsulta.data >= trinta_segundos_atras
        ).first()

        if envio_recente:
            return jsonify({'erro': 'Comprovante já foi enviado recentemente. Aguarde alguns segundos.'}), 400

        try:
            # Validar arquivo
            if 'comprovante' not in request.files:
                return jsonify({'erro': 'Nenhum arquivo enviado'}), 400

            arquivo = request.files['comprovante']
            if arquivo.filename == '':
                return jsonify({'erro': 'Nenhum arquivo selecionado'}), 400

            # Validar extensão
            ext = os.path.splitext(arquivo.filename)[1].lower()
            if ext not in ['.pdf', '.jpg', '.jpeg', '.png']:
                return jsonify({'erro': 'Formato inválido. Use PDF, JPG ou PNG'}), 400

            # Salvar arquivo
            filename = secure_filename(f'comprovante_{consulta.id}_{datetime.now().strftime("%Y%m%d%H%M%S")}{ext}')
            filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            arquivo.save(filepath)

            # Verificar WhatsApp antes de continuar
            ws = WhatsApp(consulta.usuario_id)
            if not ws.ok():
                return jsonify({'erro': 'WhatsApp não configurado'}), 500

            # Buscar telefone - PRIORITIZAR o que confirmou (telefone_confirmacao)
            telefone = None
            if consulta.telefone_confirmacao:
                telefone = consulta.telefone_confirmacao
            else:
                for tel in consulta.telefones:
                    if tel.enviado:
                        telefone = tel.numero
                        break

            if not telefone:
                return jsonify({'erro': 'Nenhum telefone válido encontrado'}), 400

            # Capturar base_url antes de sair do contexto da requisição
            base_url = request.url_root.rstrip('/')

            # Atualizar consulta IMEDIATAMENTE (resposta rápida pro usuário)
            consulta.comprovante_path = filepath
            consulta.comprovante_nome = filename
            consulta.status = 'CONFIRMADO'
            consulta.data_confirmacao = datetime.utcnow()
            db.session.commit()

            # Atualizar stats da campanha
            consulta.campanha.atualizar_stats()
            db.session.commit()

            # Iniciar envio em background (OCR + mensagens + arquivo + pesquisa)
            t = threading.Thread(
                target=enviar_comprovante_background,
                args=(current_user.id, consulta.id, filepath, telefone, base_url)
            )
            t.daemon = True
            t.start()
            logger.info(f"Thread de envio de comprovante iniciada para consulta {consulta.id}")

            return jsonify({'sucesso': True, 'mensagem': 'Comprovante salvo! Enviando para o paciente em segundo plano...'})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao enviar comprovante: {e}")
            return jsonify({'erro': str(e)}), 500


    @app.route('/api/consulta/<int:consulta_id>/reagendar', methods=['POST'])
    @login_required
    def reagendar_consulta_manual(consulta_id):
        """
        Processa o reagendamento manual de uma consulta.
        O admin informa nova data/hora. O sistema envia msg confirmando.
        """
        consulta = AgendamentoConsulta.query.get_or_404(consulta_id)
        
        # Verificar permissão (mesmo criador)
        if consulta.campanha.criador_id != current_user.id:
            return jsonify({'erro': 'Acesso negado'}), 403

        data = request.json
        nova_data = data.get('nova_data')
        nova_hora = data.get('nova_hora')

        if not nova_data or not nova_hora:
            return jsonify({'erro': 'Data e hora são obrigatórios'}), 400

        try:
            # 1. Atualizar consulta
            consulta.status = 'REAGENDADO'
            consulta.nova_data = nova_data
            consulta.nova_hora = nova_hora
            consulta.data_reagendamento = datetime.utcnow()
            
            # Buscar telefone válido
            telefone = None
            for tel in consulta.telefones:
                if tel.enviado or tel.prioridade == 1:
                    telefone = tel.numero
                    break
            
            if not telefone:
                 telefone = consulta.telefones[0].numero if consulta.telefones else None
            
            if not telefone:
                return jsonify({'erro': 'Consulta sem telefone'}), 400

            # 2. Enviar mensagem de confirmação do reagendamento
            msg_reagendamento = f"""📅 *CONSULTA REAGENDADA!*

Olá, {consulta.paciente}!

Conseguimos uma nova data para sua consulta.

🗓 *Nova Data:* {nova_data}
⏰ *Horário:* {nova_hora}
👨‍⚕️ *Especialidade:* {consulta.especialidade}

Por favor, confirme se poderá comparecer respondendo:
1️⃣ *SIM* - Confirmar
2️⃣ *NÃO* - Não posso ir

_Hospital Universitário Walter Cantídio_"""

            ws = WhatsApp(current_user.id)
            ok, result = ws.enviar(telefone, msg_reagendamento)
            
            if ok:
                consulta.mensagem_enviada = True 
                enviar_e_registrar_consulta(ws, telefone, msg_reagendamento, consulta)
            
            db.session.commit()
            
            return jsonify({'sucesso': True, 'mensagem': 'Reagendado com sucesso!'})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao reagendar: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # AÇÕES MANUAIS
    # =========================================================================

    @app.route('/api/consulta/<int:id>/confirmar', methods=['POST'])
    @login_required
    def consulta_confirmar_manual(id):
        """Confirma consulta manualmente (sem comprovante)"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        # Validar status - só pode confirmar se está aguardando
        if consulta.status in ['CONFIRMADO', 'REJEITADO']:
            return jsonify({'erro': f'Consulta já está {consulta.status}'}), 400

        try:
            consulta.status = 'CONFIRMADO'
            consulta.data_confirmacao = datetime.utcnow()
            db.session.commit()

            consulta.campanha.atualizar_stats()
            db.session.commit()

            return jsonify({'sucesso': True})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao confirmar consulta: {e}")
            return jsonify({'erro': str(e)}), 500


    @app.route('/api/consulta/<int:id>/cancelar', methods=['POST'])
    @login_required
    def consulta_cancelar_manual(id):
        """Cancela/rejeita consulta manualmente"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        # Validar status - não pode cancelar se já está finalizado
        if consulta.status in ['CONFIRMADO', 'REJEITADO']:
            return jsonify({'erro': f'Consulta já está {consulta.status}'}), 400

        try:
            motivo = request.json.get('motivo', 'Cancelado manualmente') if request.json else 'Cancelado manualmente'

            consulta.status = 'REJEITADO'
            consulta.motivo_rejeicao = motivo
            consulta.data_rejeicao = datetime.utcnow()
            db.session.commit()

            consulta.campanha.atualizar_stats()
            db.session.commit()

            return jsonify({'sucesso': True})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao cancelar consulta: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # PROGRESSO E MONITORAMENTO
    # =========================================================================

    @app.route('/consultas/campanha/<int:id>/progresso')
    @login_required
    def consultas_campanha_progresso(id):
        """Página de progresso do envio da campanha"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            flash('Acesso negado', 'danger')
            return redirect(url_for('consultas_dashboard'))

        task_id = request.args.get('task_id') or campanha.celery_task_id

        if not task_id:
            flash('Task ID não encontrado', 'warning')
            return redirect(url_for('consultas_dashboard'))

        return render_template('progresso_campanha_consultas.html', campanha=campanha, task_id=task_id)


    # =========================================================================
    # APIs PARA DETALHES E CHAT
    # =========================================================================

    @app.route('/api/consulta/<int:id>/detalhes', methods=['GET'])
    @login_required
    def consulta_detalhes_api(id):
        """API: Retorna detalhes e histórico de mensagens de uma consulta"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        # Buscar logs de mensagens
        logs = LogMsgConsulta.query.filter_by(consulta_id=consulta.id).order_by(LogMsgConsulta.data.asc()).all()

        logs_data = []
        for log in logs:
            logs_data.append({
                'id': log.id,
                'direcao': log.direcao,
                'mensagem': log.mensagem,
                'telefone': log.telefone,
                'status': log.status,
                'erro': log.erro,
                'data': log.data.strftime('%d/%m/%Y %H:%M:%S') if log.data else None
            })

        # Dados da consulta
        consulta_data = {
            'id': consulta.id,
            'paciente': consulta.paciente,
            'tipo': consulta.tipo,
            'status': consulta.status,
            'telefones': [t.numero for t in consulta.telefones],
            'medico_solicitante': consulta.medico_solicitante,
            'especialidade': consulta.especialidade,
            'data_aghu': consulta.data_aghu,  # Data da consulta (string)
            'observacoes': consulta.observacoes,
            'motivo_rejeicao': consulta.motivo_rejeicao,
            'data_envio': consulta.data_envio_mensagem.strftime('%d/%m/%Y %H:%M:%S') if consulta.data_envio_mensagem else None,
            'logs': logs_data
        }

        return jsonify(consulta_data)


    @app.route('/api/consulta/<int:id>/enviar_mensagem', methods=['POST'])
    @login_required
    def consulta_enviar_mensagem_manual(id):
        """API: Envia mensagem manual para uma consulta"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        try:
            mensagem = request.json.get('mensagem', '').strip()
            telefone_selecionado = request.json.get('telefone', '').strip()

            if not mensagem:
                return jsonify({'erro': 'Mensagem vazia'}), 400

            # Buscar WhatsApp do usuário
            ws = WhatsApp(current_user.id)
            if not ws.ok():
                return jsonify({'erro': 'WhatsApp não configurado'}), 400

            conn, _ = ws.conectado()
            if not conn:
                return jsonify({'erro': 'WhatsApp desconectado'}), 400

            # Usar telefone selecionado ou pegar o primeiro disponível
            if not consulta.telefones:
                return jsonify({'erro': 'Nenhum telefone disponível'}), 400

            # Validar se o telefone selecionado pertence à consulta
            telefone = None
            if telefone_selecionado:
                for tel in consulta.telefones:
                    if tel.numero == telefone_selecionado:
                        telefone = tel.numero
                        break
                if not telefone:
                    return jsonify({'erro': 'Telefone selecionado não pertence a esta consulta'}), 400
            else:
                telefone = consulta.telefones[0].numero

            # Enviar mensagem
            ok, result = ws.enviar(telefone, mensagem)

            if ok:
                # Log de sucesso
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='enviada',
                    telefone=telefone,
                    mensagem=mensagem[:500],
                    status='sucesso',
                    msg_id=result
                )
                db.session.add(log)
                db.session.commit()

                return jsonify({
                    'sucesso': True,
                    'mensagem': 'Mensagem enviada com sucesso'
                })
            else:
                # Log de erro
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='enviada',
                    telefone=telefone,
                    mensagem=mensagem[:500],
                    status='erro',
                    erro=str(result)[:200]
                )
                db.session.add(log)
                db.session.commit()

                return jsonify({'erro': f'Erro ao enviar: {result}'}), 500

        except Exception as e:
            logger.exception(f"Erro ao enviar mensagem manual: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # EXCLUIR CONSULTA
    # =========================================================================

    @app.route('/api/consulta/<int:id>/excluir', methods=['DELETE', 'POST'])
    @login_required
    def consulta_excluir(id):
        """Exclui uma consulta individual"""
        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        try:
            campanha_id = consulta.campanha_id

            # Excluir logs relacionados
            LogMsgConsulta.query.filter_by(consulta_id=consulta.id).delete()

            # Excluir telefones relacionados
            TelefoneConsulta.query.filter_by(consulta_id=consulta.id).delete()

            # Excluir a consulta
            db.session.delete(consulta)
            db.session.commit()

            # Atualizar stats da campanha
            campanha = CampanhaConsulta.query.get(campanha_id)
            if campanha:
                campanha.atualizar_stats()
                db.session.commit()

            return jsonify({'sucesso': True, 'mensagem': 'Consulta excluída com sucesso'})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao excluir consulta: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # REENVIAR MENSAGEM DE CONFIRMAÇÃO
    # =========================================================================

    @app.route('/api/consulta/<int:id>/reenviar', methods=['POST'])
    @login_required
    def consulta_reenviar(id):
        """Reenvia mensagem de confirmação para uma consulta"""
        from app import formatar_mensagem_consulta_inicial

        consulta = AgendamentoConsulta.query.get_or_404(id)

        if consulta.usuario_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        # Validar status - só pode reenviar se não está finalizado
        if consulta.status in ['CONFIRMADO', 'REJEITADO']:
            return jsonify({'erro': f'Não é possível reenviar. Consulta já está {consulta.status}'}), 400

        try:
            # Verificar WhatsApp
            ws = WhatsApp(consulta.usuario_id)
            if not ws.ok():
                return jsonify({'erro': 'WhatsApp não configurado'}), 400

            conn, _ = ws.conectado()
            if not conn:
                return jsonify({'erro': 'WhatsApp desconectado'}), 400

            # Buscar telefone
            telefone = None
            for tel in consulta.telefones:
                if tel.numero:
                    telefone = tel.numero
                    break

            if not telefone:
                return jsonify({'erro': 'Nenhum telefone disponível'}), 400

            # Formatar mensagem (usa o objeto consulta diretamente)
            msg = formatar_mensagem_consulta_inicial(consulta)

            # Enviar mensagem
            ok, result = ws.enviar(telefone, msg)

            if ok:
                # Atualizar status
                consulta.status = 'AGUARDANDO_CONFIRMACAO'
                consulta.data_envio_mensagem = datetime.utcnow()

                # Log de sucesso
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='enviada',
                    telefone=telefone,
                    mensagem=msg[:500],
                    status='sucesso',
                    msg_id=result
                )
                db.session.add(log)

                # Marcar telefone como enviado e atualizar data_envio
                for tel in consulta.telefones:
                    if tel.numero == telefone:
                        tel.enviado = True
                        tel.data_envio = datetime.utcnow()
                        break

                db.session.commit()

                # Atualizar stats
                consulta.campanha.atualizar_stats()
                db.session.commit()

                return jsonify({'sucesso': True, 'mensagem': 'Mensagem reenviada com sucesso'})
            else:
                # Log de erro
                log = LogMsgConsulta(
                    campanha_id=consulta.campanha_id,
                    consulta_id=consulta.id,
                    direcao='enviada',
                    telefone=telefone,
                    mensagem=msg[:500],
                    status='erro',
                    erro=str(result)[:200]
                )
                db.session.add(log)
                db.session.commit()

                return jsonify({'erro': f'Erro ao enviar: {result}'}), 500

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao reenviar mensagem: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # EDITAR CAMPANHA
    # =========================================================================

    @app.route('/api/consultas/campanha/<int:id>/editar', methods=['POST'])
    @login_required
    def consultas_campanha_editar(id):
        """Edita configurações da campanha"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        try:
            data = request.json or {}

            # Atualizar campos permitidos
            if 'nome' in data:
                campanha.nome = data['nome'].strip()

            if 'descricao' in data:
                campanha.descricao = data['descricao'].strip()

            if 'meta_diaria' in data:
                campanha.meta_diaria = int(data['meta_diaria'])

            if 'hora_inicio' in data:
                campanha.hora_inicio = int(data['hora_inicio'])

            if 'hora_fim' in data:
                campanha.hora_fim = int(data['hora_fim'])

            if 'tempo_entre_envios' in data:
                campanha.tempo_entre_envios = int(data['tempo_entre_envios'])

            db.session.commit()

            return jsonify({
                'sucesso': True,
                'mensagem': 'Campanha atualizada com sucesso',
                'campanha': {
                    'id': campanha.id,
                    'nome': campanha.nome,
                    'descricao': campanha.descricao,
                    'meta_diaria': campanha.meta_diaria,
                    'hora_inicio': campanha.hora_inicio,
                    'hora_fim': campanha.hora_fim,
                    'tempo_entre_envios': campanha.tempo_entre_envios
                }
            })

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao editar campanha: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # EXCLUIR CAMPANHA
    # =========================================================================

    @app.route('/api/consultas/campanha/<int:id>/excluir', methods=['DELETE', 'POST'])
    @login_required
    def consultas_campanha_excluir(id):
        """Exclui uma campanha e todas as suas consultas"""
        campanha = CampanhaConsulta.query.get_or_404(id)

        if campanha.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'Acesso negado'}), 403

        try:
            # Buscar todas as consultas da campanha
            consultas = AgendamentoConsulta.query.filter_by(campanha_id=campanha.id).all()

            for consulta in consultas:
                # Excluir logs
                LogMsgConsulta.query.filter_by(consulta_id=consulta.id).delete()
                # Excluir telefones
                TelefoneConsulta.query.filter_by(consulta_id=consulta.id).delete()

            # Excluir logs da campanha (que não têm consulta específica)
            LogMsgConsulta.query.filter_by(campanha_id=campanha.id).delete()

            # Excluir todas as consultas
            AgendamentoConsulta.query.filter_by(campanha_id=campanha.id).delete()

            # Excluir a campanha
            db.session.delete(campanha)
            db.session.commit()

            return jsonify({'sucesso': True, 'mensagem': 'Campanha excluída com sucesso'})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao excluir campanha: {e}")
            return jsonify({'erro': str(e)}), 500


    # =========================================================================
    # PESQUISAS DE SATISFAÇÃO - Dashboard
    # =========================================================================

    @app.route('/consultas/pesquisas')
    @login_required
    def pesquisas_dashboard():
        """Dashboard de pesquisas de satisfação"""
        from sqlalchemy import func
        
        # Buscar pesquisas do usuário
        pesquisas = PesquisaSatisfacao.query.filter_by(usuario_id=current_user.id).order_by(PesquisaSatisfacao.data_resposta.desc()).all()
        
        # Calcular estatísticas
        total = len(pesquisas)
        respondidas = len([p for p in pesquisas if not p.pulou])
        puladas = len([p for p in pesquisas if p.pulou])
        
        # Média de notas (NPS)
        notas = [p.nota_satisfacao for p in pesquisas if p.nota_satisfacao is not None]
        media_nota = round(sum(notas) / len(notas), 1) if notas else 0
        
        # % atendimento ágil
        atenciosos = [p for p in pesquisas if p.equipe_atenciosa is not None]
        pct_agil = round(len([p for p in atenciosos if p.equipe_atenciosa]) / len(atenciosos) * 100, 1) if atenciosos else 0
        
        # Comentários recentes
        comentarios = [p for p in pesquisas if p.comentario and len(p.comentario.strip()) > 0][:10]
        
        # Especialidades para filtro
        especialidades = list(set([p.especialidade for p in pesquisas if p.especialidade]))
        especialidades.sort()
        
        return render_template('pesquisas_dashboard.html',
            pesquisas=pesquisas,
            total=total,
            respondidas=respondidas,
            puladas=puladas,
            media_nota=media_nota,
            pct_agil=pct_agil,
            comentarios=comentarios,
            especialidades=especialidades
        )

    @app.route('/api/consultas/pesquisas/export')
    @login_required
    def pesquisas_export_csv():
        """Exportar pesquisas para CSV"""
        import csv
        from io import StringIO
        
        pesquisas = PesquisaSatisfacao.query.filter_by(usuario_id=current_user.id).order_by(PesquisaSatisfacao.data_resposta.desc()).all()
        
        output = StringIO()
        writer = csv.writer(output)
        
        # Header
        writer.writerow(['Data', 'Especialidade', 'Tipo', 'Nota', 'Equipe Ágil', 'Comentário', 'Pulou'])
        
        for p in pesquisas:
            writer.writerow([
                p.data_resposta.strftime('%d/%m/%Y %H:%M') if p.data_resposta else '',
                p.especialidade or '',
                p.tipo_agendamento or '',
                p.nota_satisfacao or '',
                'Sim' if p.equipe_atenciosa else ('Não' if p.equipe_atenciosa is False else ''),
                p.comentario or '',
                'Sim' if p.pulou else 'Não'
            ])
        
        output.seek(0)
        
        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=pesquisas_satisfacao.csv'}
        )


    # =========================================================================
    # HISTÓRICO DE CONSULTAS - Visualização de pacientes e seus históricos
    # =========================================================================

    @app.route('/consultas/historico')
    @login_required
    def consultas_historico():
        """Página de histórico de consultas dos pacientes"""
        tipo_sistema = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
        if tipo_sistema != 'AGENDAMENTO_CONSULTA':
            flash('Acesso negado. Usuário configurado para Fila Cirúrgica.', 'warning')
            return redirect(url_for('dashboard'))

        # Parâmetros de filtro
        filtro_paciente = request.args.get('paciente', '').strip()
        filtro_especialidade = request.args.get('especialidade', '').strip()
        filtro_data_inicio = request.args.get('data_inicio', '').strip()
        filtro_data_fim = request.args.get('data_fim', '').strip()

        # Query base - pacientes do usuário
        pacientes_query = Paciente.query.filter_by(usuario_id=current_user.id)

        if filtro_paciente:
            pacientes_query = pacientes_query.filter(Paciente.nome.ilike(f'%{filtro_paciente}%'))

        pacientes = pacientes_query.order_by(Paciente.nome).all()

        # Buscar históricos com filtros
        historicos_query = HistoricoConsulta.query.filter_by(usuario_id=current_user.id)

        if filtro_especialidade:
            historicos_query = historicos_query.filter(HistoricoConsulta.especialidade.ilike(f'%{filtro_especialidade}%'))

        if filtro_data_inicio:
            historicos_query = historicos_query.filter(HistoricoConsulta.data_consulta >= filtro_data_inicio)

        if filtro_data_fim:
            historicos_query = historicos_query.filter(HistoricoConsulta.data_consulta <= filtro_data_fim)

        historicos = historicos_query.order_by(HistoricoConsulta.data_consulta.desc()).all()

        # Estatísticas
        total_pacientes = Paciente.query.filter_by(usuario_id=current_user.id).count()
        total_historicos = HistoricoConsulta.query.filter_by(usuario_id=current_user.id).count()

        # Lista de especialidades para filtro
        especialidades = db.session.query(HistoricoConsulta.especialidade).filter(
            HistoricoConsulta.usuario_id == current_user.id,
            HistoricoConsulta.especialidade.isnot(None)
        ).distinct().all()
        especialidades = [e[0] for e in especialidades if e[0]]

        return render_template(
            'historico_consultas.html',
            pacientes=pacientes,
            historicos=historicos,
            total_pacientes=total_pacientes,
            total_historicos=total_historicos,
            especialidades=especialidades,
            filtro_paciente=filtro_paciente,
            filtro_especialidade=filtro_especialidade,
            filtro_data_inicio=filtro_data_inicio,
            filtro_data_fim=filtro_data_fim
        )


    @app.route('/consultas/historico/paciente/<int:id>')
    @login_required
    def consultas_historico_paciente(id):
        """Detalhes do histórico de um paciente específico"""
        paciente = Paciente.query.get_or_404(id)

        if paciente.usuario_id != current_user.id:
            flash('Acesso negado', 'danger')
            return redirect(url_for('consultas_historico'))

        # Buscar todo o histórico do paciente
        historicos = HistoricoConsulta.query.filter_by(
            paciente_id=paciente.id
        ).order_by(HistoricoConsulta.data_consulta.desc()).all()

        return render_template(
            'historico_paciente_detalhe.html',
            paciente=paciente,
            historicos=historicos
        )


    @app.route('/api/consultas/historico/export')
    @login_required
    def historico_export_csv():
        """Exportar histórico de consultas para CSV"""
        import csv
        from io import StringIO

        historicos = HistoricoConsulta.query.filter_by(
            usuario_id=current_user.id
        ).order_by(HistoricoConsulta.data_consulta.desc()).all()

        output = StringIO()
        writer = csv.writer(output)

        # Header
        writer.writerow([
            'Paciente', 'Data Consulta', 'Hora', 'Especialidade', 'Profissional',
            'Unidade', 'Tipo Consulta', 'Tipo Demanda', 'Nro Consulta'
        ])

        for h in historicos:
            paciente_nome = h.paciente.nome if h.paciente else 'N/A'
            writer.writerow([
                paciente_nome,
                h.data_consulta or '',
                h.hora_consulta or '',
                h.especialidade or '',
                h.profissional or '',
                h.unidade_funcional or '',
                h.tipo_consulta or '',
                h.tipo_demanda or '',
                h.nro_consulta or ''
            ])

        output.seek(0)

        from flask import Response
        return Response(
            output.getvalue(),
            mimetype='text/csv',
            headers={'Content-Disposition': 'attachment; filename=historico_consultas.csv'}
        )


    logger.info("Rotas do modo consulta inicializadas com sucesso")
