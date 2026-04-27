"""Auth & landing routes (login, logout, cadastro)."""

from datetime import datetime

from flask import (
    Blueprint, flash, jsonify, redirect, render_template, request,
    url_for,
)
from flask_login import (
    current_user, login_required, login_user, logout_user,
)

from app.extensions import db
from app.main import ADMIN_EMAIL, get_dashboard_route, logger
from app.models import Usuario, ConfigGlobal


bp = Blueprint('auth', __name__)


@bp.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))
    return redirect(url_for('auth.login'))
@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))

    if request.method == 'POST':
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        u = Usuario.query.filter_by(email=email).first()

        if u and u.check_password(senha) and u.ativo:
            login_user(u)
            u.ultimo_acesso = datetime.utcnow()
            db.session.commit()
            # Redirecionar para dashboard correto baseado no tipo_sistema
            return redirect(url_for(get_dashboard_route()))
        flash('Email ou senha incorretos', 'danger')

    return render_template('login.html')
@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))
@bp.route('/cadastro', methods=['GET', 'POST'])
def cadastro():
    if current_user.is_authenticated:
        return redirect(url_for(get_dashboard_route()))

    if request.method == 'POST':
        nome = request.form.get('nome', '').strip()
        email = request.form.get('email', '').strip().lower()
        senha = request.form.get('senha', '')
        senha_confirm = request.form.get('senha_confirm', '')
        tipo_sistema = request.form.get('tipo_sistema', 'BUSCA_ATIVA').strip()

        # Validações
        if not nome or not email or not senha:
            flash('Preencha todos os campos', 'danger')
            return render_template('cadastro.html')

        if len(senha) < 6:
            flash('Senha deve ter no mínimo 6 caracteres', 'danger')
            return render_template('cadastro.html')

        if senha != senha_confirm:
            flash('As senhas não coincidem', 'danger')
            return render_template('cadastro.html')

        # Validar tipo_sistema
        if tipo_sistema not in ['BUSCA_ATIVA', 'AGENDAMENTO_CONSULTA', 'GERAL']:
            tipo_sistema = 'BUSCA_ATIVA'

        # Verificar se email já existe
        if Usuario.query.filter_by(email=email).first():
            flash('Email já cadastrado', 'danger')
            return render_template('cadastro.html')

        # Criar usuário
        usuario = Usuario(nome=nome, email=email, ativo=True, tipo_sistema=tipo_sistema)
        usuario.set_password(senha)
        db.session.add(usuario)
        db.session.commit()

        flash('Cadastro realizado com sucesso! Faça login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('cadastro.html')
