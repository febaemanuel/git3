"""Public survey endpoint at /p/<token>."""

import json
from datetime import datetime

from flask import (
    Blueprint, abort, flash, jsonify, redirect, render_template, request,
    url_for,
)

from app.extensions import csrf, db
from app.models import (
    PerguntaPesquisa, Pesquisa, RespostaItem, RespostaPesquisa,
)


bp = Blueprint('pesquisa_publica', __name__)


@bp.route('/p/<token>', methods=['GET', 'POST'])
@csrf.exempt  # link é compartilhado externamente; usa token na URL como autorização
def responder(token):
    pesquisa = Pesquisa.query.filter_by(token_publico=token).first_or_404()

    if not pesquisa.ativa:
        return render_template('pesquisa_publica_indisponivel.html', pesquisa=pesquisa), 410

    if not pesquisa.perguntas:
        return render_template('pesquisa_publica_indisponivel.html', pesquisa=pesquisa,
                               motivo='Esta pesquisa ainda não possui perguntas configuradas.'), 410

    if request.method == 'POST':
        resposta = RespostaPesquisa(
            pesquisa_id=pesquisa.id,
            ip_origem=request.headers.get('X-Forwarded-For', request.remote_addr or '')[:45],
            user_agent=(request.headers.get('User-Agent') or '')[:255],
        )
        db.session.add(resposta)
        db.session.flush()  # garante resposta.id pra usar nos itens

        faltando_obrigatoria = False

        for p in pesquisa.perguntas:
            campo = f'p_{p.id}'

            if p.tipo == 'MULTI_ESCOLHA':
                valores = [v for v in request.form.getlist(campo) if v in p.opcoes_lista()]
                if p.obrigatoria and not valores:
                    faltando_obrigatoria = True
                    break
                item = RespostaItem(resposta_id=resposta.id, pergunta_id=p.id)
                if valores:
                    import json
                    item.valor = json.dumps(valores)
                db.session.add(item)
            else:
                valor = (request.form.get(campo) or '').strip()
                if p.tipo == 'ESCALA_1_10' and valor:
                    try:
                        n = int(valor)
                        if not (1 <= n <= 10):
                            valor = ''
                    except ValueError:
                        valor = ''
                if p.obrigatoria and not valor:
                    faltando_obrigatoria = True
                    break
                item = RespostaItem(resposta_id=resposta.id, pergunta_id=p.id, valor=valor or None)
                db.session.add(item)

        if faltando_obrigatoria:
            db.session.rollback()
            flash('Por favor, responda todas as perguntas obrigatórias.', 'danger')
            return render_template('pesquisa_publica.html', pesquisa=pesquisa,
                                   form_data=request.form)

        resposta.concluida_em = datetime.utcnow()
        db.session.commit()
        return render_template('pesquisa_publica_obrigado.html', pesquisa=pesquisa)

    return render_template('pesquisa_publica.html', pesquisa=pesquisa, form_data={})
