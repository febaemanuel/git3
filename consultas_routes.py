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
        formatar_mensagem_comprovante, formatar_mensagem_voltar_posto
    )

    try:
        from celery.result import AsyncResult
        from tasks import enviar_campanha_consultas_task
    except ImportError:
        AsyncResult = None
        enviar_campanha_consultas_task = None
        logger.warning("Celery não disponível para modo consulta")


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
                            medico_solicitante=str(row.get('MEDICO_SOLICITANTE', '')).strip(),
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
                            status='AGUARDANDO_ENVIO'
                        )

                        if not consulta.paciente:
                            logger.warning(f"Linha {idx+2}: Paciente vazio, pulando")
                            continue

                        if consulta.tipo not in ['RETORNO', 'INTERCONSULTA']:
                            logger.warning(f"Linha {idx+2}: Tipo inválido '{consulta.tipo}', ajustando para RETORNO")
                            consulta.tipo = 'RETORNO'

                        db.session.add(consulta)
                        db.session.flush()  # Para obter ID da consulta

                        # Criar telefones (com formatação)
                        if consulta.telefone_cadastro:
                            numero_formatado = formatar_numero(consulta.telefone_cadastro)
                            if numero_formatado:
                                tel1 = TelefoneConsulta(
                                    consulta_id=consulta.id,
                                    numero=numero_formatado,
                                    prioridade=1
                                )
                                db.session.add(tel1)

                        if consulta.telefone_registro and consulta.telefone_registro != consulta.telefone_cadastro:
                            numero_formatado = formatar_numero(consulta.telefone_registro)
                            if numero_formatado:
                                tel2 = TelefoneConsulta(
                                    consulta_id=consulta.id,
                                    numero=numero_formatado,
                                    prioridade=2
                                )
                                db.session.add(tel2)

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
    # ENVIAR COMPROVANTE (MSG 2)
    # =========================================================================

    @app.route('/api/consulta/<int:id>/enviar_comprovante', methods=['POST'])
    @login_required
    def consulta_enviar_comprovante(id):
        """Envia comprovante (PDF/JPG) para o paciente (MSG 2)"""
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

            # Enviar MSG 2 com comprovante
            ws = WhatsApp(consulta.usuario_id)
            if not ws.ok():
                return jsonify({'erro': 'WhatsApp não configurado'}), 500

            # Buscar telefone válido
            telefone = None
            for tel in consulta.telefones:
                if tel.enviado:
                    telefone = tel.numero
                    break

            if not telefone:
                return jsonify({'erro': 'Nenhum telefone válido encontrado'}), 400

            # Enviar mensagem de texto
            msg = formatar_mensagem_comprovante()
            ok_msg, result_msg = ws.enviar(telefone, msg)

            if not ok_msg:
                return jsonify({'erro': f'Erro ao enviar mensagem: {result_msg}'}), 500

            # Enviar arquivo
            ok_file, result_file = ws.enviar_arquivo(telefone, filepath)

            if not ok_file:
                logger.warning(f"Erro ao enviar arquivo: {result_file}")
                # Continua mesmo se arquivo falhar

            # Atualizar consulta
            consulta.comprovante_path = filepath
            consulta.comprovante_nome = filename
            consulta.status = 'CONFIRMADO'
            consulta.data_confirmacao = datetime.utcnow()

            # Log
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

            # Atualizar stats da campanha
            consulta.campanha.atualizar_stats()
            db.session.commit()

            return jsonify({'sucesso': True, 'mensagem': 'Comprovante enviado com sucesso!'})

        except Exception as e:
            db.session.rollback()
            logger.exception(f"Erro ao enviar comprovante: {e}")
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


    logger.info("Rotas do modo consulta inicializadas com sucesso")
