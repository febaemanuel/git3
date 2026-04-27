"""Configuration / Celery / WhatsApp control APIs."""

import logging
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from app.celery_compat import AsyncResult, celery_app
from app.extensions import db
from app.models import ConfigGlobal, ConfigWhatsApp
from app.services.whatsapp import WhatsApp


logger = logging.getLogger(__name__)


bp = Blueprint('api', __name__)


@bp.route('/api/whatsapp/conectar', methods=['POST'])
@login_required
def conectar_whatsapp():
    """
    Conectar WhatsApp automaticamente:
    1. Verifica config global
    2. Cria instância se necessário
    3. Retorna QR code
    """
    try:
        # Verificar se admin configurou API global
        cfg_global = ConfigGlobal.get()
        if not cfg_global.ativo or not cfg_global.evolution_api_url or not cfg_global.evolution_api_key:
            return jsonify({
                'erro': 'Sistema não configurado. Entre em contato com o administrador.'
            }), 400

        # Inicializar WhatsApp com config do usuário
        ws = WhatsApp(current_user.id)

        if not ws.ok():
            return jsonify({'erro': 'Erro ao inicializar WhatsApp'}), 500

        # Tentar criar instância (se já existir, retorna sucesso)
        sucesso_criar, msg_criar = ws.criar_instancia()

        if not sucesso_criar and 'ja existe' not in msg_criar.lower():
            return jsonify({'erro': f'Erro ao criar instância: {msg_criar}'}), 500

        # Obter QR code
        ok, result = ws.qrcode()
        if ok:
            # Atualizar status no banco
            ws.cfg_user.conectado = False  # Ainda não conectou, apenas obteve QR
            ws.cfg_user.atualizado_em = datetime.utcnow()
            db.session.commit()

            return jsonify({
                'sucesso': True,
                'qrcode': result,
                'instance_name': ws.instance
            })
        else:
            if 'conectado' in result.lower() or 'open' in result.lower():
                # Já está conectado!
                ws.cfg_user.conectado = True
                ws.cfg_user.data_conexao = datetime.utcnow()
                db.session.commit()

                return jsonify({
                    'conectado': True,
                    'mensagem': 'WhatsApp já está conectado!',
                    'instance_name': ws.instance
                })
            return jsonify({'erro': result}), 400

    except Exception as e:
        logger.error(f"Erro ao conectar WhatsApp: {str(e)}")
        return jsonify({'erro': str(e)}), 500
@bp.route('/api/whatsapp/webhook/configurar', methods=['POST'])
@login_required
def configurar_webhook():
    """Configura webhook para a instância do usuário"""
    try:
        ws = WhatsApp(current_user.id)
        if not ws.ok():
            return jsonify({'erro': 'WhatsApp não configurado'}), 400

        ok, msg = ws.configurar_webhook()
        if ok:
            return jsonify({
                'sucesso': True,
                'mensagem': msg
            })
        else:
            return jsonify({'erro': msg}), 400

    except Exception as e:
        logger.error(f"Erro ao configurar webhook: {str(e)}")
        return jsonify({'erro': str(e)}), 500
@bp.route('/api/whatsapp/qrcode')
@login_required
def qrcode():
    """Obter QR code (mantido por compatibilidade, mas use /conectar)"""
    ws = WhatsApp(current_user.id)
    if not ws.ok():
        return jsonify({'erro': 'Sistema não configurado'}), 400

    ok, result = ws.qrcode()
    if ok:
        return jsonify({'qrcode': result})
    else:
        if 'conectado' in result.lower():
            return jsonify({'conectado': True, 'mensagem': result})
        return jsonify({'erro': result}), 400
@bp.route('/api/whatsapp/status')
@login_required
def ws_status():
    ws = WhatsApp(current_user.id)
    if not ws.ok():
        return jsonify({'conectado': False, 'mensagem': 'Nao configurado'})
    conn, msg = ws.conectado()
    return jsonify({'conectado': conn, 'mensagem': msg})
@bp.route('/api/task/<task_id>/status')
@login_required
def task_status(task_id):
    """
    Endpoint para verificar status de uma task Celery

    Retorna:
        - state: PENDING, PROGRESS, SUCCESS, FAILURE, RETRY
        - meta: Informações adicionais (progresso, erro, etc)
    """
    if not AsyncResult or not celery_app:
        return jsonify({
            'task_id': task_id,
            'state': 'FAILURE',
            'error': 'Celery não configurado'
        })

    task = AsyncResult(task_id, app=celery_app)

    response = {
        'task_id': task_id,
        'state': task.state,
        'ready': task.ready(),
        'successful': task.successful() if task.ready() else None,
        'failed': task.failed() if task.ready() else None
    }

    if task.state == 'PENDING':
        response['meta'] = {
            'status': 'Aguardando processamento...'
        }
    elif task.state == 'PROGRESS':
        response['meta'] = task.info
    elif task.state == 'SUCCESS':
        response['result'] = task.result
    elif task.state == 'FAILURE':
        response['error'] = str(task.info)
    elif task.state == 'RETRY':
        response['meta'] = task.info
    else:
        response['meta'] = task.info

    return jsonify(response)
@bp.route('/api/task/<task_id>/cancel', methods=['POST'])
@login_required
def task_cancel(task_id):
    """
    Cancela uma task Celery em andamento
    """
    if not AsyncResult or not celery_app:
        return jsonify({
            'sucesso': False,
            'task_id': task_id,
            'message': 'Celery não configurado'
        })

    task = AsyncResult(task_id, app=celery_app)
    task.revoke(terminate=True)

    return jsonify({
        'sucesso': True,
        'task_id': task_id,
        'message': 'Task cancelada'
    })
