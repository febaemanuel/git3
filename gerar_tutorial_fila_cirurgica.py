#!/usr/bin/env python3
"""
Gera o PDF do tutorial do Modo Fila Cirúrgica para usuários leigos.
Uso: python3 gerar_tutorial_fila_cirurgica.py
Saída: tutorial_fila_cirurgica.pdf
"""

from fpdf import FPDF

class TutorialPDF(FPDF):
    def header(self):
        self.set_font('Helvetica', 'B', 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, 'Tutorial - Fila Cirurgica | HUWC', 0, 1, 'C')
        self.set_draw_color(0, 123, 255)
        self.set_line_width(0.5)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font('Helvetica', 'I', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f'Pagina {self.page_no()}/{{nb}}', 0, 0, 'C')

    def titulo_secao(self, numero, texto):
        self.ln(6)
        self.set_fill_color(0, 123, 255)
        self.set_text_color(255, 255, 255)
        self.set_font('Helvetica', 'B', 14)
        self.cell(0, 10, f'  {numero}. {texto}', 0, 1, 'L', fill=True)
        self.ln(3)
        self.set_text_color(0, 0, 0)

    def subtitulo(self, texto):
        self.ln(3)
        self.set_font('Helvetica', 'B', 11)
        self.set_text_color(0, 90, 180)
        self.cell(0, 7, texto, 0, 1)
        self.set_text_color(0, 0, 0)
        self.ln(1)

    def paragrafo(self, texto):
        self.set_font('Helvetica', '', 10)
        self.multi_cell(0, 5.5, texto)
        self.ln(2)

    def item_lista(self, texto, bullet='  >'):
        self.set_font('Helvetica', '', 10)
        x = self.get_x()
        self.cell(10, 5.5, bullet, 0, 0)
        self.multi_cell(0, 5.5, texto)
        self.ln(1)

    def destaque(self, texto):
        self.set_fill_color(255, 243, 205)
        self.set_font('Helvetica', 'B', 10)
        self.multi_cell(0, 6, f'  IMPORTANTE: {texto}', 0, 'L', fill=True)
        self.ln(3)

    def dica(self, texto):
        self.set_fill_color(209, 236, 241)
        self.set_font('Helvetica', '', 10)
        self.multi_cell(0, 6, f'  DICA: {texto}', 0, 'L', fill=True)
        self.ln(3)

    def celula_tabela(self, w, h, txt, border=1, ln=0, align='L', fill=False, bold=False):
        if bold:
            self.set_font('Helvetica', 'B', 9)
        else:
            self.set_font('Helvetica', '', 9)
        self.cell(w, h, txt, border, ln, align, fill)


def gerar_tutorial():
    pdf = TutorialPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # =========================================================================
    # CAPA
    # =========================================================================
    pdf.add_page()
    pdf.ln(30)
    pdf.set_font('Helvetica', 'B', 28)
    pdf.set_text_color(0, 90, 180)
    pdf.cell(0, 15, 'TUTORIAL', 0, 1, 'C')
    pdf.set_font('Helvetica', 'B', 22)
    pdf.cell(0, 12, 'Modo Fila Cirurgica', 0, 1, 'C')
    pdf.ln(8)
    pdf.set_draw_color(0, 123, 255)
    pdf.set_line_width(1)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)

    pdf.set_font('Helvetica', '', 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, 'Sistema de Busca Ativa de Pacientes', 0, 1, 'C')
    pdf.cell(0, 8, 'Hospital Universitario Walter Cantidio', 0, 1, 'C')
    pdf.ln(15)

    pdf.set_font('Helvetica', '', 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, 'Guia completo para criar campanhas,', 0, 1, 'C')
    pdf.cell(0, 7, 'importar planilhas e gerenciar a fila cirurgica', 0, 1, 'C')
    pdf.cell(0, 7, 'via WhatsApp de forma automatizada.', 0, 1, 'C')

    pdf.ln(30)
    pdf.set_fill_color(240, 240, 240)
    pdf.set_font('Helvetica', 'I', 10)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 6, '  Este tutorial foi feito para usuarios sem experiencia tecnica.\n  Siga cada passo na ordem indicada.', 0, 'C', fill=True)

    # =========================================================================
    # PAGINA 2 - O QUE E O SISTEMA
    # =========================================================================
    pdf.add_page()
    pdf.set_text_color(0, 0, 0)

    pdf.titulo_secao('1', 'O que e o Sistema de Fila Cirurgica?')

    pdf.paragrafo(
        'O Sistema de Fila Cirurgica e uma ferramenta que entra em contato com pacientes '
        'que estao na lista de espera para cirurgias no Hospital Universitario Walter Cantidio. '
        'O contato e feito de forma automatica pelo WhatsApp.'
    )

    pdf.paragrafo('O sistema faz o seguinte:')
    pdf.item_lista('Envia mensagem automatica pelo WhatsApp para cada paciente da lista')
    pdf.item_lista('Pergunta se o paciente ainda tem interesse na cirurgia')
    pdf.item_lista('Registra a resposta automaticamente (SIM, NAO ou DESCONHECO)')
    pdf.item_lista('Se o paciente nao responder, reenvia lembretes automaticamente')
    pdf.item_lista('Gera relatorios com o resultado de cada paciente')
    pdf.item_lista('Responde duvidas comuns dos pacientes automaticamente (FAQ)')

    pdf.ln(3)
    pdf.destaque(
        'Voce NAO precisa enviar mensagens manualmente. O sistema faz tudo sozinho '
        'apos a campanha ser criada e iniciada.'
    )

    # =========================================================================
    # PAGINA 3 - PREPARAR A PLANILHA
    # =========================================================================
    pdf.titulo_secao('2', 'Como Preparar a Planilha Excel')

    pdf.paragrafo(
        'A planilha e o arquivo Excel (.xlsx) com os dados dos pacientes. '
        'E a parte mais importante: se a planilha estiver errada, o sistema nao vai funcionar.'
    )

    pdf.subtitulo('Colunas da Planilha')
    pdf.paragrafo(
        'A planilha deve ter as seguintes colunas (a primeira linha deve conter os nomes das colunas):'
    )

    # Tabela de colunas
    col_w = [35, 25, 50, 80]
    row_h = 7

    pdf.set_fill_color(52, 58, 64)
    pdf.set_text_color(255, 255, 255)
    pdf.celula_tabela(col_w[0], row_h, ' Coluna', fill=True, bold=True)
    pdf.celula_tabela(col_w[1], row_h, ' Obrigatorio?', fill=True, bold=True)
    pdf.celula_tabela(col_w[2], row_h, ' Formato', fill=True, bold=True)
    pdf.celula_tabela(col_w[3], row_h, ' Exemplo', fill=True, bold=True, ln=1)
    pdf.set_text_color(0, 0, 0)

    linhas = [
        ['Nome', 'SIM', 'Texto (nome completo)', 'Joao da Silva'],
        ['Telefone', 'SIM', 'Numero com DDD', '85992231683'],
        ['Procedimento', 'Opcional', 'Texto da cirurgia', 'Cirurgia de Catarata'],
        ['Nascimento', 'Opcional', 'DD/MM/AAAA', '15/08/1985'],
    ]
    for i, linha in enumerate(linhas):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.celula_tabela(col_w[0], row_h, f' {linha[0]}', fill=fill, bold=True)
        pdf.celula_tabela(col_w[1], row_h, f' {linha[1]}', fill=fill)
        pdf.celula_tabela(col_w[2], row_h, f' {linha[2]}', fill=fill)
        pdf.celula_tabela(col_w[3], row_h, f' {linha[3]}', fill=fill, ln=1)

    pdf.ln(5)

    pdf.subtitulo('Nomes aceitos para cada coluna')
    pdf.paragrafo('O sistema aceita variantes dos nomes. Veja o que funciona:')
    pdf.item_lista('Coluna Nome: "nome", "usuario", "paciente"')
    pdf.item_lista('Coluna Telefone: "telefone", "celular", "fone", "tel", "whatsapp", "contato"')
    pdf.item_lista('Coluna Procedimento: "procedimento", "cirurgia", "procedimentos"')
    pdf.item_lista('Coluna Nascimento: "nascimento", "data_nascimento", "data nascimento", "dt_nasc"')

    pdf.ln(2)
    pdf.subtitulo('Exemplo de Planilha Correta')

    col_ex = [45, 35, 55, 55]
    pdf.set_fill_color(52, 58, 64)
    pdf.set_text_color(255, 255, 255)
    pdf.celula_tabela(col_ex[0], row_h, ' Nome', fill=True, bold=True)
    pdf.celula_tabela(col_ex[1], row_h, ' Telefone', fill=True, bold=True)
    pdf.celula_tabela(col_ex[2], row_h, ' Procedimento', fill=True, bold=True)
    pdf.celula_tabela(col_ex[3], row_h, ' Nascimento', fill=True, bold=True, ln=1)
    pdf.set_text_color(0, 0, 0)

    exemplos = [
        ['Maria da Silva', '85999001122', 'Cirurgia de Catarata', '10/03/1960'],
        ['Jose Santos', '85988112233', 'Hernia Inguinal', '22/07/1975'],
        ['Ana Oliveira', '85977334455', 'Artroscopia de Joelho', '05/11/1988'],
        ['Jose Santos', '85966778899', 'Hernia Inguinal', '22/07/1975'],
    ]
    for i, ex in enumerate(exemplos):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.celula_tabela(col_ex[0], row_h, f' {ex[0]}', fill=fill)
        pdf.celula_tabela(col_ex[1], row_h, f' {ex[1]}', fill=fill)
        pdf.celula_tabela(col_ex[2], row_h, f' {ex[2]}', fill=fill)
        pdf.celula_tabela(col_ex[3], row_h, f' {ex[3]}', fill=fill, ln=1)

    pdf.ln(4)
    pdf.dica(
        'Note que "Jose Santos" aparece 2 vezes com telefones diferentes. '
        'O sistema agrupa automaticamente e cadastra os 2 numeros para o mesmo paciente!'
    )

    pdf.destaque(
        'Salve a planilha no formato .xlsx (Excel). Arquivos .csv ou .pdf NAO sao aceitos.'
    )

    # =========================================================================
    # REGRAS DA PLANILHA
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('3', 'Regras Importantes da Planilha')

    pdf.subtitulo('Telefones')
    pdf.item_lista('Use numeros com DDD, sem espacos ou tracos. Ex: 85999001122')
    pdf.item_lista('Pode ser com ou sem o 55 na frente. Ex: 5585999001122 tambem funciona')
    pdf.item_lista('Se o paciente tem mais de um telefone, coloque cada um em uma linha separada com o mesmo nome')
    pdf.item_lista('O sistema aceita ate 5 telefones por paciente')
    pdf.item_lista('Numeros invalidos sao ignorados automaticamente')

    pdf.subtitulo('Nomes')
    pdf.item_lista('Use o nome completo do paciente')
    pdf.item_lista('O sistema agrupa linhas com o MESMO NOME como sendo o mesmo paciente')
    pdf.item_lista('Se o nome estiver escrito diferente (ex: "Jose" vs "Jose Santos"), serao tratados como pessoas diferentes')

    pdf.subtitulo('Procedimento')
    pdf.item_lista('Se nao preencher, o sistema usa "o procedimento" na mensagem')
    pdf.item_lista('Se preencher, vai aparecer na mensagem: "voce esta na lista de espera para Cirurgia de Catarata"')
    pdf.item_lista('O sistema usa inteligencia artificial para padronizar os nomes dos procedimentos')

    pdf.subtitulo('Data de Nascimento')
    pdf.item_lista('Formato: DD/MM/AAAA (ex: 15/08/1985)')
    pdf.item_lista('Tambem aceita: DD-MM-AAAA ou DD.MM.AAAA')
    pdf.item_lista('Se informada, ajuda a identificar pacientes com o mesmo nome')

    # =========================================================================
    # CRIAR CAMPANHA
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('4', 'Como Criar uma Campanha')

    pdf.paragrafo(
        'Campanha e o nome dado a um lote de pacientes que serao contatados. '
        'Por exemplo: "Fila Cirurgica Oftalmologia Marco 2026".'
    )

    pdf.subtitulo('Passo a Passo')

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Passo 1: Acesse o painel', 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.paragrafo('Faca login no sistema com seu email e senha.')

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Passo 2: Clique em "Nova Campanha"', 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.paragrafo('No painel principal (Dashboard), clique no botao "Nova Campanha".')

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Passo 3: Preencha os dados', 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.item_lista('Nome da Campanha: de um nome descritivo (ex: "Oftalmologia Marco 2026")')
    pdf.item_lista('Descricao: opcional, para sua referencia')
    pdf.item_lista('Mensagem: ja vem preenchida com a mensagem padrao. Pode personalizar se quiser.')
    pdf.item_lista('Meta Diaria: quantas mensagens enviar por dia (recomendado: 50)')
    pdf.item_lista('Horario Inicio: hora para comecar os envios (ex: 08:00)')
    pdf.item_lista('Horario Fim: hora para parar os envios (ex: 18:00)')

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Passo 4: Anexe a planilha', 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.paragrafo(
        'Clique no botao de upload e selecione o arquivo Excel (.xlsx) que voce preparou.'
    )

    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, 'Passo 5: Aguarde o processamento', 0, 1)
    pdf.set_font('Helvetica', '', 10)
    pdf.paragrafo(
        'O sistema vai processar a planilha, validar os numeros e normalizar os procedimentos. '
        'Isso pode levar alguns minutos dependendo da quantidade de pacientes. '
        'Uma barra de progresso sera exibida.'
    )

    pdf.ln(3)
    pdf.dica(
        'O calculo do intervalo entre envios e automatico. Se voce definir meta de 50 '
        'mensagens entre 08:00 e 18:00 (10 horas), o sistema calcula: 1 envio a cada 12 minutos.'
    )

    # =========================================================================
    # INICIAR ENVIOS
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('5', 'Iniciar os Envios')

    pdf.subtitulo('Antes de iniciar, verifique:')
    pdf.item_lista('O WhatsApp esta conectado (indicador verde no topo da pagina)')
    pdf.item_lista('A campanha foi processada com sucesso (status "Pronta")')
    pdf.item_lista('Os horarios de envio estao corretos')

    pdf.subtitulo('Iniciando')
    pdf.paragrafo(
        'Na pagina da campanha, clique no botao "Iniciar Envios". '
        'O sistema comecara a enviar as mensagens automaticamente, '
        'respeitando o intervalo calculado e os horarios configurados.'
    )

    pdf.destaque(
        'NAO feche o navegador durante os envios. O sistema precisa estar ativo para enviar.'
    )

    pdf.subtitulo('O que o paciente recebe?')
    pdf.paragrafo('O paciente recebe uma mensagem no WhatsApp parecida com esta:')

    pdf.ln(2)
    pdf.set_fill_color(220, 248, 220)
    pdf.set_font('Helvetica', '', 9)
    msg_exemplo = (
        '  Ola, Maria da Silva!\n'
        '  \n'
        '  Aqui e da Central de Agendamentos do Hospital Universitario Walter Cantidio.\n'
        '  \n'
        '  Consta em nossos registros que voce esta na lista de espera para\n'
        '  o procedimento: Cirurgia de Catarata.\n'
        '  \n'
        '  Voce ainda tem interesse em realizar esta cirurgia?\n'
        '  \n'
        '  1 - SIM - Tenho interesse\n'
        '  2 - NAO - Nao tenho mais interesse\n'
        '  3 - DESCONHECO - Nao sou essa pessoa'
    )
    pdf.multi_cell(0, 5, msg_exemplo, 1, 'L', fill=True)
    pdf.ln(4)

    pdf.subtitulo('O que acontece com a resposta do paciente?')

    col_resp = [40, 150]
    pdf.set_fill_color(52, 58, 64)
    pdf.set_text_color(255, 255, 255)
    pdf.celula_tabela(col_resp[0], row_h, ' Resposta', fill=True, bold=True)
    pdf.celula_tabela(col_resp[1], row_h, ' O que acontece', fill=True, bold=True, ln=1)
    pdf.set_text_color(0, 0, 0)

    resps = [
        ['1 ou SIM', 'Paciente fica como CONFIRMADO. Recebe mensagem de confirmacao.'],
        ['2 ou NAO', 'Sistema pergunta o motivo. Paciente fica como REJEITADO.'],
        ['3 ou DESCON.', 'Numero e marcado como "nao pertence ao paciente".'],
        ['Sem resposta', 'Sistema reenvia lembretes automaticamente (ate 2 tentativas).'],
    ]
    for i, r in enumerate(resps):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.celula_tabela(col_resp[0], row_h, f' {r[0]}', fill=fill, bold=True)
        pdf.celula_tabela(col_resp[1], row_h, f' {r[1]}', fill=fill, ln=1)

    # =========================================================================
    # ACOMPANHAMENTO
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('6', 'Acompanhar os Resultados')

    pdf.paragrafo(
        'No Dashboard voce pode acompanhar em tempo real o progresso de cada campanha:'
    )

    pdf.item_lista('Total de contatos importados')
    pdf.item_lista('Quantos ja foram enviados')
    pdf.item_lista('Quantos confirmaram interesse (SIM)')
    pdf.item_lista('Quantos rejeitaram (NAO)')
    pdf.item_lista('Quantos ainda nao responderam')
    pdf.item_lista('Quantos tiveram erro no envio')

    pdf.subtitulo('Status dos Pacientes')

    col_st = [40, 150]
    row_h2 = 7
    pdf.set_fill_color(52, 58, 64)
    pdf.set_text_color(255, 255, 255)
    pdf.celula_tabela(col_st[0], row_h2, ' Status', fill=True, bold=True)
    pdf.celula_tabela(col_st[1], row_h2, ' Significado', fill=True, bold=True, ln=1)
    pdf.set_text_color(0, 0, 0)

    status_lista = [
        ['AGUARDANDO', 'Mensagem ainda nao foi enviada (na fila de envio)'],
        ['ENVIADO', 'Mensagem enviada, aguardando resposta do paciente'],
        ['CONFIRMADO', 'Paciente respondeu SIM - tem interesse na cirurgia'],
        ['REJEITADO', 'Paciente respondeu NAO ou todos os telefones nao reconhecem'],
        ['ERRO', 'Houve erro no envio (numero invalido, WhatsApp desconectado, etc.)'],
    ]
    for i, s in enumerate(status_lista):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.celula_tabela(col_st[0], row_h2, f' {s[0]}', fill=fill, bold=True)
        pdf.celula_tabela(col_st[1], row_h2, f' {s[1]}', fill=fill, ln=1)

    pdf.ln(5)

    pdf.subtitulo('Exportar Relatorio')
    pdf.paragrafo(
        'Voce pode exportar todos os dados para uma planilha Excel clicando em "Exportar". '
        'O arquivo gerado contem todas as informacoes: nome, telefone, procedimento, status, '
        'data de envio, resposta do paciente, etc.'
    )

    # =========================================================================
    # LEMBRETES AUTOMATICOS
    # =========================================================================
    pdf.titulo_secao('7', 'Lembretes Automaticos (Follow-up)')

    pdf.paragrafo(
        'Se o paciente NAO responder a primeira mensagem, o sistema envia lembretes '
        'automaticamente:'
    )

    pdf.ln(2)
    col_fu = [50, 140]
    pdf.set_fill_color(52, 58, 64)
    pdf.set_text_color(255, 255, 255)
    pdf.celula_tabela(col_fu[0], row_h2, ' Quando', fill=True, bold=True)
    pdf.celula_tabela(col_fu[1], row_h2, ' O que acontece', fill=True, bold=True, ln=1)
    pdf.set_text_color(0, 0, 0)

    followups = [
        ['Apos 24 horas', '1o lembrete: "Ainda nao recebemos sua confirmacao..."'],
        ['Apos 48 horas', '2o lembrete (ULTIMO): "ULTIMA TENTATIVA DE CONTATO..."'],
        ['Apos 72 horas', 'Encerramento: vaga disponibilizada por falta de resposta'],
    ]
    for i, f in enumerate(followups):
        fill = i % 2 == 0
        if fill:
            pdf.set_fill_color(240, 240, 240)
        pdf.celula_tabela(col_fu[0], row_h2, f' {f[0]}', fill=fill)
        pdf.celula_tabela(col_fu[1], row_h2, f' {f[1]}', fill=fill, ln=1)

    pdf.ln(4)
    pdf.dica(
        'Os lembretes sao enviados automaticamente. Voce nao precisa fazer nada. '
        'O sistema cuida de tudo!'
    )

    # =========================================================================
    # MOTIVOS DE REJEICAO
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('8', 'Motivos de Rejeicao')

    pdf.paragrafo(
        'Quando o paciente responde NAO, o sistema pergunta o motivo antes de finalizar. '
        'As opcoes sao:'
    )

    pdf.item_lista('1 - Ja realizei em outro hospital')
    pdf.item_lista('2 - Problemas de saude / Nao tenho condicoes')
    pdf.item_lista('3 - Nao quero mais a cirurgia')
    pdf.item_lista('4 - Outro motivo')

    pdf.paragrafo(
        'O paciente tambem pode digitar o motivo com suas proprias palavras. '
        'Tudo e registrado e aparece no relatorio.'
    )

    # =========================================================================
    # TICKETS
    # =========================================================================
    pdf.titulo_secao('9', 'Atendimento de Duvidas (Tickets)')

    pdf.paragrafo(
        'Quando o paciente envia uma mensagem que o sistema nao consegue responder automaticamente '
        '(por exemplo: "quero saber quando vai ser minha cirurgia"), um ticket de atendimento '
        'e criado para voce responder manualmente.'
    )

    pdf.subtitulo('Como funciona:')
    pdf.item_lista('Acesse o menu "Atendimento" ou "Tickets" no painel')
    pdf.item_lista('Veja as duvidas pendentes dos pacientes')
    pdf.item_lista('Responda diretamente pelo sistema')
    pdf.item_lista('O paciente recebe a resposta pelo WhatsApp')

    pdf.dica(
        'Duvidas frequentes como "onde fica o hospital?" ou "preciso de jejum?" '
        'sao respondidas automaticamente pelo FAQ. So chegam como ticket as perguntas '
        'que o sistema nao reconhece.'
    )

    # =========================================================================
    # ERROS COMUNS
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('10', 'Erros Comuns e Como Resolver')

    erros = [
        (
            'Planilha nao foi aceita',
            'Verifique se o arquivo e .xlsx (Excel). Verifique se tem as colunas "Nome" e "Telefone" '
            'na primeira linha. O nome das colunas deve ser exatamente como indicado na secao 2.'
        ),
        (
            'Numeros invalidos',
            'O telefone deve ter 10 ou 11 digitos (com DDD). Nao use espacos, tracos ou parenteses. '
            'Exemplo correto: 85999001122'
        ),
        (
            'WhatsApp desconectado',
            'Acesse Configuracoes > WhatsApp e verifique se o indicador esta verde. '
            'Se estiver vermelho, clique em "Conectar" e escaneie o QR Code novamente.'
        ),
        (
            'Mensagens nao estao sendo enviadas',
            'Verifique: 1) WhatsApp conectado; 2) Campanha iniciada; 3) Horario atual dentro do '
            'intervalo configurado (ex: se configurou 08-18h e sao 20h, so enviara amanha).'
        ),
        (
            'Paciente diz que nao recebeu',
            'Verifique o status do contato na campanha. Se mostra "ENVIADO", a mensagem foi enviada. '
            'O paciente pode ter bloqueado mensagens de desconhecidos no WhatsApp.'
        ),
    ]

    for titulo_erro, solucao in erros:
        pdf.set_font('Helvetica', 'B', 10)
        pdf.set_text_color(200, 0, 0)
        pdf.cell(0, 7, f'Problema: {titulo_erro}', 0, 1)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Helvetica', '', 10)
        pdf.multi_cell(0, 5.5, f'Solucao: {solucao}')
        pdf.ln(4)

    # =========================================================================
    # RESUMO RAPIDO
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('11', 'Resumo Rapido - Passo a Passo')

    pdf.ln(3)
    passos = [
        ('1', 'PREPARE A PLANILHA', 'Crie um arquivo Excel com colunas: Nome, Telefone, Procedimento'),
        ('2', 'ACESSE O SISTEMA', 'Faca login com seu email e senha'),
        ('3', 'CRIE A CAMPANHA', 'Clique em "Nova Campanha", de um nome e faca upload da planilha'),
        ('4', 'CONFIGURE', 'Defina meta diaria (50), horarios (08:00-18:00) e clique em criar'),
        ('5', 'AGUARDE', 'O sistema processa a planilha e normaliza os procedimentos'),
        ('6', 'INICIE OS ENVIOS', 'Clique em "Iniciar Envios" na pagina da campanha'),
        ('7', 'ACOMPANHE', 'Veja os resultados em tempo real no Dashboard'),
        ('8', 'ATENDA TICKETS', 'Responda duvidas que o FAQ nao conseguiu resolver'),
        ('9', 'EXPORTE', 'Baixe o relatorio completo em Excel quando precisar'),
    ]

    for num, titulo_p, desc in passos:
        pdf.set_fill_color(0, 123, 255)
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.cell(10, 8, f' {num}', 0, 0, 'C', fill=True)
        pdf.set_text_color(0, 0, 0)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(55, 8, f'  {titulo_p}')
        pdf.set_font('Helvetica', '', 10)
        pdf.cell(0, 8, desc, 0, 1)
        pdf.ln(2)

    pdf.ln(10)
    pdf.set_draw_color(0, 123, 255)
    pdf.set_line_width(0.5)
    pdf.line(40, pdf.get_y(), 170, pdf.get_y())
    pdf.ln(8)
    pdf.set_font('Helvetica', 'I', 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, 'Em caso de duvidas, entre em contato com o suporte tecnico.', 0, 1, 'C')
    pdf.cell(0, 8, 'Hospital Universitario Walter Cantidio - HUWC', 0, 1, 'C')

    # Salvar
    output_path = '/home/user/git3/tutorial_fila_cirurgica.pdf'
    pdf.output(output_path)
    print(f'PDF gerado com sucesso: {output_path}')
    return output_path


if __name__ == '__main__':
    gerar_tutorial()
