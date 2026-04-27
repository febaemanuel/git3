"""GERAL module: pesquisas, envios, wizard."""

import csv
import io
import json
from datetime import datetime, timedelta
from io import BytesIO

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template,
    request, send_file, url_for,
)
from flask_login import current_user, login_required
import pandas as pd

from app.extensions import db
from app.main import (
    CANAIS_RESPOSTA_GERAL, TIPOS_USO_GERAL,
    _exigir_usuario_geral, _get_envio_do_usuario,
    _get_pesquisa_do_usuario, _normalizar_telefones_textarea,
    _renderizar_mensagem_envio, logger,
)
from app.models import (
    ConfigUsuarioGeral, EnvioPesquisa, EnvioPesquisaTelefone,
    PerguntaPesquisa, Pesquisa, RespostaItem, RespostaPesquisa,
    STATUS_ENVIO_PESQUISA, STATUS_ENVIO_TELEFONE, TEMPLATES_PESQUISA,
    TIPOS_PERGUNTA,
)
from app.services.telefone import formatar_numero
from app.services.timezone import obter_agora_fortaleza


bp = Blueprint('geral', __name__)


@bp.route('/geral/dashboard')
@login_required
def geral_dashboard():
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir

    if not config.wizard_concluido:
        return redirect(url_for('geral.geral_wizard'))

    return render_template(
        'geral_dashboard.html',
        config=config,
        tipos_uso=config.tipos_uso_lista(),
    )
@bp.route('/geral/wizard', methods=['GET', 'POST'])
@login_required
def geral_wizard():
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir

    if request.method == 'POST':
        tipos_selecionados = [t for t in request.form.getlist('tipos_uso') if t in TIPOS_USO_GERAL]
        canal = request.form.get('canal_resposta', '').strip()

        if not tipos_selecionados:
            flash('Selecione ao menos um tipo de uso.', 'danger')
            return render_template('geral_wizard.html', config=config,
                                   tipos_uso=tipos_selecionados, canal_resposta=canal)

        if canal not in CANAIS_RESPOSTA_GERAL:
            flash('Selecione um canal de resposta válido.', 'danger')
            return render_template('geral_wizard.html', config=config,
                                   tipos_uso=tipos_selecionados, canal_resposta=canal)

        config.set_tipos_uso(tipos_selecionados)
        config.canal_resposta = canal
        config.wizard_concluido = True
        db.session.commit()

        flash('Configuração salva! Você já pode usar o sistema.', 'success')
        return redirect(url_for('geral.geral_dashboard'))

    return render_template(
        'geral_wizard.html',
        config=config,
        tipos_uso=config.tipos_uso_lista(),
        canal_resposta=config.canal_resposta or '',
    )
@bp.route('/geral/pesquisas')
@login_required
def geral_pesquisas_lista():
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir

    pesquisas = Pesquisa.query.filter_by(usuario_id=current_user.id) \
        .order_by(Pesquisa.data_criacao.desc()).all()

    # Pré-calcular contagem de respostas concluídas pra evitar N+1 no template.
    contagens = {}
    for p in pesquisas:
        contagens[p.id] = RespostaPesquisa.query.filter(
            RespostaPesquisa.pesquisa_id == p.id,
            RespostaPesquisa.concluida_em.isnot(None),
        ).count()

    return render_template(
        'geral_pesquisas_lista.html',
        pesquisas=pesquisas,
        contagens=contagens,
    )
@bp.route('/geral/pesquisas/nova', methods=['GET', 'POST'])
@login_required
def geral_pesquisa_nova():
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir

    if request.method == 'POST':
        titulo = (request.form.get('titulo') or '').strip()
        descricao = (request.form.get('descricao') or '').strip()
        mensagem_whatsapp = (request.form.get('mensagem_whatsapp') or '').strip()

        if not titulo:
            flash('Informe o título da pesquisa.', 'danger')
            return render_template('geral_pesquisa_form.html', pesquisa=None,
                                   titulo=titulo, descricao=descricao,
                                   mensagem_whatsapp=mensagem_whatsapp)

        pesquisa = Pesquisa(
            usuario_id=current_user.id,
            titulo=titulo,
            descricao=descricao or None,
            mensagem_whatsapp=mensagem_whatsapp or None,
            token_publico=Pesquisa.gerar_token(),
        )
        db.session.add(pesquisa)
        db.session.commit()
        flash('Pesquisa criada. Agora cadastre as perguntas.', 'success')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    return render_template('geral_pesquisa_form.html', pesquisa=None,
                           titulo='', descricao='', mensagem_whatsapp='')
@bp.route('/geral/pesquisas/templates')
@login_required
def geral_pesquisa_templates():
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    return render_template('geral_pesquisa_templates.html',
                           templates=TEMPLATES_PESQUISA)
@bp.route('/geral/pesquisas/templates/<key>/criar', methods=['POST'])
@login_required
def geral_pesquisa_criar_de_template(key):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir

    template = TEMPLATES_PESQUISA.get(key)
    if not template:
        flash('Template não encontrado.', 'danger')
        return redirect(url_for('geral.geral_pesquisa_templates'))

    pesquisa = Pesquisa(
        usuario_id=current_user.id,
        titulo=template['titulo'],
        descricao=template.get('descricao'),
        mensagem_whatsapp=template.get('mensagem_whatsapp'),
        token_publico=Pesquisa.gerar_token(),
    )
    db.session.add(pesquisa)
    db.session.flush()

    for ordem, p in enumerate(template.get('perguntas', []), start=1):
        pergunta = PerguntaPesquisa(
            pesquisa_id=pesquisa.id,
            ordem=ordem,
            texto=p['texto'],
            tipo=p['tipo'],
            obrigatoria=bool(p.get('obrigatoria', True)),
        )
        if p.get('opcoes'):
            pergunta.set_opcoes(p['opcoes'])
        db.session.add(pergunta)

    db.session.commit()
    flash(f'Pesquisa "{pesquisa.titulo}" criada a partir do template. Revise e ajuste se quiser.', 'success')
    return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))
@bp.route('/geral/pesquisas/<int:id>', methods=['GET', 'POST'])
@login_required
def geral_pesquisa_detalhe(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)

    if request.method == 'POST':
        pesquisa.titulo = (request.form.get('titulo') or pesquisa.titulo).strip()
        pesquisa.descricao = (request.form.get('descricao') or '').strip() or None
        pesquisa.mensagem_whatsapp = (request.form.get('mensagem_whatsapp') or '').strip() or None
        pesquisa.ativa = request.form.get('ativa') == 'on'
        db.session.commit()
        flash('Pesquisa atualizada.', 'success')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    link_publico = url_for('pesquisa_publica.pesquisa_publica', token=pesquisa.token_publico, _external=True)
    return render_template(
        'geral_pesquisa_form.html',
        pesquisa=pesquisa,
        titulo=pesquisa.titulo,
        descricao=pesquisa.descricao or '',
        mensagem_whatsapp=pesquisa.mensagem_whatsapp or '',
        link_publico=link_publico,
        tipos_pergunta=TIPOS_PERGUNTA,
    )
@bp.route('/geral/pesquisas/<int:id>/excluir', methods=['POST'])
@login_required
def geral_pesquisa_excluir(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)
    db.session.delete(pesquisa)
    db.session.commit()
    flash('Pesquisa removida.', 'info')
    return redirect(url_for('geral.geral_pesquisas_lista'))
@bp.route('/geral/pesquisas/<int:id>/perguntas', methods=['POST'])
@login_required
def geral_pesquisa_pergunta_criar(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)

    texto = (request.form.get('texto') or '').strip()
    tipo = (request.form.get('tipo') or 'TEXTO_CURTO').strip()
    opcoes_raw = (request.form.get('opcoes') or '').strip()
    obrigatoria = request.form.get('obrigatoria') == 'on'

    if not texto:
        flash('Digite o texto da pergunta.', 'danger')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))
    if tipo not in TIPOS_PERGUNTA:
        flash('Tipo de pergunta inválido.', 'danger')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    opcoes = []
    if tipo == 'MULTI_ESCOLHA':
        opcoes = [o.strip() for o in opcoes_raw.split('\n') if o.strip()]
        if len(opcoes) < 2:
            flash('Múltipla escolha precisa de pelo menos 2 opções (uma por linha).', 'danger')
            return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    proxima_ordem = (db.session.query(db.func.max(PerguntaPesquisa.ordem))
                     .filter_by(pesquisa_id=pesquisa.id).scalar() or 0) + 1

    pergunta = PerguntaPesquisa(
        pesquisa_id=pesquisa.id,
        ordem=proxima_ordem,
        texto=texto,
        tipo=tipo,
        obrigatoria=obrigatoria,
    )
    if opcoes:
        pergunta.set_opcoes(opcoes)
    db.session.add(pergunta)
    db.session.commit()
    flash('Pergunta adicionada.', 'success')
    return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))
@bp.route('/geral/pesquisas/<int:id>/perguntas/<int:pid>/excluir', methods=['POST'])
@login_required
def geral_pesquisa_pergunta_excluir(id, pid):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)
    pergunta = PerguntaPesquisa.query.filter_by(id=pid, pesquisa_id=pesquisa.id).first_or_404()
    db.session.delete(pergunta)
    db.session.commit()
    flash('Pergunta removida.', 'info')
    return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))
@bp.route('/geral/pesquisas/<int:id>/stats')
@login_required
def geral_pesquisa_stats(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)

    total_iniciadas = RespostaPesquisa.query.filter_by(pesquisa_id=pesquisa.id).count()
    total_concluidas = RespostaPesquisa.query.filter(
        RespostaPesquisa.pesquisa_id == pesquisa.id,
        RespostaPesquisa.concluida_em.isnot(None),
    ).count()

    # Para cada pergunta, monta os dados que viram gráfico.
    # SIM_NAO e MULTI_ESCOLHA → pizza/barra com contagem por opção.
    # ESCALA_1_10 → distribuição 1..10.
    # TEXTO_* → lista as últimas 50 respostas.
    respostas_concluidas_ids = [r.id for r in RespostaPesquisa.query.filter(
        RespostaPesquisa.pesquisa_id == pesquisa.id,
        RespostaPesquisa.concluida_em.isnot(None),
    ).all()]

    perguntas_dados = []
    for p in pesquisa.perguntas:
        itens = RespostaItem.query.filter(
            RespostaItem.pergunta_id == p.id,
            RespostaItem.resposta_id.in_(respostas_concluidas_ids) if respostas_concluidas_ids else False,
        ).all() if respostas_concluidas_ids else []

        dado = {'pergunta': p, 'total': len(itens)}

        if p.tipo == 'SIM_NAO':
            sim = sum(1 for i in itens if (i.valor or '').strip().upper() in ('SIM', 'S', 'TRUE', '1'))
            nao = len(itens) - sim
            dado['labels'] = ['Sim', 'Não']
            dado['data'] = [sim, nao]
        elif p.tipo == 'MULTI_ESCOLHA':
            contagem = {}
            for opt in p.opcoes_lista():
                contagem[opt] = 0
            for i in itens:
                for sel in i.valor_lista():
                    if sel in contagem:
                        contagem[sel] += 1
                    else:
                        contagem[sel] = 1
            dado['labels'] = list(contagem.keys())
            dado['data'] = list(contagem.values())
        elif p.tipo == 'ESCALA_1_10':
            buckets = [0] * 10
            for i in itens:
                try:
                    n = int((i.valor or '0').strip())
                    if 1 <= n <= 10:
                        buckets[n - 1] += 1
                except ValueError:
                    pass
            dado['labels'] = [str(n) for n in range(1, 11)]
            dado['data'] = buckets
        else:  # TEXTO_CURTO / TEXTO_LONGO
            dado['amostras'] = [(i.valor or '') for i in itens[-50:]]

        perguntas_dados.append(dado)

    return render_template(
        'geral_pesquisa_stats.html',
        pesquisa=pesquisa,
        total_iniciadas=total_iniciadas,
        total_concluidas=total_concluidas,
        perguntas_dados=perguntas_dados,
    )
@bp.route('/geral/pesquisas/<int:id>/exportar')
@login_required
def geral_pesquisa_exportar(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)

    perguntas = pesquisa.perguntas
    respostas = RespostaPesquisa.query.filter_by(pesquisa_id=pesquisa.id) \
        .order_by(RespostaPesquisa.iniciada_em).all()

    # Constrói um DataFrame com uma linha por resposta e uma coluna por pergunta.
    linhas = []
    for r in respostas:
        linha = {
            'iniciada_em': r.iniciada_em.strftime('%Y-%m-%d %H:%M') if r.iniciada_em else '',
            'concluida_em': r.concluida_em.strftime('%Y-%m-%d %H:%M') if r.concluida_em else '',
        }
        valores = {i.pergunta_id: i for i in r.itens}
        for p in perguntas:
            item = valores.get(p.id)
            if not item:
                linha[p.texto] = ''
            elif p.tipo == 'MULTI_ESCOLHA':
                linha[p.texto] = ', '.join(item.valor_lista())
            else:
                linha[p.texto] = item.valor or ''
        linhas.append(linha)

    df = pd.DataFrame(linhas) if linhas else pd.DataFrame(
        columns=['iniciada_em', 'concluida_em'] + [p.texto for p in perguntas]
    )

    buf = BytesIO()
    with pd.ExcelWriter(buf, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Respostas', index=False)
    buf.seek(0)

    nome_arquivo = f"pesquisa_{pesquisa.id}_{datetime.utcnow().strftime('%Y%m%d_%H%M')}.xlsx"
    return send_file(buf,
                     as_attachment=True,
                     download_name=nome_arquivo,
                     mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
@bp.route('/geral/pesquisas/<int:id>/enviar', methods=['GET', 'POST'])
@login_required
def geral_pesquisa_enviar(id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    pesquisa = _get_pesquisa_do_usuario(id)

    if not pesquisa.perguntas:
        flash('Cadastre ao menos uma pergunta antes de enviar.', 'warning')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    if not pesquisa.ativa:
        flash('Reative a pesquisa antes de enviar o link.', 'warning')
        return redirect(url_for('geral.geral_pesquisa_detalhe', id=pesquisa.id))

    link_publico = url_for('pesquisa_publica.pesquisa_publica', token=pesquisa.token_publico, _external=True)
    mensagem_padrao = pesquisa.mensagem_whatsapp or (
        f'Olá {{NOME}}! Por favor, responda nossa pesquisa: {{LINK}}'
    )

    if request.method == 'POST':
        nome = (request.form.get('nome') or '').strip() or None
        mensagem_template = (request.form.get('mensagem') or '').strip() or mensagem_padrao
        telefones_raw = request.form.get('telefones') or ''
        try:
            intervalo = max(5, int(request.form.get('intervalo', '60')))
            hora_inicio = max(0, min(23, int(request.form.get('hora_inicio', '8'))))
            hora_fim = max(0, min(23, int(request.form.get('hora_fim', '18'))))
            meta_diaria = max(1, int(request.form.get('meta_diaria', '50')))
        except ValueError:
            flash('Valores numéricos inválidos.', 'danger')
            return render_template('geral_envio_form.html', pesquisa=pesquisa,
                                   link_publico=link_publico, mensagem=mensagem_template,
                                   telefones=telefones_raw, nome=nome)

        telefones = _normalizar_telefones_textarea(telefones_raw)
        if not telefones:
            flash('Nenhum telefone válido. Use formato (85) 99999-9999, um por linha.', 'danger')
            return render_template('geral_envio_form.html', pesquisa=pesquisa,
                                   link_publico=link_publico, mensagem=mensagem_template,
                                   telefones=telefones_raw, nome=nome)

        envio = EnvioPesquisa(
            pesquisa_id=pesquisa.id,
            usuario_id=current_user.id,
            nome=nome,
            mensagem_template=mensagem_template,
            intervalo_segundos=intervalo,
            hora_inicio=hora_inicio,
            hora_fim=hora_fim,
            meta_diaria=meta_diaria,
            total=len(telefones),
        )
        db.session.add(envio)
        db.session.flush()

        for numero, nome_dest in telefones:
            db.session.add(EnvioPesquisaTelefone(
                envio_id=envio.id,
                numero=numero,
                nome=nome_dest,
            ))
        db.session.commit()

        # Disparar a task em background.
        try:
            from celery_app import celery
            res = celery.send_task('tasks.processar_envio_pesquisa', args=[envio.id])
            envio.celery_task_id = res.id
            db.session.commit()
        except Exception as e:
            envio.status = 'erro'
            envio.status_msg = f'Falha ao agendar task: {e}'
            db.session.commit()
            flash(f'Envio criado, mas o disparo falhou: {e}', 'danger')

        flash(f'Envio iniciado: {len(telefones)} destinatários.', 'success')
        return redirect(url_for('geral.geral_envio_progresso', envio_id=envio.id))

    return render_template('geral_envio_form.html', pesquisa=pesquisa,
                           link_publico=link_publico, mensagem=mensagem_padrao,
                           telefones='', nome='')
@bp.route('/geral/envios/<int:envio_id>')
@login_required
def geral_envio_progresso(envio_id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    envio = _get_envio_do_usuario(envio_id)

    pendentes = sum(1 for t in envio.telefones if t.status == 'pendente')
    return render_template('geral_envio_progresso.html', envio=envio, pendentes=pendentes)
@bp.route('/geral/envios/<int:envio_id>/status.json')
@login_required
def geral_envio_status(envio_id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return jsonify({'erro': 'forbidden'}), 403
    envio = _get_envio_do_usuario(envio_id)
    return jsonify({
        'status': envio.status,
        'status_msg': envio.status_msg,
        'total': envio.total,
        'enviados': envio.enviados,
        'falhas': envio.falhas,
        'pendentes': envio.total - envio.enviados - envio.falhas,
    })
@bp.route('/geral/envios/<int:envio_id>/pausar', methods=['POST'])
@login_required
def geral_envio_pausar(envio_id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    envio = _get_envio_do_usuario(envio_id)
    if envio.status == 'enviando':
        envio.status = 'pausado'
        envio.status_msg = 'Pausado pelo usuário'
        db.session.commit()
        flash('Envio pausado.', 'info')
    return redirect(url_for('geral.geral_envio_progresso', envio_id=envio.id))
@bp.route('/geral/envios/<int:envio_id>/continuar', methods=['POST'])
@login_required
def geral_envio_continuar(envio_id):
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    envio = _get_envio_do_usuario(envio_id)
    if envio.status in ('pausado', 'erro'):
        envio.status = 'pendente'
        envio.status_msg = None
        db.session.commit()
        try:
            from celery_app import celery
            res = celery.send_task('tasks.processar_envio_pesquisa', args=[envio.id])
            envio.celery_task_id = res.id
            db.session.commit()
            flash('Envio retomado.', 'success')
        except Exception as e:
            envio.status = 'erro'
            envio.status_msg = f'Falha ao retomar: {e}'
            db.session.commit()
            flash(f'Falha ao retomar: {e}', 'danger')
    return redirect(url_for('geral.geral_envio_progresso', envio_id=envio.id))
@bp.route('/geral/envios/<int:envio_id>/reenviar_falhas', methods=['POST'])
@login_required
def geral_envio_reenviar_falhas(envio_id):
    """Cria um novo lote contendo apenas os números que falharam neste envio."""
    config, redir = _exigir_usuario_geral()
    if redir:
        return redir
    envio = _get_envio_do_usuario(envio_id)

    falhas = [t for t in envio.telefones if t.status == 'falhou']
    if not falhas:
        flash('Não há falhas neste envio para reenviar.', 'info')
        return redirect(url_for('geral.geral_envio_progresso', envio_id=envio.id))

    novo = EnvioPesquisa(
        pesquisa_id=envio.pesquisa_id,
        usuario_id=current_user.id,
        nome=(envio.nome or f'Lote #{envio.id}') + ' (reenvio)',
        mensagem_template=envio.mensagem_template,
        intervalo_segundos=envio.intervalo_segundos,
        hora_inicio=envio.hora_inicio,
        hora_fim=envio.hora_fim,
        meta_diaria=envio.meta_diaria,
        total=len(falhas),
    )
    db.session.add(novo)
    db.session.flush()

    for t in falhas:
        db.session.add(EnvioPesquisaTelefone(
            envio_id=novo.id,
            numero=t.numero,
            nome=t.nome,
        ))
    db.session.commit()

    try:
        from celery_app import celery
        res = celery.send_task('tasks.processar_envio_pesquisa', args=[novo.id])
        novo.celery_task_id = res.id
        db.session.commit()
    except Exception as e:
        novo.status = 'erro'
        novo.status_msg = f'Falha ao agendar task: {e}'
        db.session.commit()
        flash(f'Reenvio criado, mas o disparo falhou: {e}', 'danger')
        return redirect(url_for('geral.geral_envio_progresso', envio_id=novo.id))

    flash(f'Reenvio iniciado: {len(falhas)} destinatários que haviam falhado.', 'success')
    return redirect(url_for('geral.geral_envio_progresso', envio_id=novo.id))
