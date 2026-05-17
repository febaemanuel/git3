"""
=============================================================================
ROTAS - MODO SCIH (Serviço de Controle de Infecção Hospitalar)
=============================================================================
Pesquisa pós-cirúrgica enviada via WhatsApp para pacientes da Maternidade
Escola Assis Chateaubriand. Templates fixos: CESARIANA e MASTOLOGIA.
"""

import json
import logging
import secrets
from datetime import datetime
from io import BytesIO

import pandas as pd
from flask import (
    render_template, request, redirect, url_for, flash, jsonify,
    send_file, abort
)
from flask_login import login_required, current_user

logger = logging.getLogger(__name__)


# Templates dos questionários (campos exibidos pra paciente e usados na
# agregação do dashboard). Mantidos no código por decisão de produto.
TEMPLATES_PESQUISA = {
    'CESARIANA': {
        'titulo': 'Pesquisa pós-cesárea',
        'cirurgia_label': 'cesárea',
    },
    'MASTOLOGIA': {
        'titulo': 'Pesquisa pós-mastologia',
        'cirurgia_label': 'mastologia',
    },
}

SINTOMAS_OPCOES = [
    'Febre',
    'Ferida cirúrgica avermelhada',
    'Ferida cirúrgica inchada',
    'Ferida cirúrgica com dor',
    'Ferida cirúrgica com secreção',
    'Ferida cirúrgica com pus',
    'Ferida cirúrgica com sangramento',
    'Ferida cirúrgica com mau cheiro',
]


def _exige_scih():
    """Bloqueia acesso pra quem não é SCIH (ou admin)."""
    tipo = getattr(current_user, 'tipo_sistema', 'BUSCA_ATIVA')
    if tipo != 'PESQUISA_SCIH' and not getattr(current_user, 'is_admin', False):
        flash('Acesso negado. Esta área é exclusiva do módulo SCIH.', 'warning')
        return False
    return True


def _gerar_token():
    """Token URL-safe único pra identificar a pesquisa do paciente."""
    return secrets.token_urlsafe(24)


def init_scih_routes(app, db):
    """Registra todas as rotas do módulo SCIH."""

    from app import (
        CampanhaSCIH, PacienteSCIH, RespostaSCIH, LogMsgSCIH,
        WhatsApp, ConfigWhatsApp, formatar_numero
    )

    try:
        from tasks import enviar_campanha_scih_task
    except ImportError:
        enviar_campanha_scih_task = None
        logger.warning("Celery não disponível para módulo SCIH")

    # =========================================================================
    # DASHBOARD
    # =========================================================================
    @app.route('/scih/dashboard')
    @login_required
    def scih_dashboard():
        if not _exige_scih():
            return redirect(url_for('login'))

        campanhas = CampanhaSCIH.query.filter_by(
            criador_id=current_user.id
        ).order_by(CampanhaSCIH.id.desc()).all()

        # Agregados gerais
        total_camp = len(campanhas)
        total_pac = sum(c.total_pacientes or 0 for c in campanhas)
        total_env = sum(c.total_enviados or 0 for c in campanhas)
        total_resp = sum(c.total_respondidos or 0 for c in campanhas)
        pct_resp = round(total_resp / total_env * 100, 1) if total_env else 0

        return render_template(
            'scih/dashboard.html',
            campanhas=campanhas,
            total_camp=total_camp,
            total_pac=total_pac,
            total_env=total_env,
            total_resp=total_resp,
            pct_resp=pct_resp,
        )

    # =========================================================================
    # IMPORTAR PLANILHA / CRIAR CAMPANHA
    # =========================================================================
    @app.route('/scih/importar', methods=['GET', 'POST'])
    @login_required
    def scih_importar():
        if not _exige_scih():
            return redirect(url_for('login'))

        if request.method == 'POST':
            try:
                arquivo = request.files.get('arquivo')
                if not arquivo or arquivo.filename == '':
                    flash('Selecione um arquivo Excel (.xlsx)', 'danger')
                    return redirect(request.url)
                if not arquivo.filename.lower().endswith(('.xlsx', '.xls')):
                    flash('Formato inválido. Use .xlsx ou .xls', 'danger')
                    return redirect(request.url)

                nome = request.form.get('nome', '').strip()
                descricao = request.form.get('descricao', '').strip()
                template = request.form.get('template', 'CESARIANA').strip().upper()
                hora_inicio = int(request.form.get('hora_inicio', 8))
                hora_fim = int(request.form.get('hora_fim', 18))
                meta_diaria = int(request.form.get('meta_diaria', 100))

                if not nome:
                    flash('Informe o nome da campanha', 'danger')
                    return redirect(request.url)
                if template not in TEMPLATES_PESQUISA:
                    flash('Template inválido', 'danger')
                    return redirect(request.url)

                # WhatsApp obrigatório
                if not ConfigWhatsApp.query.filter_by(usuario_id=current_user.id).first():
                    flash('Configure o WhatsApp antes de criar uma campanha.', 'danger')
                    return redirect(url_for('scih_dashboard'))
                if not WhatsApp(current_user.id).ok():
                    flash('WhatsApp não está configurado corretamente.', 'danger')
                    return redirect(url_for('scih_dashboard'))

                df = pd.read_excel(arquivo, dtype=str).fillna('')

                # Normalizar nomes de colunas (uppercase, sem espaços extras)
                df.columns = [str(c).strip().upper() for c in df.columns]

                col_nome = next((c for c in df.columns if c in ['NOME', 'NOME COMPLETO', 'PACIENTE']), None)
                col_tel = next((c for c in df.columns if c in ['TELEFONE', 'CELULAR', 'CONTATO', 'FONE']), None)
                col_data = next((c for c in df.columns if c in ['DATA CIRURGIA', 'DATA DA CIRURGIA', 'DATA']), None)
                col_idade = next((c for c in df.columns if c in ['IDADE']), None)

                if not col_nome or not col_tel:
                    flash('Planilha precisa ter pelo menos as colunas NOME e TELEFONE.', 'danger')
                    return redirect(request.url)

                camp = CampanhaSCIH(
                    criador_id=current_user.id,
                    nome=nome,
                    descricao=descricao,
                    template=template,
                    hora_inicio=hora_inicio,
                    hora_fim=hora_fim,
                    meta_diaria=meta_diaria,
                    status='pendente',
                )
                db.session.add(camp)
                db.session.flush()

                criados = 0
                for _, row in df.iterrows():
                    nome_pac = str(row.get(col_nome, '')).strip()
                    tel_raw = str(row.get(col_tel, '')).strip()
                    if not nome_pac or not tel_raw:
                        continue
                    paciente = PacienteSCIH(
                        campanha_id=camp.id,
                        criador_id=current_user.id,
                        nome=nome_pac,
                        telefone=tel_raw,
                        idade=str(row.get(col_idade, '')).strip() if col_idade else None,
                        data_cirurgia=str(row.get(col_data, '')).strip() if col_data else None,
                        token=_gerar_token(),
                        status='AGUARDANDO_ENVIO',
                    )
                    db.session.add(paciente)
                    criados += 1

                camp.total_pacientes = criados
                db.session.commit()
                camp.atualizar_stats()

                flash(f'Campanha criada com {criados} pacientes.', 'success')
                return redirect(url_for('scih_campanha_detalhe', id=camp.id))
            except Exception as e:
                logger.exception(f"Erro ao importar planilha SCIH: {e}")
                flash(f'Erro ao processar planilha: {e}', 'danger')
                return redirect(request.url)

        return render_template('scih/importar.html', templates=TEMPLATES_PESQUISA)

    # =========================================================================
    # DETALHE DA CAMPANHA
    # =========================================================================
    @app.route('/scih/campanha/<int:id>')
    @login_required
    def scih_campanha_detalhe(id):
        if not _exige_scih():
            return redirect(url_for('login'))

        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)

        camp.atualizar_stats()
        pacientes = camp.pacientes.order_by(PacienteSCIH.id).all()
        respostas = RespostaSCIH.query.filter_by(campanha_id=camp.id).all()

        # Agregação dos sintomas (Chart.js bar)
        sintoma_counts = {s: 0 for s in SINTOMAS_OPCOES}
        com_sintoma = 0
        buscou_atend = 0
        usou_remedio = 0
        for r in respostas:
            try:
                dados = json.loads(r.dados_json or '{}')
            except Exception:
                dados = {}
            if r.apresentou_sintoma:
                com_sintoma += 1
            if r.buscou_atendimento:
                buscou_atend += 1
            if r.usou_remedio:
                usou_remedio += 1
            for s in dados.get('sintomas', []) or []:
                if s in sintoma_counts:
                    sintoma_counts[s] += 1

        chart = {
            'labels': list(sintoma_counts.keys()),
            'data': list(sintoma_counts.values()),
        }

        return render_template(
            'scih/campanha_detalhe.html',
            campanha=camp,
            pacientes=pacientes,
            respostas=respostas,
            chart=chart,
            sintomas_opcoes=SINTOMAS_OPCOES,
            com_sintoma=com_sintoma,
            buscou_atend=buscou_atend,
            usou_remedio=usou_remedio,
            template_info=TEMPLATES_PESQUISA.get(camp.template, {}),
        )

    # =========================================================================
    # AÇÕES NA CAMPANHA
    # =========================================================================
    @app.route('/scih/campanha/<int:id>/iniciar', methods=['POST'])
    @login_required
    def scih_campanha_iniciar(id):
        if not _exige_scih():
            return redirect(url_for('login'))
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)
        if enviar_campanha_scih_task is None:
            flash('Sistema de envio (Celery) não está disponível.', 'danger')
            return redirect(url_for('scih_campanha_detalhe', id=id))

        base_url = request.host_url.rstrip('/')
        camp.status = 'enviando'
        camp.status_msg = 'Iniciado pelo usuário'
        db.session.commit()
        result = enviar_campanha_scih_task.delay(camp.id, base_url)
        camp.celery_task_id = result.id
        db.session.commit()
        flash('Envio iniciado!', 'success')
        return redirect(url_for('scih_campanha_detalhe', id=id))

    @app.route('/scih/campanha/<int:id>/pausar', methods=['POST'])
    @login_required
    def scih_campanha_pausar(id):
        if not _exige_scih():
            return redirect(url_for('login'))
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)
        camp.status = 'pausado'
        camp.status_msg = 'Pausado pelo usuário'
        db.session.commit()
        flash('Campanha pausada.', 'info')
        return redirect(url_for('scih_campanha_detalhe', id=id))

    @app.route('/scih/campanha/<int:id>/continuar', methods=['POST'])
    @login_required
    def scih_campanha_continuar(id):
        if not _exige_scih():
            return redirect(url_for('login'))
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)
        if enviar_campanha_scih_task is None:
            flash('Sistema de envio (Celery) não está disponível.', 'danger')
            return redirect(url_for('scih_campanha_detalhe', id=id))

        base_url = request.host_url.rstrip('/')
        camp.status = 'enviando'
        camp.status_msg = 'Retomado pelo usuário'
        db.session.commit()
        result = enviar_campanha_scih_task.delay(camp.id, base_url)
        camp.celery_task_id = result.id
        db.session.commit()
        flash('Campanha retomada.', 'success')
        return redirect(url_for('scih_campanha_detalhe', id=id))

    @app.route('/scih/campanha/<int:id>/excluir', methods=['POST'])
    @login_required
    def scih_campanha_excluir(id):
        if not _exige_scih():
            return redirect(url_for('login'))
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)
        db.session.delete(camp)
        db.session.commit()
        flash('Campanha excluída.', 'info')
        return redirect(url_for('scih_dashboard'))

    # =========================================================================
    # EXPORTAR EXCEL
    # =========================================================================
    @app.route('/scih/campanha/<int:id>/exportar')
    @login_required
    def scih_campanha_exportar(id):
        if not _exige_scih():
            return redirect(url_for('login'))
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            abort(403)

        rows = []
        for p in camp.pacientes.order_by(PacienteSCIH.id).all():
            resp = p.resposta
            try:
                dados = json.loads(resp.dados_json) if resp and resp.dados_json else {}
            except Exception:
                dados = {}
            rows.append({
                'Nome': p.nome,
                'Telefone': p.telefone,
                'Idade': p.idade or '',
                'Data Cirurgia': p.data_cirurgia or '',
                'Status': p.status,
                'Enviado em': p.data_envio_mensagem.strftime('%d/%m/%Y %H:%M') if p.data_envio_mensagem else '',
                'Erro Envio': p.erro_envio or '',
                'Respondida': 'Sim' if resp else 'Não',
                'Data Resposta': resp.data_resposta.strftime('%d/%m/%Y %H:%M') if resp and resp.data_resposta else '',
                'Apresentou Sintomas': 'Sim' if resp and resp.apresentou_sintoma else ('Não' if resp else ''),
                'Sintomas': ', '.join(dados.get('sintomas', []) or []) if resp else '',
                'Buscou Atendimento': 'Sim' if resp and resp.buscou_atendimento else ('Não' if resp else ''),
                'Usou Remédio': 'Sim' if resp and resp.usou_remedio else ('Não' if resp else ''),
                'Qual Remédio': (dados.get('qual_remedio') or '') if resp else '',
                'Observações': (dados.get('observacoes') or '') if resp else '',
            })

        df = pd.DataFrame(rows)
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df.to_excel(w, sheet_name='Pacientes', index=False)
        out.seek(0)
        return send_file(
            out,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'scih_campanha_{id}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    # =========================================================================
    # PROGRESSO (polling JSON)
    # =========================================================================
    @app.route('/scih/campanha/<int:id>/progresso')
    @login_required
    def scih_campanha_progresso(id):
        if not _exige_scih():
            return jsonify({'erro': 'acesso negado'}), 403
        camp = CampanhaSCIH.query.get_or_404(id)
        if camp.criador_id != current_user.id and not current_user.is_admin:
            return jsonify({'erro': 'acesso negado'}), 403
        camp.atualizar_stats()
        return jsonify({
            'status': camp.status,
            'status_msg': camp.status_msg,
            'total_pacientes': camp.total_pacientes,
            'total_enviados': camp.total_enviados,
            'total_respondidos': camp.total_respondidos,
            'total_erros': camp.total_erros,
            'pct_resposta': camp.pct_resposta(),
        })

    # =========================================================================
    # PÁGINA PÚBLICA DA PESQUISA (sem login, acesso por token)
    # =========================================================================
    @app.route('/p/<token>', methods=['GET', 'POST'])
    def pesquisa_publica(token):
        paciente = PacienteSCIH.query.filter_by(token=token).first()
        if not paciente:
            return render_template('scih/pesquisa_invalida.html'), 404

        campanha = paciente.campanha
        template_info = TEMPLATES_PESQUISA.get(campanha.template, TEMPLATES_PESQUISA['CESARIANA'])

        # Já respondeu?
        if paciente.resposta:
            return render_template(
                'scih/pesquisa_obrigado.html',
                ja_respondeu=True,
                template_info=template_info,
            )

        if request.method == 'POST':
            try:
                form = request.form

                def _bool(v):
                    return str(v).strip().upper() in ('SIM', 'S', 'YES', '1', 'TRUE')

                apresentou = _bool(form.get('apresentou_sintoma', ''))
                sintomas = form.getlist('sintomas') if apresentou else []
                buscou = _bool(form.get('buscou_atendimento', ''))
                usou = _bool(form.get('usou_remedio', ''))
                qual_remedio = form.get('qual_remedio', '').strip() if usou else ''
                observacoes = form.get('observacoes', '').strip()

                dados = {
                    'nome': form.get('nome', '').strip(),
                    'idade': form.get('idade', '').strip(),
                    'data_ligacao': datetime.utcnow().strftime('%Y-%m-%d'),
                    'data_cirurgia': form.get('data_cirurgia', '').strip(),
                    'apresentou_sintoma': apresentou,
                    'sintomas': [s for s in sintomas if s in SINTOMAS_OPCOES],
                    'buscou_atendimento': buscou,
                    'usou_remedio': usou,
                    'qual_remedio': qual_remedio,
                    'observacoes': observacoes,
                }

                resposta = RespostaSCIH(
                    paciente_id=paciente.id,
                    campanha_id=campanha.id,
                    dados_json=json.dumps(dados, ensure_ascii=False),
                    apresentou_sintoma=apresentou,
                    buscou_atendimento=buscou,
                    usou_remedio=usou,
                    ip=(request.headers.get('X-Forwarded-For') or request.remote_addr or '')[:45],
                    user_agent=(request.headers.get('User-Agent') or '')[:500],
                )
                db.session.add(resposta)
                paciente.status = 'RESPONDIDO'
                paciente.data_resposta = datetime.utcnow()
                db.session.commit()
                campanha.atualizar_stats()

                return render_template(
                    'scih/pesquisa_obrigado.html',
                    ja_respondeu=False,
                    template_info=template_info,
                )
            except Exception as e:
                logger.exception(f"Erro salvando resposta SCIH (token={token}): {e}")
                flash('Não foi possível salvar sua resposta. Tente novamente.', 'danger')

        return render_template(
            'scih/pesquisa_publica.html',
            paciente=paciente,
            campanha=campanha,
            template_info=template_info,
            sintomas_opcoes=SINTOMAS_OPCOES,
            data_hoje=datetime.now().strftime('%d/%m/%Y'),
        )

    logger.info("Rotas SCIH registradas")
