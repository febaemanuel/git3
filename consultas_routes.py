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
        LogMsgConsulta, WhatsApp,
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
        if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
            flash('Acesso negado. Usuário configurado para Fila Cirúrgica.', 'warning')
            return redirect(url_for('dashboard'))

        campanhas = CampanhaConsulta.query.filter_by(
            criador_id=current_user.id
        ).order_by(CampanhaConsulta.data_criacao.desc()).all()

        # Atualizar estatísticas de cada campanha
        for camp in campanhas:
            camp.atualizar_stats()
        db.session.commit()

        return render_template('consultas_dashboard.html', campanhas=campanhas)


    # =========================================================================
    # IMPORTAR PLANILHA
    # =========================================================================

    @app.route('/consultas/importar', methods=['GET', 'POST'])
    @login_required
    def consultas_importar():
        """Importa planilha Excel com consultas"""
        if current_user.tipo_sistema != 'AGENDAMENTO_CONSULTA':
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

                        # Criar telefones
                        if consulta.telefone_cadastro:
                            tel1 = TelefoneConsulta(
                                consulta_id=consulta.id,
                                numero=consulta.telefone_cadastro,
                                prioridade=1
                            )
                            db.session.add(tel1)

                        if consulta.telefone_registro and consulta.telefone_registro != consulta.telefone_cadastro:
                            tel2 = TelefoneConsulta(
                                consulta_id=consulta.id,
                                numero=consulta.telefone_registro,
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

        # Buscar consultas
        consultas = AgendamentoConsulta.query.filter_by(
            campanha_id=id
        ).order_by(AgendamentoConsulta.id).all()

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
            task_progress=task_progress
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
            # Verificar WhatsApp
            ws = WhatsApp(current_user.id)
            if not ws.ok():
                flash('Configure o WhatsApp antes de iniciar', 'warning')
                return redirect(url_for('config_whatsapp'))

            conn, _ = ws.conectado()
            if not conn:
                flash('WhatsApp desconectado. Conecte antes de iniciar.', 'warning')
                return redirect(url_for('conectar_whatsapp'))

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

        return render_template('consulta_detalhe.html', consulta=consulta)


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
            return jsonify({'erro': f'Status inválido: {consulta.status}'}), 400

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


    logger.info("Rotas do modo consulta inicializadas com sucesso")
