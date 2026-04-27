"""Cross-cutting helpers used by route blueprints.

verificar_acesso_*, get_dashboard_route, admin_required, load_user —
moved out of the (now removed) app/main.py.
"""

from functools import wraps

from flask import abort, flash, redirect, url_for
from flask_login import current_user

from app.extensions import db, login_manager
from app.models import Campanha, Contato, TicketAtendimento, Usuario


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


def load_user(uid):
    """Flask-Login user_loader. Registered on ``login_manager`` inside
    ``create_app()`` to keep import order independent of side effects."""
    return db.session.get(Usuario, int(uid))
