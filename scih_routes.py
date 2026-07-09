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
        WhatsApp, ConfigWhatsApp, formatar_numero, csrf, TZ_FORTALEZA
    )

    # Filtro Jinja: converte um datetime salvo em UTC para o horário de
    # Fortaleza (UTC-3) na hora de exibir. Datetimes naive são tratados como UTC.
    def _fortaleza_dt(dt, fmt='%d/%m/%Y %H:%M'):
        if not dt:
            return ''
        try:
            import pytz
            if dt.tzinfo is None:
                dt = pytz.utc.localize(dt)
            return dt.astimezone(TZ_FORTALEZA).strftime(fmt)
        except Exception:
            return dt.strftime(fmt)

    app.jinja_env.filters['fortaleza_dt'] = _fortaleza_dt

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
                aba = request.form.get('aba', '').strip()

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

                # Detectar abas disponíveis e ler a escolhida (ou a primeira)
                try:
                    xls = pd.ExcelFile(arquivo)
                    abas_disponiveis = xls.sheet_names
                except Exception as e:
                    flash(f'Não consegui abrir o arquivo Excel: {e}', 'danger')
                    return redirect(request.url)

                if aba:
                    # Tenta match case-insensitive
                    match = next((s for s in abas_disponiveis if s.strip().lower() == aba.lower()), None)
                    if not match:
                        flash(
                            f'Aba "{aba}" não encontrada. Abas disponíveis: '
                            + ', '.join(abas_disponiveis),
                            'danger'
                        )
                        return redirect(request.url)
                    aba_usada = match
                else:
                    aba_usada = abas_disponiveis[0]

                df = pd.read_excel(xls, sheet_name=aba_usada, dtype=str).fillna('')

                # Normalizar nomes de colunas (uppercase, sem espaços extras)
                df.columns = [str(c).strip().upper() for c in df.columns]

                col_nome = next((c for c in df.columns if c in ['PACIENTE', 'NOME', 'NOME COMPLETO']), None)
                col_tel = next((c for c in df.columns if c in ['FONE', 'TELEFONE', 'CELULAR', 'CONTATO']), None)
                col_data = next((c for c in df.columns if c in ['DATA CIRURGIA', 'DATA DA CIRURGIA', 'DATA']), None)
                col_idade = next((c for c in df.columns if c in ['IDADE']), None)
                col_cirurgia = next((c for c in df.columns if c in ['CIRURGIA', 'PROCEDIMENTO']), None)
                col_obs = next((c for c in df.columns if c in ['OBSERVACOES', 'OBSERVAÇÕES', 'OBS']), None)

                if not col_nome or not col_tel:
                    flash(
                        'Planilha precisa ter pelo menos as colunas PACIENTE (ou NOME) e FONE (ou TELEFONE). '
                        f'Colunas detectadas na aba "{aba_usada}": {", ".join(df.columns)}',
                        'danger'
                    )
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
                'Enviado em': _fortaleza_dt(p.data_envio_mensagem),
                'Erro Envio': p.erro_envio or '',
                'Respondida': 'Sim' if resp else 'Não',
                'Data Resposta': _fortaleza_dt(resp.data_resposta) if resp else '',
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

        # Atividade ao vivo: último envio bem-sucedido + próximo previsto + erros recentes
        ultimo_log = LogMsgSCIH.query.filter_by(
            campanha_id=camp.id, direcao='enviada', status='sucesso'
        ).order_by(LogMsgSCIH.id.desc()).first()

        ultimo_nome = None
        ultimo_telefone = None
        ultimo_quando = None
        proximo_em_segs = None
        if ultimo_log:
            pac_ult = db.session.get(PacienteSCIH, ultimo_log.paciente_id) if ultimo_log.paciente_id else None
            ultimo_nome = pac_ult.nome if pac_ult else None
            ultimo_telefone = ultimo_log.telefone
            ultimo_quando = _fortaleza_dt(ultimo_log.data, '%d/%m %H:%M:%S')
            if camp.status == 'enviando' and ultimo_log.data:
                intervalo = camp.calcular_intervalo()
                from datetime import datetime as _dt
                segs_passados = (_dt.utcnow() - ultimo_log.data).total_seconds()
                proximo_em_segs = max(int(intervalo - segs_passados), 0)

        proximo_paciente = None
        if camp.status == 'enviando':
            prox = PacienteSCIH.query.filter_by(
                campanha_id=camp.id, status='AGUARDANDO_ENVIO'
            ).order_by(PacienteSCIH.id).first()
            if prox:
                proximo_paciente = {'nome': prox.nome, 'telefone': prox.telefone}

        erros_recentes_q = LogMsgSCIH.query.filter_by(
            campanha_id=camp.id, status='erro'
        ).order_by(LogMsgSCIH.id.desc()).limit(5).all()
        erros_recentes = []
        for e in erros_recentes_q:
            pac_err = db.session.get(PacienteSCIH, e.paciente_id) if e.paciente_id else None
            erros_recentes.append({
                'nome': pac_err.nome if pac_err else '-',
                'telefone': e.telefone or '-',
                'erro': (e.erro or '')[:200],
                'quando': _fortaleza_dt(e.data, '%d/%m %H:%M'),
            })

        return jsonify({
            'status': camp.status,
            'status_msg': camp.status_msg,
            'total_pacientes': camp.total_pacientes,
            'total_enviados': camp.total_enviados,
            'total_respondidos': camp.total_respondidos,
            'total_sem_resposta': camp.total_sem_resposta_count(),
            'total_erros': camp.total_erros,
            'pct_resposta': camp.pct_resposta(),
            'enviados_hoje': camp.enviados_hoje or 0,
            'meta_diaria': camp.meta_diaria,
            'intervalo_segs': camp.calcular_intervalo(),
            # Atividade ao vivo
            'ultimo_enviado': {
                'nome': ultimo_nome,
                'telefone': ultimo_telefone,
                'quando': ultimo_quando,
            } if ultimo_nome else None,
            'proximo_paciente': proximo_paciente,
            'proximo_em_segs': proximo_em_segs,
            'erros_recentes': erros_recentes,
        })

    # =========================================================================
    # RESULTADOS COM FILTROS (pra Dr. Marcus classificar infecções)
    # =========================================================================
    def _coletar_respostas_filtradas():
        """Aplica os filtros vindos da query string e retorna lista de respostas."""
        campanha_id = request.args.get('campanha_id', '').strip()
        sintoma = request.args.get('sintoma', '').strip()
        apresentou = request.args.get('apresentou', '').strip()  # SIM/NAO/''
        buscou = request.args.get('buscou', '').strip()
        usou = request.args.get('usou', '').strip()
        data_de = request.args.get('data_de', '').strip()
        data_ate = request.args.get('data_ate', '').strip()
        template_filtro = request.args.get('template', '').strip().upper()
        status_paciente = request.args.get('status_paciente', '').strip()

        # Base: respostas das campanhas do usuário (ou todas se admin)
        q = RespostaSCIH.query.join(CampanhaSCIH, RespostaSCIH.campanha_id == CampanhaSCIH.id)
        if not current_user.is_admin:
            q = q.filter(CampanhaSCIH.criador_id == current_user.id)
        if campanha_id.isdigit():
            q = q.filter(RespostaSCIH.campanha_id == int(campanha_id))
        if template_filtro in TEMPLATES_PESQUISA:
            q = q.filter(CampanhaSCIH.template == template_filtro)
        if apresentou == 'SIM':
            q = q.filter(RespostaSCIH.apresentou_sintoma.is_(True))
        elif apresentou == 'NAO':
            q = q.filter(RespostaSCIH.apresentou_sintoma.is_(False))
        if buscou == 'SIM':
            q = q.filter(RespostaSCIH.buscou_atendimento.is_(True))
        elif buscou == 'NAO':
            q = q.filter(RespostaSCIH.buscou_atendimento.is_(False))
        if usou == 'SIM':
            q = q.filter(RespostaSCIH.usou_remedio.is_(True))
        elif usou == 'NAO':
            q = q.filter(RespostaSCIH.usou_remedio.is_(False))
        if data_de:
            try:
                d = datetime.strptime(data_de, '%Y-%m-%d')
                q = q.filter(RespostaSCIH.data_resposta >= d)
            except ValueError:
                pass
        if data_ate:
            try:
                d = datetime.strptime(data_ate, '%Y-%m-%d')
                # incluir o dia inteiro
                d = d.replace(hour=23, minute=59, second=59)
                q = q.filter(RespostaSCIH.data_resposta <= d)
            except ValueError:
                pass

        respostas = q.order_by(RespostaSCIH.data_resposta.desc()).all()

        # Filtro por sintoma específico precisa parsear o JSON (não dá pra fazer no SQL portável)
        if sintoma and sintoma in SINTOMAS_OPCOES:
            filtradas = []
            for r in respostas:
                try:
                    dados = json.loads(r.dados_json or '{}')
                except Exception:
                    dados = {}
                if sintoma in (dados.get('sintomas') or []):
                    filtradas.append(r)
            respostas = filtradas

        return respostas, {
            'campanha_id': campanha_id,
            'sintoma': sintoma,
            'apresentou': apresentou,
            'buscou': buscou,
            'usou': usou,
            'data_de': data_de,
            'data_ate': data_ate,
            'template': template_filtro,
            'status_paciente': status_paciente,
        }

    # Classificação automática de sintomas sugestivos de ISC desativada.
    # Quem decide o que é "caso de atenção" é o Dr. Marcus na análise manual.
    SINTOMAS_ATENCAO = set()

    @app.route('/scih/respostas')
    @login_required
    def scih_respostas():
        if not _exige_scih():
            return redirect(url_for('login'))

        respostas, filtros = _coletar_respostas_filtradas()

        # Enriquecer com dados parseados + agregações
        respostas_view = []
        sintoma_counts = {s: 0 for s in SINTOMAS_OPCOES}
        com_sintoma = 0
        buscou_atend = 0
        usou_remedio = 0
        atencao = []  # casos com pelo menos um sintoma de atenção
        por_dia = {}  # YYYY-MM-DD -> int
        por_template = {'CESARIANA': 0, 'MASTOLOGIA': 0}
        por_campanha = {}  # campanha_id -> {'nome':..., 'count': N}

        for r in respostas:
            try:
                dados = json.loads(r.dados_json or '{}')
            except Exception:
                dados = {}
            p = r.paciente
            c = p.campanha if p else None
            sintomas_pac = [s for s in (dados.get('sintomas') or []) if s in sintoma_counts]
            for s in sintomas_pac:
                sintoma_counts[s] += 1
            if r.apresentou_sintoma:
                com_sintoma += 1
            if r.buscou_atendimento:
                buscou_atend += 1
            if r.usou_remedio:
                usou_remedio += 1
            if r.data_resposta:
                # Agregação por dia também em horário de Fortaleza
                try:
                    import pytz
                    d_local = (pytz.utc.localize(r.data_resposta) if r.data_resposta.tzinfo is None else r.data_resposta).astimezone(TZ_FORTALEZA)
                except Exception:
                    d_local = r.data_resposta
                dia = d_local.strftime('%Y-%m-%d')
                por_dia[dia] = por_dia.get(dia, 0) + 1
            if c and c.template in por_template:
                por_template[c.template] += 1
            if c:
                if c.id not in por_campanha:
                    por_campanha[c.id] = {'nome': c.nome, 'count': 0}
                por_campanha[c.id]['count'] += 1

            severos = [s for s in sintomas_pac if s in SINTOMAS_ATENCAO]
            item = {
                'r': r,
                'dados': dados,
                'severos': severos,
            }
            respostas_view.append(item)
            if severos:
                atencao.append(item)

        total = len(respostas_view)
        pct_sintoma = round(com_sintoma / total * 100, 1) if total else 0
        pct_buscou = round(buscou_atend / total * 100, 1) if total else 0
        pct_remedio = round(usou_remedio / total * 100, 1) if total else 0

        # Top 5 sintomas mais reportados (para destaque)
        top_sintomas = sorted(
            ((s, n) for s, n in sintoma_counts.items() if n > 0),
            key=lambda x: x[1], reverse=True
        )[:5]

        # Series ordenadas para Chart.js
        dias_ordenados = sorted(por_dia.keys())
        chart = {
            'sintomas_labels': list(sintoma_counts.keys()),
            'sintomas_data': list(sintoma_counts.values()),
            'apresentou_data': [com_sintoma, max(total - com_sintoma, 0)],
            'buscou_data': [buscou_atend, max(total - buscou_atend, 0)],
            'remedio_data': [usou_remedio, max(total - usou_remedio, 0)],
            'timeline_labels': [datetime.strptime(d, '%Y-%m-%d').strftime('%d/%m') for d in dias_ordenados],
            'timeline_data': [por_dia[d] for d in dias_ordenados],
            'template_labels': list(por_template.keys()),
            'template_data': list(por_template.values()),
            'campanha_labels': [v['nome'] for v in por_campanha.values()],
            'campanha_data': [v['count'] for v in por_campanha.values()],
        }

        # Lista de campanhas para o select do filtro
        camp_q = CampanhaSCIH.query
        if not current_user.is_admin:
            camp_q = camp_q.filter_by(criador_id=current_user.id)
        campanhas = camp_q.order_by(CampanhaSCIH.id.desc()).all()

        return render_template(
            'scih/respostas.html',
            respostas=respostas_view,
            atencao=atencao,
            campanhas=campanhas,
            sintomas_opcoes=SINTOMAS_OPCOES,
            sintomas_atencao=SINTOMAS_ATENCAO,
            templates=TEMPLATES_PESQUISA,
            f=filtros,
            total=total,
            com_sintoma=com_sintoma,
            buscou_atend=buscou_atend,
            usou_remedio=usou_remedio,
            pct_sintoma=pct_sintoma,
            pct_buscou=pct_buscou,
            pct_remedio=pct_remedio,
            top_sintomas=top_sintomas,
            chart=chart,
        )

    @app.route('/scih/respostas/exportar')
    @login_required
    def scih_respostas_exportar():
        if not _exige_scih():
            return redirect(url_for('login'))

        respostas, _f = _coletar_respostas_filtradas()
        rows = []
        for r in respostas:
            try:
                dados = json.loads(r.dados_json or '{}')
            except Exception:
                dados = {}
            p = r.paciente
            c = r.paciente.campanha if r.paciente else None
            rows.append({
                'Campanha': c.nome if c else '',
                'Template': c.template if c else '',
                'Paciente': p.nome if p else '',
                'Telefone': p.telefone if p else '',
                'Idade': (p.idade if p else '') or dados.get('idade', ''),
                'Data Cirurgia': (p.data_cirurgia if p else '') or dados.get('data_cirurgia', ''),
                'Data Resposta': _fortaleza_dt(r.data_resposta),
                'Apresentou Sintomas': 'Sim' if r.apresentou_sintoma else 'Não',
                'Sintomas': ', '.join(dados.get('sintomas', []) or []),
                'Buscou Atendimento': 'Sim' if r.buscou_atendimento else 'Não',
                'Usou Remédio': 'Sim' if r.usou_remedio else 'Não',
                'Qual Remédio': dados.get('qual_remedio', '') or '',
                'Observações': dados.get('observacoes', '') or '',
            })

        df = pd.DataFrame(rows)
        out = BytesIO()
        with pd.ExcelWriter(out, engine='openpyxl') as w:
            df.to_excel(w, sheet_name='Respostas', index=False)
        out.seek(0)
        return send_file(
            out,
            mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            as_attachment=True,
            download_name=f'scih_respostas_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
        )

    # =========================================================================
    # RELATÓRIO ESTATÍSTICO (proporções com IC 95% + qui-quadrado/Fisher)
    # =========================================================================
    def _wilson_ci(k, n, alpha=0.05):
        """Intervalo de confiança Wilson pra proporção. Mais robusto que normal pra N pequeno."""
        import math
        if n == 0:
            return (0.0, 0.0, 0.0)
        from scipy.stats import norm
        z = norm.ppf(1 - alpha / 2)
        p = k / n
        denom = 1 + z * z / n
        center = (p + z * z / (2 * n)) / denom
        margin = (z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))) / denom
        return (p, max(0.0, center - margin), min(1.0, center + margin))

    def _testar_associacao_2x2(a, b, c, d):
        """
        Tabela 2x2:
                  exposto    nao_exposto
        evento       a            b
        nao_evento   c            d

        Retorna: (teste_nome, p_value, odds_ratio, recomenda_fisher)
        """
        from scipy.stats import chi2_contingency, fisher_exact
        table = [[a, b], [c, d]]
        # Se alguma célula esperada < 5, prefere Fisher
        try:
            chi2, p_chi, dof, expected = chi2_contingency(table, correction=False)
            min_exp = min(min(row) for row in expected)
            usar_fisher = min_exp < 5
            if usar_fisher:
                odds, p = fisher_exact(table)
                return ('Fisher exato', p, odds, True)
            odds = (a * d) / (b * c) if (b * c) > 0 else float('inf')
            return ('Qui-quadrado', p_chi, odds, False)
        except Exception:
            return ('-', None, None, False)

    @app.route('/scih/relatorio-estatistico')
    @login_required
    def scih_relatorio_estatistico():
        if not _exige_scih():
            return redirect(url_for('login'))

        # Carrega campanhas do usuário
        camp_q = CampanhaSCIH.query
        if not current_user.is_admin:
            camp_q = camp_q.filter_by(criador_id=current_user.id)
        campanhas_disponiveis = camp_q.order_by(CampanhaSCIH.id.desc()).all()

        # Campanhas selecionadas.
        # Aceita 2 formatos:
        # - <select multiple>: envia ?campanhas=1&campanhas=2&campanhas=3 (getlist)
        # - Link/URL direta: ?campanhas=1,2,3 (CSV)
        camp_ids = []
        valores = request.args.getlist('campanhas')
        for v in valores:
            for x in str(v).split(','):
                x = x.strip()
                if x.isdigit():
                    n = int(x)
                    if n not in camp_ids:
                        camp_ids.append(n)

        relatorio = None
        if camp_ids:
            # Filtra respostas das campanhas escolhidas (do usuário)
            q = RespostaSCIH.query.join(
                CampanhaSCIH, RespostaSCIH.campanha_id == CampanhaSCIH.id
            ).filter(RespostaSCIH.campanha_id.in_(camp_ids))
            if not current_user.is_admin:
                q = q.filter(CampanhaSCIH.criador_id == current_user.id)
            respostas = q.all()

            # Conta pacientes das campanhas pra denominadores
            pac_q = PacienteSCIH.query.filter(PacienteSCIH.campanha_id.in_(camp_ids))
            total_cadastrados = pac_q.count()
            total_recebeu_msg = pac_q.filter(
                PacienteSCIH.status.in_(['ENVIADO', 'RESPONDIDO', 'SEM_RESPOSTA'])
            ).count()
            total_sem_resposta_real = pac_q.filter_by(status='SEM_RESPOSTA').count()
            total_erros = pac_q.filter_by(status='ERRO').count()

            n_respondidos = len(respostas)
            taxa_resposta = (n_respondidos / total_recebeu_msg * 100) if total_recebeu_msg else 0

            # Parse dos JSONs
            parsed = []
            for r in respostas:
                try:
                    dados = json.loads(r.dados_json or '{}')
                except Exception:
                    dados = {}
                parsed.append({
                    'r': r,
                    'd': dados,
                    'sintomas': dados.get('sintomas', []) or [],
                    'paciente': r.paciente,
                    'campanha': r.paciente.campanha if r.paciente else None,
                })

            # === Proporções gerais (com IC 95% Wilson) ===
            indicadores_principais = []
            for label, key, color in [
                ('Apresentou algum sintoma', 'apresentou_sintoma', 'danger'),
                ('Buscou atendimento médico', 'buscou_atendimento', 'primary'),
                ('Utilizou algum remédio', 'usou_remedio', 'warning'),
            ]:
                k = sum(1 for it in parsed if getattr(it['r'], key))
                p, lo, hi = _wilson_ci(k, n_respondidos)
                indicadores_principais.append({
                    'label': label, 'k': k, 'n': n_respondidos,
                    'pct': round(p * 100, 1),
                    'ic_lo': round(lo * 100, 1), 'ic_hi': round(hi * 100, 1),
                    'color': color,
                })

            # === Prevalência por sintoma específico (IC 95%) ===
            prevalencia_sintomas = []
            for s in SINTOMAS_OPCOES:
                k = sum(1 for it in parsed if s in it['sintomas'])
                p, lo, hi = _wilson_ci(k, n_respondidos)
                prevalencia_sintomas.append({
                    'sintoma': s, 'k': k, 'n': n_respondidos,
                    'pct': round(p * 100, 1),
                    'ic_lo': round(lo * 100, 1), 'ic_hi': round(hi * 100, 1),
                })
            prevalencia_sintomas.sort(key=lambda x: -x['k'])

            # === Análise de sensibilidade (não-resposta) ===
            # Cenário PESSIMISTA: todos sem_resposta tiveram o desfecho
            # Cenário OTIMISTA: nenhum sem_resposta teve
            sensibilidade = []
            for label, key in [
                ('Apresentou sintoma', 'apresentou_sintoma'),
                ('Buscou atendimento', 'buscou_atendimento'),
            ]:
                k_obs = sum(1 for it in parsed if getattr(it['r'], key))
                pessimista_k = k_obs + total_sem_resposta_real
                otimista_k = k_obs
                base = total_recebeu_msg
                if base > 0:
                    p_obs = round(k_obs / n_respondidos * 100, 1) if n_respondidos else 0
                    p_pess = round(pessimista_k / base * 100, 1)
                    p_otim = round(otimista_k / base * 100, 1)
                else:
                    p_obs = p_pess = p_otim = 0
                sensibilidade.append({
                    'label': label,
                    'observado': p_obs,
                    'pessimista': p_pess,
                    'otimista': p_otim,
                })

            # === Associações 2x2 (Qui-quadrado / Fisher) ===
            def cell_count(filtro_a, filtro_b):
                return sum(1 for it in parsed if filtro_a(it) and filtro_b(it))

            associacoes = []
            pares = [
                ('Sintoma × Buscou atendimento',
                 lambda it: it['r'].apresentou_sintoma,
                 lambda it: it['r'].buscou_atendimento),
                ('Sintoma × Usou remédio',
                 lambda it: it['r'].apresentou_sintoma,
                 lambda it: it['r'].usou_remedio),
                ('Buscou atendimento × Usou remédio',
                 lambda it: it['r'].buscou_atendimento,
                 lambda it: it['r'].usou_remedio),
            ]
            for label, fa, fb in pares:
                a = cell_count(fa, fb)          # ambos sim
                b = cell_count(fa, lambda it: not fb(it))  # A sim, B não
                c = cell_count(lambda it: not fa(it), fb)  # A não, B sim
                d = cell_count(lambda it: not fa(it), lambda it: not fb(it))  # ambos não
                teste, p, odds, usou_fisher = _testar_associacao_2x2(a, b, c, d)
                associacoes.append({
                    'label': label,
                    'tabela': {'a': a, 'b': b, 'c': c, 'd': d},
                    'teste': teste,
                    'p_value': round(p, 4) if p is not None else None,
                    'odds_ratio': round(odds, 2) if odds is not None and odds != float('inf') else None,
                    'significativo': (p is not None and p < 0.05),
                    'usou_fisher': usou_fisher,
                })

            # === Comparação por procedimento (Cesariana × Mastologia) ===
            por_procedimento = []
            grupos = {'CESARIANA': [], 'MASTOLOGIA': []}
            for it in parsed:
                t = it['campanha'].template if it['campanha'] else None
                if t in grupos:
                    grupos[t].append(it)

            comparacao_proc = None
            if len(grupos['CESARIANA']) >= 5 and len(grupos['MASTOLOGIA']) >= 5:
                # Comparar taxa de "apresentou sintoma" entre os 2 grupos
                a = sum(1 for it in grupos['CESARIANA'] if it['r'].apresentou_sintoma)
                c = len(grupos['CESARIANA']) - a
                b = sum(1 for it in grupos['MASTOLOGIA'] if it['r'].apresentou_sintoma)
                d = len(grupos['MASTOLOGIA']) - b
                teste, p, odds, _ = _testar_associacao_2x2(a, b, c, d)
                comparacao_proc = {
                    'cesariana': {
                        'n': len(grupos['CESARIANA']),
                        'com_sintoma': a,
                        'pct': round(a / len(grupos['CESARIANA']) * 100, 1) if grupos['CESARIANA'] else 0,
                    },
                    'mastologia': {
                        'n': len(grupos['MASTOLOGIA']),
                        'com_sintoma': b,
                        'pct': round(b / len(grupos['MASTOLOGIA']) * 100, 1) if grupos['MASTOLOGIA'] else 0,
                    },
                    'teste': teste,
                    'p_value': round(p, 4) if p is not None else None,
                    'odds_ratio': round(odds, 2) if odds is not None and odds != float('inf') else None,
                    'significativo': (p is not None and p < 0.05),
                }

            # === Alertas metodológicos (régua calibrada pra MEAC) ===
            alertas = []
            if n_respondidos < 20:
                alertas.append({
                    'tipo': 'danger',
                    'msg': f'Amostra insuficiente (N={n_respondidos}). Considere estender o período '
                           f'ou agregar mais campanhas antes de tirar conclusões.'
                })
            elif n_respondidos < 50:
                alertas.append({
                    'tipo': 'warning',
                    'msg': f'Amostra pequena (N={n_respondidos}). Trate os números como TENDÊNCIA — '
                           f'compare com o histórico da MEAC, mas evite comparações entre subgrupos.'
                })
            if total_recebeu_msg > 0 and (total_sem_resposta_real / total_recebeu_msg) > 0.4:
                taxa_nr = round(total_sem_resposta_real / total_recebeu_msg * 100, 1)
                alertas.append({
                    'tipo': 'danger',
                    'msg': f'Alta taxa de não-resposta ({taxa_nr}%). Forte risco de viés de seleção — '
                           f'pacientes que responderam podem ser sistematicamente diferentes das que não responderam. '
                           f'Veja a análise de sensibilidade abaixo.'
                })
            if any(a['usou_fisher'] for a in associacoes):
                alertas.append({
                    'tipo': 'info',
                    'msg': 'Algumas associações usaram teste exato de Fisher porque a frequência esperada '
                           'em alguma célula era menor que 5 (mais robusto para N pequeno).'
                })

            relatorio = {
                'campanhas': [c for c in campanhas_disponiveis if c.id in camp_ids],
                'n_respondidos': n_respondidos,
                'total_cadastrados': total_cadastrados,
                'total_recebeu_msg': total_recebeu_msg,
                'total_sem_resposta_real': total_sem_resposta_real,
                'total_erros': total_erros,
                'taxa_resposta': round(taxa_resposta, 1),
                'indicadores_principais': indicadores_principais,
                'prevalencia_sintomas': prevalencia_sintomas,
                'sensibilidade': sensibilidade,
                'associacoes': associacoes,
                'comparacao_proc': comparacao_proc,
                'alertas': alertas,
                'gerado_em': _fortaleza_dt(datetime.utcnow()),
            }

        return render_template(
            'scih/relatorio_estatistico.html',
            campanhas_disponiveis=campanhas_disponiveis,
            camp_ids=camp_ids,
            relatorio=relatorio,
        )

    # =========================================================================
    # PÁGINA PÚBLICA DA PESQUISA (sem login, acesso por token)
    # =========================================================================
    # CSRF isento: a autenticação aqui é o token único na URL (já é um secret
    # que só a paciente recebeu). Manter o CSRF causaria falsos negativos quando
    # a paciente abre o link, fecha o navegador e volta depois.
    @app.route('/p/<token>', methods=['GET', 'POST'])
    @csrf.exempt
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

                # Data da "ligação" em horário de Fortaleza (não UTC)
                try:
                    import pytz as _pytz
                    _hoje_local = datetime.utcnow().replace(tzinfo=_pytz.utc).astimezone(TZ_FORTALEZA).strftime('%Y-%m-%d')
                except Exception:
                    _hoje_local = datetime.utcnow().strftime('%Y-%m-%d')

                dados = {
                    'nome': form.get('nome', '').strip(),
                    'idade': form.get('idade', '').strip(),
                    'data_ligacao': _hoje_local,
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
            data_hoje=_fortaleza_dt(datetime.utcnow(), '%d/%m/%Y'),
        )

    logger.info("Rotas SCIH registradas")

    # =========================================================================
    # TUTORIAL
    # =========================================================================
    @app.route('/scih/tutorial')
    @login_required
    def scih_tutorial():
        if not _exige_scih():
            return redirect(url_for('login'))

        return render_template('tutorial_scih.html')
