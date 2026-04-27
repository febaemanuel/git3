"""Message formatting helpers (consultas + fila) and the send-and-log
shortcut used by the consulta flow."""

from datetime import datetime

from app.extensions import db
from app.models.consulta import LogMsgConsulta
from app.services.timezone import obter_hora_fortaleza


def formatar_data_consulta(data_str):
    """
    Formata a data da consulta para exibição na mensagem.
    Remove timestamps como "00:00:00" e formata no padrão DD/MM/YYYY.

    Exemplos de entrada:
    - "2024-05-20 00:00:00" -> "20/05/2024"
    - "5/20/2024" -> "20/05/2024"
    - "20/05/2024" -> "20/05/2024"
    """
    if not data_str or not str(data_str).strip():
        return "-"

    data_str = str(data_str).strip()

    # Remover timestamp se existir (ex: "2024-05-20 00:00:00")
    if ' ' in data_str:
        data_str = data_str.split(' ')[0]

    try:
        # Tentar diferentes formatos de entrada
        formatos = [
            '%Y-%m-%d',      # 2024-05-20
            '%d/%m/%Y',      # 20/05/2024
            '%m/%d/%Y',      # 5/20/2024
            '%d-%m-%Y',      # 20-05-2024
        ]

        for fmt in formatos:
            try:
                data_obj = datetime.strptime(data_str, fmt)
                # Retorna no formato brasileiro DD/MM/YYYY
                return data_obj.strftime('%d/%m/%Y')
            except ValueError:
                continue

        # Se nenhum formato funcionou, retorna o original
        return data_str

    except Exception:
        return data_str


def enviar_e_registrar_consulta(ws, telefone, mensagem, consulta):
    """
    Envia mensagem via WhatsApp e registra no log automaticamente.
    Isso garante que todas as mensagens enviadas apareçam no chat.
    """
    ok, result = ws.enviar(telefone, mensagem)

    # Registrar no log independente do resultado
    log = LogMsgConsulta(
        campanha_id=consulta.campanha_id,
        consulta_id=consulta.id,
        direcao='enviada',
        telefone=telefone,
        mensagem=mensagem[:500],
        status='sucesso' if ok else 'erro',
        msg_id=result if ok else None,
        erro=str(result)[:200] if not ok else None
    )
    db.session.add(log)
    db.session.commit()

    return ok, result


def obter_saudacao_dinamica():
    """
    Retorna saudação apropriada baseada na hora atual (fuso de Fortaleza/Brasil UTC-3).
    - Bom dia! (6h - 11h59)
    - Boa tarde! (12h - 17h59)
    - Boa noite! (18h - 5h59)
    """
    hora_atual = obter_hora_fortaleza()

    if 6 <= hora_atual < 12:
        return "Bom dia!"
    elif 12 <= hora_atual < 18:
        return "Boa tarde!"
    else:
        return "Boa noite!"


def formatar_mensagem_consulta_inicial(consulta):
    """
    MSG 1: Mensagem inicial de confirmação de consulta (enviada automaticamente)
    Enviada para: TODOS (RETORNO, INTERCONSULTA e REMARCACAO)
    Status: AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO
    """
    saudacao = obter_saudacao_dinamica()

    # TIPO REMARCACAO: Mensagem específica para consultas remarcadas
    if consulta.tipo == 'REMARCACAO':
        return f"""{saudacao}

📅 *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*

Informamos que sua consulta de *{consulta.especialidade}* com *{consulta.medico_solicitante}* foi *REMARCADA*.

📌 *Motivo:* {consulta.motivo_remarcacao or 'Motivo administrativo'}

❌ Data anterior: *{consulta.data_anterior or 'Não informada'}*
✅ *Nova data:* *{formatar_data_consulta(consulta.data_aghu)}*

Pode confirmar sua presença na nova data?

1️⃣ *SIM* - Confirmo presença
2️⃣ *NÃO* - Não posso comparecer
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""

    # TIPO INTERCONSULTA: Mensagem baseada em PACIENTE_VOLTAR_POSTO_SMS
    if consulta.tipo == 'INTERCONSULTA':
        voltar_posto = (consulta.paciente_voltar_posto_sms or '').upper()

        if voltar_posto in ['S', 'SIM']:
            # NÃO APROVADA - Precisa procurar UBS
            return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.

Solicitação de interconsulta do paciente *{consulta.paciente}* para a especialidade de *{consulta.especialidade}* foi avaliada e *não aprovada* para marcação no HUWC.

Procure sua UBS para solicitar encaminhamento para outra instituição de saúde."""

        elif voltar_posto in ['N', 'NAO', 'NÃO']:
            # APROVADA - Aguardar contato
            return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.

Solicitação de interconsulta do paciente *{consulta.paciente}* para a especialidade de *{consulta.especialidade}* foi avaliada e *aprovada* para marcação no HUWC.

Em breve entraremos em contato informando a data da consulta."""

        # Fallback se não tiver o campo preenchido
        return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.

Sua solicitação de interconsulta do paciente *{consulta.paciente}* para *{consulta.especialidade}* está em análise."""

    # TIPOS RETORNO e INTERCONSULTA: Verifica se é EXAME ou CONSULTA
    # Mensagem de EXAME só para OFTALMOLOGIA
    eh_oftalmologia = consulta.especialidade and 'OFTALMOLOGIA' in consulta.especialidade.upper()

    if consulta.exames and eh_oftalmologia:
        # Mensagem para EXAME
        return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.
Estamos informando que o *EXAME* do paciente *{consulta.paciente}*, foi *MARCADO* para o dia *{formatar_data_consulta(consulta.data_aghu)}*, exame *{consulta.exames}*, com especialidade em *{consulta.especialidade}*.

Caso não haja confirmação em até *2 dias*, seu exame será cancelado!

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""
    else:
        # Mensagem para CONSULTA
        return f"""{saudacao}

Falamos do *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*.
Estamos informando que a *CONSULTA* do paciente *{consulta.paciente}*, foi *MARCADA* para o dia *{formatar_data_consulta(consulta.data_aghu)}*, com *{consulta.medico_solicitante}*, com especialidade em *{consulta.especialidade}*.

Caso não haja confirmação em até *2 dias*, sua consulta será cancelada!

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_consulta_retry1(consulta):
    """
    MSG 1 RETRY: Primeira tentativa de recontato (16h após envio inicial)
    """
    saudacao = obter_saudacao_dinamica()

    # INTERCONSULTA: NÃO ENVIA RETRY (apenas MSG 1)
    if consulta.tipo == 'INTERCONSULTA':
        return None

    # Mensagem padrão para RETORNO e REMARCACAO
    return f"""{saudacao}

📋 *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*

Ainda não recebemos sua confirmação para a consulta de *{consulta.paciente}*.

*Dados da consulta:*
📅 Data: *{formatar_data_consulta(consulta.data_aghu)}*
👨‍⚕️ Médico: *{consulta.medico_solicitante}*
🏥 Especialidade: *{consulta.especialidade}*

⚠️ *IMPORTANTE:* Caso não haja confirmação em até *2 dias*, sua consulta será cancelada!

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_consulta_retry2(consulta):
    """
    MSG 1 RETRY FINAL: Segunda e última tentativa de recontato (32h após envio inicial)
    """
    saudacao = obter_saudacao_dinamica()

    # INTERCONSULTA: NÃO ENVIA RETRY (apenas MSG 1)
    if consulta.tipo == 'INTERCONSULTA':
        return None

    # Mensagem padrão para RETORNO e REMARCACAO
    return f"""{saudacao}

🚨 *HOSPITAL UNIVERSITÁRIO WALTER CANTÍDIO*
⚠️ *ÚLTIMA TENTATIVA DE CONTATO*

Esta é nossa *ÚLTIMA TENTATIVA* antes do cancelamento automático da consulta de *{consulta.paciente}*.

*Dados da consulta:*
📅 Data: *{formatar_data_consulta(consulta.data_aghu)}*
👨‍⚕️ Médico: *{consulta.medico_solicitante}*
🏥 Especialidade: *{consulta.especialidade}*

❌ *Se não recebermos sua resposta, a consulta será CANCELADA automaticamente.*

Posso confirmar o agendamento?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não consigo ir / Não quero mais
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""



def formatar_mensagem_comprovante(consulta=None, dados_ocr=None, link_comprovante=None):
    """
    MSG 2: Mensagem de comprovante (enviada manualmente com arquivo anexo)
    Enviada para: Consultas com status AGUARDANDO_COMPROVANTE
    Status: AGUARDANDO_COMPROVANTE → CONFIRMADO

    Args:
        consulta: Objeto AgendamentoConsulta (opcional, para fallback)
        dados_ocr: Dict com dados extraídos do comprovante via OCR (opcional)
                   Keys: paciente, data, hora, medico, especialidade
        link_comprovante: URL do link público para baixar o comprovante (opcional)
    """
    # OCR para tudo, EXCETO especialidade que vem da planilha
    paciente = None
    data = None
    hora = None
    medico = None
    especialidade = None

    # Dados do OCR (paciente, data, hora, médico)
    if dados_ocr:
        paciente = dados_ocr.get('paciente')
        data = dados_ocr.get('data')
        hora = dados_ocr.get('hora')
        medico = dados_ocr.get('medico')

    # ESPECIALIDADE vem da planilha (consulta), não do OCR
    if consulta:
        especialidade = consulta.especialidade

    # Fallback para dados da consulta se OCR não extraiu
    if consulta:
        if not paciente:
            paciente = consulta.paciente
        if not data:
            data = consulta.data_aghu
        if not medico:
            medico = consulta.medico_solicitante or consulta.grade_aghu

    # Formata dados para exibição
    paciente_str = paciente if paciente else 'Paciente'
    data_str = data if data else '-'
    hora_str = hora if hora else '-'
    medico_str = medico if medico else '-'
    especialidade_str = especialidade if especialidade else '-'

    # Verifica se é EXAME (coluna EXAMES preenchida E especialidade OFTALMOLOGIA)
    exames = None
    if consulta and consulta.exames:
        exames = consulta.exames

    # Bloco do link (só adiciona se link_comprovante foi fornecido)
    link_bloco = ""
    if link_comprovante:
        link_bloco = f"""

🔗 *LINK DO COMPROVANTE*
Caso não consiga abrir o comprovante em PDF, baixe pelo link:
{link_comprovante}
_Este link ficará disponível por 7 dias._"""

    # Mensagem de EXAME só para OFTALMOLOGIA
    eh_oftalmologia = especialidade_str and 'OFTALMOLOGIA' in especialidade_str.upper()

    if exames and eh_oftalmologia:
        # Mensagem para EXAME
        return f"""O Hospital Walter Cantídio agradece seu contato. *EXAME CONFIRMADO!*

*Paciente:* *{paciente_str}*
*Data:* *{data_str}*
*Horário:* *{hora_str}*
*Exame:* *{exames}*
*Especialidade:* *{especialidade_str}*
{link_bloco}

O hospital entra em contato através do: (85) 992081534 / (85)996700783 / (85)991565903 / (85) 992614237 / (85) 992726080. É importante que atenda as ligações e responda as mensagens desses números. Por tanto, salve-os!

Confira seu comprovante: data, horário e exame.

Caso falte, procurar o ambulatório para ser colocado novamente no pré-agendamento.

Você sabia que pode verificar sua consulta no app HU Digital? https://play.google.com/store/apps/details?id=br.gov.ebserh.hudigital&pcampaignid=web_share . Após 5 horas dessa mensagem, verifique sua consulta agendada no app.

Reagendamentos estarão presentes no app HU Digital. Verifique sempre o app HU Digital.

📊 *Pesquisa de Satisfação* (opcional): Sua opinião é muito importante! Responda nosso formulário: https://docs.google.com/forms/d/1TEpVEaJYTxG7Jz5o-tU1FJ988XRT0A8GJ7y3X40S18Q/viewform"""
    else:
        # Mensagem para CONSULTA
        return f"""O Hospital Walter Cantídio agradece seu contato. *CONSULTA CONFIRMADA!*

*Paciente:* *{paciente_str}*
*Data:* *{data_str}*
*Horário:* *{hora_str}*
*Médico(a):* *{medico_str}*
*Especialidade:* *{especialidade_str}*
{link_bloco}

O hospital entra em contato através do: (85) 992081534 / (85)996700783 / (85)991565903 / (85) 992614237 / (85) 992726080. É importante que atenda as ligações e responda as mensagens desses números. Por tanto, salve-os!

Confira seu comprovante: data, horário e nome do(a) médico(a).

Não fazemos marcação de exames, apenas consultas.

Caso falte, procurar o ambulatório para ser colocado novamente no pré-agendamento.

Você sabia que pode verificar sua consulta no app HU Digital? https://play.google.com/store/apps/details?id=br.gov.ebserh.hudigital&pcampaignid=web_share . Após 5 horas dessa mensagem, verifique sua consulta agendada no app.

Reagendamentos estarão presentes no app HU Digital. Verifique sempre o app HU Digital.

📊 *Pesquisa de Satisfação* (opcional): Sua opinião é muito importante! Responda nosso formulário: https://docs.google.com/forms/d/1TEpVEaJYTxG7Jz5o-tU1FJ988XRT0A8GJ7y3X40S18Q/viewform"""


def formatar_mensagem_perguntar_motivo():
    """
    MSG 3A: Pergunta motivo da rejeição (enviada automaticamente)
    Enviada para: TODOS que respondem NÃO na MSG 1
    Status: AGUARDANDO_CONFIRMACAO → AGUARDANDO_MOTIVO_REJEICAO
    """
    return """Entendemos sua decisão.

Poderia nos informar o *motivo* da recusa? Isso nos ajuda a melhorar nosso atendimento.

(Pode responder livremente com o motivo)"""


def formatar_mensagem_voltar_posto(consulta):
    """
    MSG 3B: Orientação para voltar ao posto (enviada automaticamente)
    Enviada para: INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = SIM
    Status: AGUARDANDO_MOTIVO_REJEICAO → REJEITADO
    """
    return f"""HOSPITAL WALTER CANTIDIO
Boa tarde! Falo com {consulta.paciente}? Sua consulta para o serviço de {consulta.especialidade} foi avaliada e por não se encaixar nos critérios do hospital, não foi possível seguir com o agendamento, portanto será necessário procurar um posto de saúde para realizar seu atendimento. Agradecemos a compreensão, tenha uma boa tarde!"""


def formatar_mensagem_interconsulta_aprovada(consulta):
    """
    MSG INTERCONSULTA APROVADA: Mensagem de aprovação para interconsulta (sem necessidade de ir ao posto)
    Enviada para: INTERCONSULTA com PACIENTE_VOLTAR_POSTO_SMS = NÃO (quando paciente responde SIM)
    Status: AGUARDANDO_CONFIRMACAO → CONFIRMADO
    """
    return f"""✅ *HOSPITAL WALTER CANTÍDIO*

Olá, {consulta.paciente}!

Solicitação de interconsulta avaliada e aprovada para marcação no HUWC, em breve entraremos em contato informando a data da consulta.

Especialidade: *{consulta.especialidade}*

_Hospital Universitário Walter Cantídio_"""


def formatar_mensagem_confirmacao_rejeicao(consulta):
    """
    MSG CONFIRMAÇÃO REJEIÇÃO: Mensagem de confirmação após paciente informar motivo
    Enviada para: Consultas que foram rejeitadas pelo paciente (após informar motivo)
    Status: AGUARDANDO_MOTIVO_REJEICAO → REJEITADO
    """
    return f"""✅ *HOSPITAL WALTER CANTÍDIO*

Entendido, {consulta.paciente}.

Sua consulta de *{consulta.especialidade}* foi cancelada conforme solicitado.

Caso precise reagendar, entre em contato com o seu ambulatório para ser inserida novamente e aguardar nova data.

Obrigado!

_Hospital Universitário Walter Cantídio_"""


def formatar_mensagem_cancelamento_sem_resposta(consulta):
    """
    MSG CANCELAMENTO: Mensagem de cancelamento por falta de resposta
    Enviada para: Consultas que não responderam após 24h e 2 tentativas adicionais
    Status: AGUARDANDO_CONFIRMACAO → CANCELADO
    """
    return f"""❌ *HOSPITAL WALTER CANTÍDIO*

Olá, {consulta.paciente}.

Não recebemos sua confirmação para a consulta de *{consulta.especialidade}* marcada para *{formatar_data_consulta(consulta.data_aghu)}*.

Sua consulta foi *CANCELADA* por falta de resposta.

Caso ainda tenha interesse, procure o posto de saúde para reagendar.

_Hospital Universitário Walter Cantídio_"""


def formatar_mensagem_fila_retry1(contato):
    """
    MSG RETRY 1 (FILA): Primeira tentativa de recontato (24h após envio inicial)
    """
    saudacao = obter_saudacao_dinamica()
    procedimento = contato.procedimento_normalizado or contato.procedimento or 'o procedimento'

    return f"""{saudacao}

📋 Ainda não recebemos sua confirmação para o procedimento de *{contato.nome}*.

*Procedimento:* {procedimento}

⚠️ *IMPORTANTE:* Caso não haja confirmação em até *2 dias*, sua vaga será disponibilizada para outra pessoa!

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_fila_retry2(contato):
    """
    MSG RETRY 2 (FILA): Segunda e última tentativa de recontato (48h após retry 1)
    """
    saudacao = obter_saudacao_dinamica()
    procedimento = contato.procedimento_normalizado or contato.procedimento or 'o procedimento'

    return f"""{saudacao}

🚨 *ÚLTIMA TENTATIVA DE CONTATO*

Esta é nossa *ÚLTIMA TENTATIVA* antes de disponibilizarmos sua vaga para o procedimento de *{contato.nome}*.

*Procedimento:* {procedimento}

❌ *Se não recebermos sua resposta, sua vaga será disponibilizada automaticamente.*

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa"""


def formatar_mensagem_fila_sem_resposta(contato):
    """
    MSG SEM RESPOSTA (FILA): Encerramento por falta de resposta após 3 tentativas
    """
    procedimento = contato.procedimento_normalizado or contato.procedimento or 'o procedimento'

    return f"""❌ *Olá, {contato.nome}.*

Não recebemos sua confirmação para o procedimento de *{procedimento}*.

Sua vaga foi *disponibilizada* por falta de resposta.

Caso ainda tenha interesse, entre em contato conosco pelo telefone (85) 3366-8000."""

RESPOSTAS_SIM = [
    'SIM', 'S', '1',
    'CONFIRMO', 'CONFIRMADO',
    'TENHO INTERESSE', 'ACEITO', 'OK',
    '1 SIM', '1SIM', 'SIM 1', 'SIM1'
]

RESPOSTAS_NAO = [
    'NAO', 'NÃO', 'N', '2',
    'NAO QUERO', 'NÃO QUERO',
    'NAO TENHO INTERESSE', 'NÃO TENHO INTERESSE',
    '2 NAO', '2NAO', 'NAO 2', 'NAO2',
    '2 NÃO', '2NÃO', 'NÃO 2', 'NÃO2'
]

RESPOSTAS_DESCONHECO = [
    '3', 'DESCONHECO', 'DESCONHEÇO',
    'NAO SOU', 'NÃO SOU',
    'ENGANO', 'NUMERO ERRADO', 'NÚMERO ERRADO',
    '3 DESCONHECO', '3DESCONHECO', '3 DESCONHEÇO', '3DESCONHEÇO'
]

MENSAGEM_PADRAO = """📋 *Olá, {nome}*!

Aqui é da *Central de Agendamentos do Hospital Universitário Walter Cantídio*.

Consta em nossos registros que você está na lista de espera para o procedimento: *{procedimento}*.

Você ainda tem interesse em realizar esta cirurgia?

1️⃣ *SIM* - Tenho interesse
2️⃣ *NÃO* - Não tenho mais interesse
3️⃣ *DESCONHEÇO* - Não sou essa pessoa

_Por favor, responda com o número da opção._
"""


def verificar_resposta_em_lista(texto_up, lista_respostas):
    """
    Verifica se o texto É EXATAMENTE uma resposta válida.
    MUDANÇA CRÍTICA: Agora aceita SOMENTE respostas exatas (mensagem completa).
    Exemplos:
    - "SIM" → ✅ aceito
    - "1" → ✅ aceito  
    - "TENHO INTERESSE" → ✅ aceito
    - "Boa tarde! Não sei quando posso ir" → ❌ rejeitado (não é resposta exata)
    - "Sim, quero" → ❌ rejeitado (não é resposta exata)
    """
    # Remove espaços extras e normaliza
    texto_normalizado = ' '.join(texto_up.split())
    
    # Verifica se a mensagem COMPLETA é exatamente uma das respostas válidas
    return texto_normalizado in lista_respostas


def _renderizar_mensagem_envio(mensagem_template, link_publico, nome_destinatario=None):
    """Substitui placeholders na mensagem; se {LINK} ausente, anexa no fim."""
    texto = mensagem_template or ''
    if '{NOME}' in texto:
        texto = texto.replace('{NOME}', nome_destinatario or '')
    if '{LINK}' in texto:
        texto = texto.replace('{LINK}', link_publico)
    else:
        texto = (texto.rstrip() + '\n\n' + link_publico).strip()
    return texto

