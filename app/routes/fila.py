"""Fila cirúrgica (busca ativa) routes."""

import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, date
from io import BytesIO

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template,
    request, send_file, url_for,
)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename
import pandas as pd

from app.celery_compat import AsyncResult, celery_app
from app.extensions import db
from app.models import (
    Campanha, ConfigGlobal, ConfigTentativas, ConfigWhatsApp,
    Contato, LogMsg, RespostaAutomatica, Telefone, TentativaContato,
    TicketAtendimento, Tutorial, Usuario,
)
from app.seeds import criar_faqs_padrao, criar_tutoriais_padrao
from app.services.mensagem import (
    MENSAGEM_PADRAO,
    formatar_mensagem_fila_retry1, formatar_mensagem_fila_retry2,
    formatar_mensagem_fila_sem_resposta,
)
from app.services.planilha import processar_planilha
from app.services.telefone import formatar_numero
from app.services.timezone import (
    obter_agora_fortaleza, obter_hoje_fortaleza,
)
from app.services.whatsapp import WhatsApp
from app.utils import (
    admin_required, get_dashboard_route, verificar_acesso_campanha,
    verificar_acesso_contato, verificar_acesso_ticket,
)


logger = logging.getLogger(__name__)


bp = Blueprint('fila', __name__)


@bp.route('/dashboard')
@login_required
def dashboard():
    # Filtrar apenas campanhas do usuario atual
    camps = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()
    for c in camps:
        c.atualizar_stats()

    ws = WhatsApp(current_user.id)
    ws_ativo = ws.ok()
    ws_conn = False
    if ws_ativo:
        ws_conn, _ = ws.conectado()

    # Estatisticas apenas das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in camps]
    stats = {
        'campanhas': len(camps),
        'contatos': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids)).count() if user_campanhas_ids else 0,
        'confirmados': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids), Contato.confirmado == True).count() if user_campanhas_ids else 0,
        'rejeitados': Contato.query.filter(Contato.campanha_id.in_(user_campanhas_ids), Contato.rejeitado == True).count() if user_campanhas_ids else 0
    }

    return render_template('dashboard.html', campanhas=camps, whatsapp_ativo=ws_ativo,
                           whatsapp_conectado=ws_conn, mensagem_padrao=MENSAGEM_PADRAO, stats=stats)
@bp.route('/campanha/criar', methods=['POST'])
@login_required
def criar_campanha():
    nome = request.form.get('nome', '').strip()
    msg = request.form.get('mensagem', MENSAGEM_PADRAO).strip()
    tempo = int(request.form.get('tempo_entre_envios', 15))

    # Novos campos de agendamento
    meta_diaria = int(request.form.get('meta_diaria', 50))
    horario_inicio = request.form.get('horario_inicio', '08:00')
    horario_fim = request.form.get('horario_fim', '18:00')
    dias_duracao = int(request.form.get('dias_duracao', 0))

    # Extrair hora dos horários (formato HH:MM)
    hora_inicio = int(horario_inicio.split(':')[0]) if horario_inicio else 8
    hora_fim = int(horario_fim.split(':')[0]) if horario_fim else 18

    if not nome:
        flash('Nome obrigatorio', 'danger')
        return redirect(url_for(get_dashboard_route()))

    if 'arquivo' not in request.files or not request.files['arquivo'].filename:
        flash('Selecione arquivo Excel', 'danger')
        return redirect(url_for(get_dashboard_route()))

    arq = request.files['arquivo']
    if not arq.filename.lower().endswith(('.xlsx', '.xls')):
        flash('Arquivo deve ser Excel', 'danger')
        return redirect(url_for(get_dashboard_route()))

    camp = Campanha(
        nome=nome,
        descricao=request.form.get('descricao', ''),
        mensagem=msg,
        limite_diario=meta_diaria,  # Usar meta_diaria como limite_diario
        tempo_entre_envios=tempo,
        meta_diaria=meta_diaria,
        hora_inicio=hora_inicio,
        hora_fim=hora_fim,
        dias_duracao=dias_duracao,
        criador_id=current_user.id,
        arquivo=arq.filename,
        status='processando',
        status_msg='Aguardando processamento...'
    )
    db.session.add(camp)
    db.session.commit()

    # Salvar arquivo temporário para processamento assíncrono
    # Usar /app/uploads/temp que é compartilhado entre web e worker via volume
    import os
    temp_dir = '/app/uploads/temp'
    os.makedirs(temp_dir, exist_ok=True)

    # Nome único para o arquivo temporário
    temp_filename = f'upload_{camp.id}_{int(time.time() * 1000)}.xlsx'
    temp_path = os.path.join(temp_dir, temp_filename)

    # Salvar arquivo
    try:
        arq.save(temp_path)
        logger.info(f"Arquivo salvo em: {temp_path}")

        # Verificar se arquivo existe e tem conteúdo
        if not os.path.exists(temp_path):
            raise FileNotFoundError(f"Arquivo não foi salvo: {temp_path}")

        file_size = os.path.getsize(temp_path)
        logger.info(f"Arquivo salvo com sucesso: {file_size} bytes")

    except Exception as e:
        logger.error(f"Erro ao salvar arquivo: {e}")
        camp.status = 'erro'
        camp.status_msg = f'Erro ao salvar arquivo: {str(e)}'
        db.session.commit()
        flash(f'Erro ao salvar arquivo: {e}', 'danger')
        return redirect(url_for(get_dashboard_route()))

    # Processar planilha de forma ASSÍNCRONA com Celery
    from app.tasks import processar_planilha_task
    task = processar_planilha_task.delay(temp_path, camp.id)

    # Salvar task_id na campanha para polling
    camp.task_id = task.id
    db.session.commit()

    logger.info(f"Task {task.id} iniciada para campanha {camp.id}")

    # Redirecionar para página de progresso
    return redirect(url_for('fila.progresso_campanha', id=camp.id, task_id=task.id))
@bp.route('/campanha/<int:id>/progresso')
@login_required
def progresso_campanha(id):
    """Página de progresso do processamento da campanha"""
    camp = verificar_acesso_campanha(id)
    task_id = request.args.get('task_id') or camp.task_id

    if not task_id:
        flash('Task ID não encontrado', 'warning')
        return redirect(url_for(get_dashboard_route()))

    return render_template('progresso_campanha.html', campanha=camp, task_id=task_id)
@bp.route('/api/campanha/status/<task_id>')
@login_required
def status_processamento(task_id):
    """API para polling do status da task de processamento"""
    if not AsyncResult or not celery_app:
        return jsonify({
            'state': 'FAILURE',
            'status': 'Celery não configurado',
            'percent': 0
        })

    task = AsyncResult(task_id, app=celery_app)

    if task.state == 'PENDING':
        response = {
            'state': task.state,
            'status': 'Aguardando processamento...',
            'percent': 0
        }
    elif task.state == 'PROGRESS':
        response = {
            'state': task.state,
            'status': task.info.get('status', ''),
            'percent': task.info.get('percent', 0),
            'current': task.info.get('current', 0),
            'total': task.info.get('total', 100)
        }
    elif task.state == 'SUCCESS':
        result = task.info
        response = {
            'state': task.state,
            'status': 'Processamento concluído!',
            'percent': 100,
            'result': result
        }
    else:  # FAILURE ou outro estado
        response = {
            'state': task.state,
            'status': str(task.info) if task.info else 'Erro desconhecido',
            'percent': 0
        }

    return jsonify(response)
@bp.route('/campanha/<int:id>')
@login_required
def campanha_detalhe(id):
    camp = verificar_acesso_campanha(id)
    camp.atualizar_stats()

    filtro = request.args.get('filtro', 'todos')
    busca = request.args.get('busca', '').strip()
    page = request.args.get('page', 1, type=int)

    q = camp.contatos

    if filtro == 'validos':
        q = q.join(Telefone).filter(Telefone.whatsapp_valido == True).distinct()
    elif filtro == 'invalidos':
        # Contatos onde TODOS os telefones sao invalidos ou nao tem telefone
        # Dificil fazer em uma query simples, vamos filtrar por status se possivel
        # Ou usar status 'sem_whatsapp'
        q = q.filter(Contato.status == 'sem_whatsapp')
    elif filtro == 'confirmados':
        q = q.filter_by(confirmado=True)
    elif filtro == 'rejeitados':
        q = q.filter_by(rejeitado=True)
    elif filtro == 'pendentes':
        q = q.filter(Contato.status.in_(['pendente', 'pronto_envio']))
    elif filtro == 'aguardando':
        q = q.filter(Contato.status == 'enviado', Contato.confirmado == False, Contato.rejeitado == False)
    elif filtro == 'erros':
        q = q.filter(Contato.erro.isnot(None))
    elif filtro == 'nao_validados':
        q = q.join(Telefone).filter(Telefone.whatsapp_valido == None).distinct()

    if busca:
        q = q.join(Telefone).filter((Contato.nome.ilike(f'%{busca}%')) | (Telefone.numero.ilike(f'%{busca}%'))).distinct()

    contatos = q.order_by(Contato.id).paginate(page=page, per_page=50)

    return render_template('campanha.html', campanha=camp, contatos=contatos, filtro=filtro, busca=busca)
@bp.route('/campanha/<int:id>/validar', methods=['POST'])
@login_required
def validar_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status in ['validando', 'em_andamento']:
        return jsonify({'erro': 'Ja em processamento'}), 400

    ws = WhatsApp(camp.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    # Iniciar task Celery em vez de thread
    from app.tasks import validar_campanha_task
    task = validar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('api.task_status', task_id=task.id)
    })
@bp.route('/campanha/<int:id>/iniciar', methods=['POST'])
@login_required
def iniciar_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status == 'em_andamento':
        return jsonify({'erro': 'Ja em andamento'}), 400

    # Verifica se tem pendentes ou prontos
    pendentes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhum contato para enviar'}), 400

    ws = WhatsApp(camp.criador_id)
    conn, _ = ws.conectado()
    if not conn:
        return jsonify({'erro': 'WhatsApp desconectado'}), 400

    # Iniciar task Celery em vez de thread
    from app.tasks import enviar_campanha_task
    task = enviar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('api.task_status', task_id=task.id)
    })
@bp.route('/campanha/<int:id>/pausar', methods=['POST'])
@login_required
def pausar_campanha(id):
    camp = verificar_acesso_campanha(id)
    camp.status = 'pausada'
    camp.status_msg = 'Pausada'
    db.session.commit()
    return jsonify({'sucesso': True})
@bp.route('/campanha/<int:id>/retomar', methods=['POST'])
@login_required
def retomar_campanha(id):
    camp = verificar_acesso_campanha(id)
    # Verifica se tem pendentes ou prontos
    pendentes = camp.contatos.filter(Contato.status.in_(['pendente', 'pronto_envio'])).count()
    if pendentes == 0:
        return jsonify({'erro': 'Nenhum contato pendente'}), 400

    # Iniciar task Celery em vez de thread
    from app.tasks import enviar_campanha_task
    task = enviar_campanha_task.delay(id)

    return jsonify({
        'sucesso': True,
        'task_id': task.id,
        'status_url': url_for('api.task_status', task_id=task.id)
    })
@bp.route('/campanha/<int:id>/cancelar', methods=['POST'])
@login_required
def cancelar_campanha(id):
    camp = verificar_acesso_campanha(id)
    camp.status = 'cancelada'
    camp.status_msg = 'Cancelada'
    db.session.commit()
    return jsonify({'sucesso': True})
@bp.route('/campanha/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_campanha(id):
    camp = verificar_acesso_campanha(id)
    if camp.status in ['em_andamento', 'validando']:
        flash('Nao pode excluir em andamento', 'danger')
        return redirect(url_for('fila.campanha_detalhe', id=id))

    db.session.delete(camp)
    db.session.commit()
    flash('Excluida', 'success')
    return redirect(url_for(get_dashboard_route()))
@bp.route('/campanha/<int:id>/exportar')
@login_required
def exportar_campanha(id):
    camp = verificar_acesso_campanha(id)

    dados = []
    for c in camp.contatos.order_by(Contato.id).all():
        dados.append({
            'Nome': c.nome,
            'Nascimento': c.data_nascimento.strftime('%d/%m/%Y') if c.data_nascimento else '',
            'Telefones': c.telefones_str(),
            'Procedimento': c.procedimento,
            'Status': c.status_texto(),
            'Enviado': 'Sim' if c.status in ['enviado', 'aguardando_nascimento', 'aguardando_motivo_rejeicao', 'concluido'] or c.confirmado or c.rejeitado else 'Nao',
            'Data Envio': max([t.data_envio for t in c.telefones if t.data_envio], default=None).strftime('%d/%m/%Y %H:%M') if any(t.data_envio for t in c.telefones) else '',
            'Confirmado': 'SIM' if c.confirmado else '',
            'Rejeitado': 'SIM' if c.rejeitado else '',
            'Resposta': c.resposta or '',
            'Data Resposta': c.data_resposta.strftime('%d/%m/%Y %H:%M') if c.data_resposta else '',
            'Erro': c.erro or ''
        })

    df = pd.DataFrame(dados)
    out = BytesIO()
    with pd.ExcelWriter(out, engine='openpyxl') as w:
        df.to_excel(w, sheet_name='Contatos', index=False)
    out.seek(0)

    return send_file(out, mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                     as_attachment=True, download_name=f'campanha_{id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx')
@bp.route('/api/campanha/<int:id>/status')
@login_required
def api_status(id):
    camp = verificar_acesso_campanha(id)
    camp.atualizar_stats()
    return jsonify({
        'status': camp.status,
        'status_msg': camp.status_msg,
        'total_contatos': camp.total_contatos,
        'total_validos': camp.total_validos,
        'total_invalidos': camp.total_invalidos,
        'total_enviados': camp.total_enviados,
        'total_confirmados': camp.total_confirmados,
        'total_rejeitados': camp.total_rejeitados,
        'total_erros': camp.total_erros,
        'pct_validacao': camp.pct_validacao(),
        'pct_envio': camp.pct_envio(),
        'pct_confirmacao': camp.pct_confirmacao(),
        'percentual_validacao': camp.percentual_validacao(),
        'percentual_envio': camp.percentual_envio(),
        'percentual_confirmacao': camp.percentual_confirmacao(),
        'percentual_conclusao': camp.percentual_conclusao(),
        'pendentes_validar': camp.pendentes_validar(),
        'pendentes_enviar': camp.pendentes_enviar()
    })
@bp.route('/api/contato/<int:id>/confirmar', methods=['POST'])
@login_required
def api_confirmar(id):
    c = verificar_acesso_contato(id)
    c.confirmado = True
    c.rejeitado = False
    c.data_resposta = datetime.utcnow()
    c.resposta = f"[Manual: {current_user.nome}]"
    c.status = 'concluido'
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()
    return jsonify({'sucesso': True})
@bp.route('/api/contato/<int:id>/rejeitar', methods=['POST'])
@login_required
def api_rejeitar(id):
    c = verificar_acesso_contato(id)
    c.rejeitado = True
    c.confirmado = False
    c.data_resposta = datetime.utcnow()
    c.resposta = f"[Manual: {current_user.nome}]"
    c.status = 'concluido'
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()
    return jsonify({'sucesso': True})
@bp.route('/api/contato/<int:id>/reenviar', methods=['POST'])
@login_required
def api_reenviar(id):
    c = verificar_acesso_contato(id)
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    c.erro = None

    # Usar procedimento normalizado (mais simples) se disponível, senão usar original
    procedimento_msg = c.procedimento_normalizado or c.procedimento or 'o procedimento'
    msg = c.campanha.mensagem.replace('{nome}', c.nome).replace('{procedimento}', procedimento_msg)

    # Enviar para TODOS os numeros validos
    tels = c.telefones.filter_by(whatsapp_valido=True).all()
    if not tels:
        return jsonify({'erro': 'Nenhum numero valido'}), 400

    sucesso = False
    erros = []

    for t in tels:
        ok, result = ws.enviar(t.numero_fmt, msg)
        if ok:
            t.enviado = True
            t.data_envio = datetime.utcnow()
            t.msg_id = result
            sucesso = True
        else:
            erros.append(result)
            
    if sucesso:
        c.status = 'enviado'
        c.erro = None
        db.session.commit()
        return jsonify({'sucesso': True})
    else:
        c.erro = "; ".join(erros)
        db.session.commit()
        return jsonify({'erro': c.erro}), 400
@bp.route('/api/contato/<int:id>/revalidar', methods=['POST'])
@login_required
def api_revalidar(id):
    c = verificar_acesso_contato(id)
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp nao configurado'}), 400

    tels = c.telefones.all()
    if not tels:
        return jsonify({'erro': 'Sem telefones'}), 400
        
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
            
    c.erro = None
    if tem_valido:
        if c.status == 'sem_whatsapp':
            c.status = 'pendente' # ou pronto_envio
    else:
        c.status = 'sem_whatsapp'
        
    db.session.commit()
    c.campanha.atualizar_stats()
    db.session.commit()

    return jsonify({'sucesso': True, 'valido': tem_valido})
@bp.route('/api/contato/<int:id>/detalhes', methods=['GET'])
@login_required
def api_contato_detalhes(id):
    """
    Retorna informações detalhadas do contato incluindo:
    - Todas as respostas de cada telefone
    - Histórico de mensagens (enviadas e recebidas)
    - Status de conflito
    """
    try:
        c = verificar_acesso_contato(id)

        # Obter respostas detalhadas de todos os telefones
        respostas_telefones = []
        for telefone in c.telefones.all():
            tel_info = {
                'id': telefone.id,
                'numero': telefone.numero,
                'numero_formatado': telefone.numero_fmt,
                'prioridade': telefone.prioridade,
                'whatsapp_valido': telefone.whatsapp_valido,
                'enviado': telefone.enviado,
                'data_envio': telefone.data_envio.isoformat() if telefone.data_envio else None,
                'resposta': getattr(telefone, 'resposta', None),
                'data_resposta': getattr(telefone, 'data_resposta', None).isoformat() if getattr(telefone, 'data_resposta', None) else None,
                'tipo_resposta': getattr(telefone, 'tipo_resposta', None),
                'tipo_resposta_texto': {
                    'confirmado': 'Confirmado',
                    'rejeitado': 'Rejeitado',
                    'desconheco': 'Não conhece a pessoa'
                }.get(getattr(telefone, 'tipo_resposta', None), 'Sem resposta'),
                'validacao_pendente': getattr(telefone, 'validacao_pendente', False)
            }
            respostas_telefones.append(tel_info)

        # Obter histórico de mensagens do log
        logs = LogMsg.query.filter_by(contato_id=c.id).order_by(LogMsg.data).all()
        historico = []
        for log in logs:
            log_info = {
                'id': log.id,
                'direcao': log.direcao,
                'telefone': log.telefone,
                'mensagem': log.mensagem,
                'data': log.data.isoformat() if log.data else None,
                'status': log.status,
                'sentimento': log.sentimento,
                'sentimento_score': log.sentimento_score
            }
            historico.append(log_info)

        # Informações do contato
        # Usar try/except para métodos que podem não existir ainda
        try:
            tem_multiplas = c.tem_respostas_multiplas()
            tem_conflito = c.tem_conflito_real()
        except:
            tem_multiplas = False
            tem_conflito = False

        contato_info = {
            'id': c.id,
            'nome': c.nome,
            'data_nascimento': c.data_nascimento.isoformat() if c.data_nascimento else None,
            'procedimento': c.procedimento,
            'status': c.status,
            'status_texto': c.status_texto(),
            'confirmado': c.confirmado,
            'rejeitado': c.rejeitado,
            'erro': c.erro,
            'tem_respostas_multiplas': tem_multiplas,
            'tem_conflito_real': tem_conflito,
            'campanha_id': c.campanha_id
        }

        return jsonify({
            'contato': contato_info,
            'telefones': respostas_telefones,
            'historico': historico
        })
    except Exception as e:
        logger.error(f"Erro ao buscar detalhes do contato {id}: {str(e)}")
        return jsonify({'erro': 'Erro ao carregar detalhes. Banco de dados precisa ser atualizado.'}), 500
@bp.route('/api/contato/<int:id>/enviar_mensagem', methods=['POST'])
@login_required
def api_enviar_mensagem_contato(id):
    """
    Envia uma mensagem para um telefone específico do contato
    """
    c = verificar_acesso_contato(id)

    data = request.get_json()
    telefone_id = data.get('telefone_id')
    mensagem = data.get('mensagem', '').strip()

    if not mensagem:
        return jsonify({'erro': 'Mensagem não pode estar vazia'}), 400

    # Encontrar o telefone
    telefone = None
    for t in c.telefones.all():
        if t.id == telefone_id:
            telefone = t
            break

    if not telefone:
        return jsonify({'erro': 'Telefone não encontrado'}), 404

    if not telefone.whatsapp_valido:
        return jsonify({'erro': 'Este número não possui WhatsApp válido'}), 400

    # Enviar mensagem
    ws = WhatsApp(c.campanha.criador_id)
    if not ws.ok():
        return jsonify({'erro': 'WhatsApp não configurado'}), 400

    sucesso, resultado = ws.enviar(telefone.numero_fmt, mensagem)

    if sucesso:
        # Registrar no log
        log = LogMsg(
            campanha_id=c.campanha_id,
            contato_id=c.id,
            direcao='enviada',
            telefone=telefone.numero_fmt,
            mensagem=mensagem,
            status='enviado'
        )
        db.session.add(log)
        db.session.commit()

        return jsonify({
            'sucesso': True,
            'mensagem': 'Mensagem enviada com sucesso'
        })
    else:
        return jsonify({
            'erro': f'Erro ao enviar mensagem: {resultado}'
        }), 500
@bp.route('/contato/<int:id>/detalhes')
@login_required
def contato_detalhes_pagina(id):
    """
    Página completa com detalhes do contato
    """
    c = verificar_acesso_contato(id)

    # Obter telefones com respostas
    telefones = c.telefones.all()

    # Obter histórico de mensagens
    logs = LogMsg.query.filter_by(contato_id=c.id).order_by(LogMsg.data).all()

    return render_template('contato_detalhes.html',
                         contato=c,
                         telefones=telefones,
                         logs=logs)
@bp.route('/contato/<int:id>/editar', methods=['GET', 'POST'])
@login_required
def editar_contato(id):
    c = verificar_acesso_contato(id)
    
    if request.method == 'POST':
        c.nome = request.form.get('nome', '').strip()[:200]
        c.procedimento = request.form.get('procedimento', '').strip()[:500]
        
        # Data de nascimento
        dt_nasc_str = request.form.get('data_nascimento', '').strip()
        if dt_nasc_str:
            try:
                c.data_nascimento = datetime.strptime(dt_nasc_str, '%Y-%m-%d').date()
            except:
                flash('Data de nascimento inválida', 'danger')
                return redirect(url_for('fila.editar_contato', id=id))
        
        # Telefones - remover todos e recriar
        for t in c.telefones.all():
            db.session.delete(t)
        
        telefones_input = request.form.getlist('telefones[]')
        for i, tel_raw in enumerate(telefones_input):
            tel = tel_raw.strip()
            if not tel:
                continue
            fmt = formatar_numero(tel)
            if fmt:
                t = Telefone(
                    contato_id=c.id,
                    numero=tel[:20],
                    numero_fmt=fmt,
                    prioridade=i+1
                )
                db.session.add(t)
        
        db.session.commit()
        c.campanha.atualizar_stats()
        db.session.commit()
        
        flash('Contato atualizado com sucesso!', 'success')
        return redirect(url_for('fila.campanha_detalhe', id=c.campanha_id))
    
    return render_template('editar_contato.html', contato=c)
@bp.route('/configuracoes')
@login_required
def configuracoes():
    """
    Tela de configurações WhatsApp
    - ADMIN: Pode configurar API global (URL e Key)
    - USUÁRIO: Apenas conecta seu WhatsApp (instância criada automaticamente)
    """
    cfg_global = ConfigGlobal.get()
    cfg_user = ConfigWhatsApp.get(current_user.id)

    # Verificar status de conexão
    conectado = False
    status_msg = "Não configurado"

    if cfg_global.ativo:
        try:
            ws = WhatsApp(current_user.id)
            if ws.ok():
                conectado, status_msg = ws.conectado()
        except Exception as e:
            status_msg = f"Erro: {str(e)}"

    return render_template('configuracoes.html',
                         config_global=cfg_global,
                         config_user=cfg_user,
                         conectado=conectado,
                         status_msg=status_msg,
                         is_admin=current_user.is_admin)
@bp.route('/configuracoes/global', methods=['POST'])
@login_required
@admin_required
def configuracoes_global():
    """Admin atualiza configuração global da Evolution API"""
    cfg = ConfigGlobal.get()

    cfg.evolution_api_url = request.form.get('api_url', '').strip().rstrip('/')
    cfg.evolution_api_key = request.form.get('api_key', '').strip()
    cfg.ativo = request.form.get('ativo') == 'on'
    cfg.atualizado_em = datetime.utcnow()
    cfg.atualizado_por = current_user.id
    db.session.commit()

    flash('✅ Configuração global salva com sucesso!', 'success')
    return redirect(url_for('fila.configuracoes'))
@bp.route('/faq')
@login_required
def gerenciar_faq():
    # Mostrar FAQs globais + FAQs do usuário
    faqs = RespostaAutomatica.query.filter(
        db.or_(
            RespostaAutomatica.global_faq == True,
            RespostaAutomatica.criador_id == current_user.id
        )
    ).order_by(RespostaAutomatica.prioridade.desc()).all()
    return render_template('faq.html', faqs=faqs)
@bp.route('/faq/criar', methods=['POST'])
@login_required
def criar_faq():
    categoria = request.form.get('categoria', '').strip()
    resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    prioridade = int(request.form.get('prioridade', 1))
    global_faq = request.form.get('global_faq') == 'on'  # Checkbox

    if not categoria or not resposta or not gatilhos_str:
        flash('Preencha todos os campos', 'danger')
        return redirect(url_for('fila.gerenciar_faq'))

    # Apenas admin pode criar FAQs globais
    if global_faq and not current_user.is_admin:
        flash('❌ Apenas administradores podem criar FAQs globais', 'danger')
        return redirect(url_for('fila.gerenciar_faq'))

    # Converter gatilhos de string para lista
    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]

    faq = RespostaAutomatica(
        categoria=categoria,
        resposta=resposta,
        prioridade=prioridade,
        global_faq=global_faq,
        criador_id=None if global_faq else current_user.id  # Global não tem criador
    )
    faq.set_gatilhos(gatilhos)
    db.session.add(faq)
    db.session.commit()

    tipo = 'global' if global_faq else 'privado'
    flash(f'✅ FAQ {tipo} criado com sucesso!', 'success')
    return redirect(url_for('fila.gerenciar_faq'))
@bp.route('/faq/<int:id>/editar', methods=['POST'])
@login_required
def editar_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)

    # Verificar permissões: só pode editar se for o criador OU se for global e for admin
    if faq.global_faq:
        if not current_user.is_admin:
            flash('❌ Apenas administradores podem editar FAQs globais', 'danger')
            return redirect(url_for('fila.gerenciar_faq'))
    else:
        if faq.criador_id != current_user.id:
            flash('❌ Você não pode editar FAQs de outros usuários', 'danger')
            return redirect(url_for('fila.gerenciar_faq'))

    faq.categoria = request.form.get('categoria', '').strip()
    faq.resposta = request.form.get('resposta', '').strip()
    gatilhos_str = request.form.get('gatilhos', '').strip()
    faq.prioridade = int(request.form.get('prioridade', 1))
    faq.ativa = request.form.get('ativa') == 'on'

    gatilhos = [g.strip() for g in gatilhos_str.split(',') if g.strip()]
    faq.set_gatilhos(gatilhos)

    db.session.commit()
    flash('✅ FAQ atualizado!', 'success')
    return redirect(url_for('fila.gerenciar_faq'))
@bp.route('/faq/<int:id>/excluir', methods=['POST'])
@login_required
def excluir_faq(id):
    faq = RespostaAutomatica.query.get_or_404(id)

    # Verificar permissões: só pode excluir se for o criador OU se for global e for admin
    if faq.global_faq:
        if not current_user.is_admin:
            flash('❌ Apenas administradores podem excluir FAQs globais', 'danger')
            return redirect(url_for('fila.gerenciar_faq'))
    else:
        if faq.criador_id != current_user.id:
            flash('❌ Você não pode excluir FAQs de outros usuários', 'danger')
            return redirect(url_for('fila.gerenciar_faq'))

    db.session.delete(faq)
    db.session.commit()
    flash('✅ FAQ excluído!', 'success')
    return redirect(url_for('fila.gerenciar_faq'))
@bp.route('/tutorial')
@login_required
def tutorial():
    categoria = request.args.get('categoria', 'inicio')
    tutoriais = Tutorial.query.filter_by(ativo=True, categoria=categoria).order_by(Tutorial.ordem).all()

    # Se não encontrou, pegar todos
    if not tutoriais:
        tutoriais = Tutorial.query.filter_by(ativo=True).order_by(Tutorial.categoria, Tutorial.ordem).all()

    return render_template('tutorial.html', tutoriais=tutoriais, categoria=categoria)
@bp.route('/tutorial/<int:id>')
@login_required
def tutorial_detalhe(id):
    tutorial = Tutorial.query.get_or_404(id)
    return render_template('tutorial_detalhe.html', tutorial=tutorial)
@bp.route('/followup/configurar', methods=['GET', 'POST'])
@login_required
def configurar_followup():
    config = ConfigTentativas.get()

    if request.method == 'POST':
        config.max_tentativas = int(request.form.get('max_tentativas', 3))
        config.intervalo_dias = int(request.form.get('intervalo_dias', 3))
        config.ativo = request.form.get('ativo') == 'on'
        db.session.commit()
        flash('Configuração salva!', 'success')
        return redirect(url_for('fila.configurar_followup'))

    return render_template('followup_config.html', config=config)
@bp.route('/followup/processar', methods=['POST'])
@login_required
def processar_followup_manual():
    """Executar follow-up manualmente (para testes)"""
    # Usar task Celery em vez de thread
    from app.tasks import follow_up_automatico_task
    task = follow_up_automatico_task.delay()
    flash(f'Follow-up iniciado (Task ID: {task.id})', 'info')
    return redirect(url_for(get_dashboard_route()))
@bp.route('/sentimentos')
@login_required
def dashboard_sentimentos():
    # Filtrar apenas logs das campanhas do usuario atual
    user_campanhas_ids = [c.id for c in Campanha.query.filter_by(criador_id=current_user.id).all()]

    # Estatísticas de sentimento
    query_sentimento = db.session.query(
        LogMsg.sentimento,
        db.func.count(LogMsg.id)
    ).filter(
        LogMsg.direcao == 'recebida',
        LogMsg.sentimento.isnot(None)
    )

    if user_campanhas_ids:
        query_sentimento = query_sentimento.filter(LogMsg.campanha_id.in_(user_campanhas_ids))

    stats_sentimento = query_sentimento.group_by(LogMsg.sentimento).all()

    # FAQs mais usadas (filtrar por criador ou globais)
    faqs_top = RespostaAutomatica.query.filter(
        RespostaAutomatica.contador_uso > 0,
        db.or_(
            RespostaAutomatica.global_faq == True,
            RespostaAutomatica.criador_id == current_user.id
        )
    ).order_by(RespostaAutomatica.contador_uso.desc()).limit(10).all()

    return render_template('sentimentos.html',
                         stats_sentimento=dict(stats_sentimento),
                         faqs_top=faqs_top)
@bp.route('/logs')
@login_required
def logs():
    page = request.args.get('page', 1, type=int)
    camp_id = request.args.get('campanha_id', type=int)
    direcao = request.args.get('direcao')

    q = LogMsg.query
    if camp_id:
        q = q.filter_by(campanha_id=camp_id)
    if direcao:
        q = q.filter_by(direcao=direcao)

    logs = q.order_by(LogMsg.data.desc()).paginate(page=page, per_page=100)
    # Filtrar apenas campanhas do usuario atual
    camps = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()

    return render_template('logs.html', logs=logs, campanhas=camps, campanha_id=camp_id, direcao=direcao)
@bp.route('/relatorios')
@login_required
def relatorios():
    """Página de relatórios com dashboard executivo"""
    # Filtrar apenas campanhas do usuario atual
    campanhas = Campanha.query.filter_by(criador_id=current_user.id).order_by(Campanha.data_criacao.desc()).all()

    # Se houver uma campanha selecionada via query param
    campanha_id = request.args.get('campanha_id', type=int)
    campanha_selecionada = None
    if campanha_id:
        # Verificar se a campanha pertence ao usuario
        campanha_selecionada = Campanha.query.filter_by(id=campanha_id, criador_id=current_user.id).first()

    return render_template('relatorios.html',
                          campanhas=campanhas,
                          campanha_selecionada=campanha_selecionada)
@bp.route('/api/relatorios/<int:campanha_id>')
@login_required
def api_relatorios(campanha_id):
    """API para retornar dados de relatórios de uma campanha específica"""
    campanha = verificar_acesso_campanha(campanha_id)

    # Atualizar estatísticas
    campanha.atualizar_stats()
    db.session.commit()

    # Buscar contatos da campanha
    contatos = Contato.query.filter_by(campanha_id=campanha_id).all()

    # Preparar dados dos contatos para a tabela
    contatos_data = []
    for contato in contatos:
        # Buscar o primeiro telefone do contato
        telefone_obj = Telefone.query.filter_by(contato_id=contato.id).first()
        telefone_str = telefone_obj.numero if telefone_obj else None
        data_envio = telefone_obj.data_envio if telefone_obj and telefone_obj.data_envio else None

        contatos_data.append({
            'id': contato.id,
            'nome': contato.nome,
            'telefone': telefone_str,
            'procedimento': contato.procedimento,
            'procedimento_normalizado': contato.procedimento_normalizado,
            'status': contato.status,
            'confirmado': contato.confirmado,
            'rejeitado': contato.rejeitado,
            'erro': contato.erro,
            'data_envio': data_envio.isoformat() if data_envio else None,
            'resposta': contato.resposta
        })

    return jsonify({
        'campanha_id': campanha.id,
        'campanha_nome': campanha.nome,
        'total_contatos': campanha.total_contatos,
        'total_enviados': campanha.total_enviados,
        'total_confirmados': campanha.total_confirmados,
        'total_rejeitados': campanha.total_rejeitados,
        'total_erros': campanha.total_erros,
        'contatos': contatos_data
    })
