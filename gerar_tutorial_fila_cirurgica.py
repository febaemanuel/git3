#!/usr/bin/env python3
"""
Gera o PDF do tutorial do Modo Fila Cirúrgica para usuários leigos.
Uso: python3 gerar_tutorial_fila_cirurgica.py
Saída: tutorial_fila_cirurgica.pdf
"""

from fpdf import FPDF

FONT_REGULAR = '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf'
FONT_BOLD    = '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf'
FONT_ITALIC  = '/usr/share/fonts/truetype/dejavu/DejaVuSansMono-Oblique.ttf'

AZUL      = (0, 100, 200)
AZUL_ESC  = (0, 60, 130)
CINZA_ESC = (52, 58, 64)
BRANCO    = (255, 255, 255)
AMARELO   = (255, 243, 205)
AZUL_CLARO = (209, 236, 241)
VERDE_CLARO = (220, 248, 220)
CINZA_CLARO = (240, 240, 240)
VERMELHO  = (190, 0, 0)
PRETO     = (0, 0, 0)

class TutorialPDF(FPDF):
    def header(self):
        self.set_font('dv', '', 9)
        self.set_text_color(*[100]*3)
        self.cell(0, 7, 'Tutorial – Modo Fila Cirúrgica | HUWC', 0, new_x='LMARGIN', new_y='NEXT', align='C')
        self.set_draw_color(*AZUL)
        self.set_line_width(0.4)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(3)

    def footer(self):
        self.set_y(-14)
        self.set_font('dv', '', 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 8, f'Página {self.page_no()}/{{nb}}', 0, align='C')

    def titulo_secao(self, numero, texto):
        self.ln(5)
        self.set_fill_color(*AZUL)
        self.set_text_color(*BRANCO)
        self.set_font('dvb', '', 13)
        self.cell(0, 10, f'  {numero}. {texto}', 0, new_x='LMARGIN', new_y='NEXT', fill=True)
        self.ln(3)
        self.set_text_color(*PRETO)

    def subtitulo(self, texto):
        self.ln(3)
        self.set_font('dvb', '', 11)
        self.set_text_color(*AZUL_ESC)
        self.cell(0, 7, texto, 0, new_x='LMARGIN', new_y='NEXT')
        self.set_text_color(*PRETO)
        self.ln(1)

    def paragrafo(self, texto):
        self.set_font('dv', '', 10)
        self.multi_cell(0, 5.5, texto)
        self.ln(2)

    def item_lista(self, texto):
        self.set_font('dv', '', 10)
        self.cell(8, 5.5, '›', 0)
        self.multi_cell(0, 5.5, texto)
        self.ln(1)

    def destaque(self, texto):
        self.set_fill_color(*AMARELO)
        self.set_font('dvb', '', 10)
        self.multi_cell(0, 6, f'  [!] IMPORTANTE: {texto}', border=0, fill=True)
        self.ln(3)

    def dica(self, texto):
        self.set_fill_color(*AZUL_CLARO)
        self.set_font('dv', '', 10)
        self.multi_cell(0, 6, f'  >> DICA: {texto}', border=0, fill=True)
        self.ln(3)

    ROW_H = 7

    def th(self, widths, labels):
        self.set_fill_color(*CINZA_ESC)
        self.set_text_color(*BRANCO)
        self.set_font('dvb', '', 9)
        for i, (w, label) in enumerate(zip(widths, labels)):
            nx = 'LMARGIN' if i == len(labels)-1 else 'RIGHT'
            ny = 'NEXT'    if i == len(labels)-1 else 'TOP'
            self.cell(w, self.ROW_H, f' {label}', 1, new_x=nx, new_y=ny, fill=True)
        self.set_text_color(*PRETO)

    def tr(self, widths, values, fill=False, bold_first=False):
        if fill:
            self.set_fill_color(*CINZA_CLARO)
        for i, (w, val) in enumerate(zip(widths, values)):
            nx = 'LMARGIN' if i == len(values)-1 else 'RIGHT'
            ny = 'NEXT'    if i == len(values)-1 else 'TOP'
            self.set_font('dvb' if (bold_first and i == 0) else 'dv', '', 9)
            self.cell(w, self.ROW_H, f' {val}', 1, new_x=nx, new_y=ny, fill=fill)


def gerar_tutorial():
    pdf = TutorialPDF()
    pdf.add_font('dv',  '', FONT_REGULAR)
    pdf.add_font('dvb', '', FONT_BOLD)
    pdf.add_font('dvi', '', FONT_ITALIC)
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # =========================================================================
    # CAPA
    # =========================================================================
    pdf.add_page()
    pdf.ln(28)
    pdf.set_font('dvb', '', 30)
    pdf.set_text_color(*AZUL)
    pdf.cell(0, 16, 'TUTORIAL', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('dvb', '', 22)
    pdf.cell(0, 12, 'Modo Fila Cirúrgica', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(6)
    pdf.set_draw_color(*AZUL)
    pdf.set_line_width(1)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())
    pdf.ln(10)
    pdf.set_font('dv', '', 13)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, 'Sistema de Busca Ativa de Pacientes', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 8, 'Hospital Universitário Walter Cantídio', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(12)
    pdf.set_font('dv', '', 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 7, 'Guia completo para criar campanhas,', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 7, 'importar planilhas e gerenciar a fila cirúrgica', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.cell(0, 7, 'via WhatsApp de forma automatizada.', align='C', new_x='LMARGIN', new_y='NEXT')
    pdf.ln(28)
    pdf.set_fill_color(242, 242, 242)
    pdf.set_font('dvi', '', 10)
    pdf.set_text_color(120, 120, 120)
    pdf.multi_cell(0, 6,
        '  Este tutorial foi feito para usuários sem experiência técnica.\n'
        '  Siga cada passo na ordem indicada.',
        border=0, align='C', fill=True)

    # =========================================================================
    # O QUE É O SISTEMA
    # =========================================================================
    pdf.add_page()
    pdf.set_text_color(*PRETO)
    pdf.titulo_secao('1', 'O que é o Sistema de Fila Cirúrgica?')
    pdf.paragrafo(
        'O Sistema de Fila Cirúrgica entra em contato com pacientes que estão na lista de espera '
        'para cirurgias no Hospital Universitário Walter Cantídio. O contato é feito de forma '
        'automática pelo WhatsApp.'
    )
    pdf.paragrafo('O sistema faz o seguinte automaticamente:')
    pdf.item_lista('Envia mensagem pelo WhatsApp para cada paciente da lista')
    pdf.item_lista('Pergunta se o paciente ainda tem interesse na cirurgia')
    pdf.item_lista('Registra a resposta (SIM, NÃO ou DESCONHEÇO)')
    pdf.item_lista('Se o paciente não responder, reenvia lembretes automaticamente')
    pdf.item_lista('Gera relatórios com o resultado de cada paciente')
    pdf.item_lista('Responde dúvidas comuns dos pacientes automaticamente (FAQ)')
    pdf.ln(3)
    pdf.destaque(
        'Você NÃO precisa enviar mensagens manualmente. O sistema faz tudo sozinho '
        'após a campanha ser criada e iniciada.'
    )

    # =========================================================================
    # PREPARAR A PLANILHA
    # =========================================================================
    pdf.titulo_secao('2', 'Como Preparar a Planilha Excel')
    pdf.paragrafo(
        'A planilha é o arquivo Excel (.xlsx) com os dados dos pacientes. '
        'É a parte mais importante: se a planilha estiver errada, o sistema não vai funcionar.'
    )
    pdf.subtitulo('Colunas obrigatórias')
    pdf.paragrafo('A planilha DEVE ter estas duas colunas. O nome deve ser exatamente como abaixo:')

    cw = [40, 30, 55, 65]
    pdf.th(cw, ['Coluna', 'Obrigatório?', 'Formato', 'Exemplo'])
    linhas = [
        ['Nome', '✔ SIM', 'Texto (nome completo)', 'Maria da Silva'],
        ['Telefone', '✔ SIM', 'Número com DDD, sem traços', '85992231683'],
        ['Procedimento', 'Opcional', 'Texto da cirurgia', 'Cirurgia de Catarata'],
    ]
    for i, linha in enumerate(linhas):
        pdf.tr(cw, linha, fill=(i % 2 == 0), bold_first=True)

    pdf.ln(5)
    pdf.subtitulo('Nomes aceitos para cada coluna')
    pdf.paragrafo('O sistema reconhece variações do nome. Veja o que funciona:')
    pdf.item_lista('Coluna Nome: "nome", "usuario", "usuário", "paciente"')
    pdf.item_lista('Coluna Telefone: "telefone", "celular", "fone", "tel", "whatsapp", "contato"')
    pdf.item_lista('Coluna Procedimento: "procedimento", "cirurgia", "procedimentos"')

    pdf.ln(3)
    pdf.subtitulo('Como informar o Telefone')
    pdf.item_lista('Coloque o número com DDD, sem espaços, traços ou parênteses: 85992231683')
    pdf.item_lista(
        'Se o paciente tem MAIS DE UM telefone, coloque todos na MESMA célula separados por espaço:\n'
        '       Exemplo: 85992231683 85997293229'
    )
    pdf.item_lista('O sistema separa e testa cada número automaticamente')
    pdf.item_lista('Aceita até 5 telefones por paciente')

    pdf.ln(2)
    pdf.dica(
        'Telefones separados por vírgula, ponto e vírgula ou espaço são todos reconhecidos. '
        'Ex: "85992231683 85997293229" ou "85992231683, 85997293229" — ambos funcionam.'
    )

    # =========================================================================
    # EXEMPLO DE PLANILHA
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('3', 'Exemplo de Planilha Correta')

    cex = [55, 65, 70]
    pdf.th(cex, ['Nome', 'Telefone', 'Procedimento'])
    exemplos = [
        ['Maria da Silva',  '85992231683 85997293229', 'Cirurgia de Catarata'],
        ['José Santos',     '85988112233',             'Hérnia Inguinal'],
        ['Ana Oliveira',    '85977334455',             'Artroscopia de Joelho'],
    ]
    for i, ex in enumerate(exemplos):
        pdf.tr(cex, ex, fill=(i % 2 == 0))

    pdf.ln(5)
    pdf.dica(
        '"Maria da Silva" tem dois telefones na mesma célula. O sistema separa '
        'automaticamente e envia para os dois números!'
    )
    pdf.destaque(
        'Salve a planilha no formato .xlsx (Excel). '
        'Arquivos .csv ou .pdf NÃO são aceitos.'
    )

    pdf.subtitulo('Regras importantes')
    pdf.item_lista('Use o nome completo do paciente na coluna Nome')
    pdf.item_lista('O sistema agrupa linhas com o MESMO NOME como sendo o mesmo paciente')
    pdf.item_lista(
        'Se o nome estiver escrito diferente (ex: "Jose" vs "José Santos"), '
        'serão tratados como pessoas diferentes — revise bem os nomes'
    )
    pdf.item_lista('Números inválidos são ignorados automaticamente')

    # =========================================================================
    # CRIAR CAMPANHA
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('4', 'Como Criar uma Campanha')
    pdf.paragrafo(
        'Campanha é o nome dado a um lote de pacientes que serão contatados. '
        'Exemplo: "Fila Cirúrgica Oftalmologia Março 2026".'
    )

    passos_campanha = [
        ('Passo 1: Acesse o painel',
         'Faça login no sistema com seu e-mail e senha.'),
        ('Passo 2: Clique em "Nova Campanha"',
         'No painel principal (Dashboard), clique no botão "Nova Campanha".'),
        ('Passo 3: Preencha os dados',
         'Nome da Campanha: dê um nome descritivo (ex: "Oftalmologia Março 2026")\n'
         '       Meta Diária: quantas mensagens enviar por dia (recomendado: 50)\n'
         '       Horário Início: quando começar os envios (ex: 08:00)\n'
         '       Horário Fim: quando parar os envios (ex: 18:00)'),
        ('Passo 4: Anexe a planilha',
         'Clique no botão de upload e selecione o arquivo .xlsx que você preparou.'),
        ('Passo 5: Aguarde o processamento',
         'O sistema processa a planilha, valida os números e normaliza os procedimentos. '
         'Uma barra de progresso será exibida. Pode levar alguns minutos.'),
    ]
    for titulo_p, desc in passos_campanha:
        pdf.set_font('dvb', '', 10)
        pdf.set_text_color(*AZUL_ESC)
        pdf.cell(0, 6, titulo_p, new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(*PRETO)
        pdf.set_font('dv', '', 10)
        pdf.multi_cell(0, 5.5, f'       {desc}')
        pdf.ln(3)

    pdf.dica(
        'O cálculo do intervalo entre envios é automático. '
        'Meta de 50 mensagens entre 08:00 e 18:00 = 1 envio a cada 12 minutos.'
    )

    # =========================================================================
    # INICIAR ENVIOS
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('5', 'Iniciar os Envios')

    pdf.subtitulo('Antes de iniciar, verifique:')
    pdf.item_lista('O WhatsApp está conectado (indicador verde no topo da página)')
    pdf.item_lista('A campanha foi processada com sucesso')
    pdf.item_lista('Os horários de envio estão corretos')

    pdf.subtitulo('Iniciando')
    pdf.paragrafo(
        'Na página da campanha, clique no botão "Iniciar Envios". '
        'O sistema começará a enviar automaticamente, respeitando o intervalo e os horários.'
    )
    pdf.destaque(
        'NÃO feche o navegador durante os envios. O sistema precisa estar ativo para enviar.'
    )

    pdf.subtitulo('Mensagem que o paciente recebe')
    pdf.ln(2)
    pdf.set_fill_color(*VERDE_CLARO)
    pdf.set_font('dv', '', 9.5)
    pdf.multi_cell(0, 5.5,
        '  Olá, Maria da Silva!\n\n'
        '  Aqui é da Central de Agendamentos do Hospital Universitário Walter Cantídio.\n\n'
        '  Consta em nossos registros que você está na lista de espera para o\n'
        '  procedimento: Cirurgia de Catarata.\n\n'
        '  Você ainda tem interesse em realizar esta cirurgia?\n\n'
        '  1 – SIM  – Tenho interesse\n'
        '  2 – NÃO  – Não tenho mais interesse\n'
        '  3 – DESCONHEÇO – Não sou essa pessoa',
        border=1, fill=True)
    pdf.ln(4)

    pdf.subtitulo('O que acontece com a resposta do paciente?')
    cw2 = [42, 148]
    pdf.th(cw2, ['Resposta', 'O que acontece'])
    resps = [
        ['1 ou SIM',    'Paciente fica como CONFIRMADO. Recebe mensagem de confirmação.'],
        ['2 ou NÃO',    'Sistema pergunta o motivo. Paciente fica como REJEITADO.'],
        ['3 ou DESCON.','Número marcado como "não pertence ao paciente".'],
        ['Sem resposta','Sistema reenvia lembretes automaticamente (até 2 vezes).'],
    ]
    for i, r in enumerate(resps):
        pdf.tr(cw2, r, fill=(i % 2 == 0), bold_first=True)

    # =========================================================================
    # ACOMPANHAMENTO
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('6', 'Acompanhar os Resultados')
    pdf.paragrafo(
        'No Dashboard você acompanha em tempo real o progresso de cada campanha:'
    )
    pdf.item_lista('Total de contatos importados')
    pdf.item_lista('Quantos já foram enviados')
    pdf.item_lista('Quantos confirmaram interesse (SIM)')
    pdf.item_lista('Quantos rejeitaram (NÃO)')
    pdf.item_lista('Quantos ainda não responderam')
    pdf.item_lista('Quantos tiveram erro no envio')

    pdf.subtitulo('Status dos Pacientes')
    cw3 = [38, 152]
    pdf.th(cw3, ['Status', 'Significado'])
    status_lista = [
        ['AGUARDANDO',  'Mensagem ainda não foi enviada (na fila de envio)'],
        ['ENVIADO',     'Mensagem enviada, aguardando resposta do paciente'],
        ['CONFIRMADO',  'Paciente respondeu SIM – tem interesse na cirurgia'],
        ['REJEITADO',   'Paciente respondeu NÃO ou todos os telefones não reconhecem'],
        ['ERRO',        'Erro no envio (número inválido, WhatsApp desconectado, etc.)'],
    ]
    for i, s in enumerate(status_lista):
        pdf.tr(cw3, s, fill=(i % 2 == 0), bold_first=True)

    pdf.ln(5)
    pdf.subtitulo('Exportar Relatório')
    pdf.paragrafo(
        'Clique em "Exportar" para baixar todos os dados em Excel. '
        'O arquivo contém: nome, telefone, procedimento, status, data de envio e resposta do paciente.'
    )

    # =========================================================================
    # LEMBRETES AUTOMÁTICOS
    # =========================================================================
    pdf.titulo_secao('7', 'Lembretes Automáticos (Follow-up)')
    pdf.paragrafo(
        'Se o paciente NÃO responder à primeira mensagem, o sistema envia lembretes:'
    )
    cw4 = [45, 145]
    pdf.th(cw4, ['Quando', 'O que acontece'])
    followups = [
        ['Após 24 horas', '1.º lembrete: "Ainda não recebemos sua confirmação…"'],
        ['Após 48 horas', '2.º lembrete (ÚLTIMO): "ÚLTIMA TENTATIVA DE CONTATO…"'],
        ['Após 72 horas', 'Encerramento: vaga disponibilizada por falta de resposta'],
    ]
    for i, f in enumerate(followups):
        pdf.tr(cw4, f, fill=(i % 2 == 0))
    pdf.ln(4)
    pdf.dica(
        'Os lembretes são enviados automaticamente. Você não precisa fazer nada. '
        'O sistema cuida de tudo!'
    )

    # =========================================================================
    # MOTIVOS DE REJEIÇÃO
    # =========================================================================
    pdf.titulo_secao('8', 'Motivos de Rejeição')
    pdf.paragrafo(
        'Quando o paciente responde NÃO, o sistema pergunta o motivo antes de finalizar:'
    )
    pdf.item_lista('1 – Já realizei em outro hospital')
    pdf.item_lista('2 – Problemas de saúde / Não tenho condições')
    pdf.item_lista('3 – Não quero mais a cirurgia')
    pdf.item_lista('4 – Outro motivo')
    pdf.paragrafo(
        'O paciente também pode digitar o motivo com suas próprias palavras. '
        'Tudo é registrado e aparece no relatório.'
    )

    # =========================================================================
    # TICKETS
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('9', 'Atendimento de Dúvidas (Tickets)')
    pdf.paragrafo(
        'Quando o paciente envia uma mensagem que o sistema não consegue responder '
        'automaticamente, um ticket é criado para você responder manualmente.'
    )
    pdf.subtitulo('Como funciona:')
    pdf.item_lista('Acesse o menu "Atendimento" ou "Tickets" no painel')
    pdf.item_lista('Veja as dúvidas pendentes dos pacientes')
    pdf.item_lista('Responda diretamente pelo sistema')
    pdf.item_lista('O paciente recebe a resposta pelo WhatsApp')
    pdf.dica(
        'Dúvidas frequentes como "onde fica o hospital?" ou "preciso de jejum?" '
        'são respondidas automaticamente pelo FAQ. Só chegam como ticket as perguntas '
        'que o sistema não reconhece.'
    )

    # =========================================================================
    # ERROS COMUNS
    # =========================================================================
    pdf.titulo_secao('10', 'Erros Comuns e Como Resolver')
    erros = [
        ('Planilha não foi aceita',
         'Verifique se o arquivo é .xlsx (Excel). Verifique se tem as colunas "Nome" e "Telefone" '
         'na primeira linha, escritas exatamente assim.'),
        ('Números inválidos',
         'O telefone deve ter 10 ou 11 dígitos (com DDD). Não use espaços, traços ou parênteses. '
         'Exemplo correto: 85999001122. Para dois números na mesma célula: 85999001122 85988776655'),
        ('WhatsApp desconectado',
         'Acesse Configurações > WhatsApp. Se o indicador estiver vermelho, clique em "Conectar" '
         'e escaneie o QR Code novamente.'),
        ('Mensagens não estão sendo enviadas',
         'Verifique: 1) WhatsApp conectado; 2) Campanha iniciada; '
         '3) Horário atual dentro do intervalo configurado (ex: se configurou 08–18h e são 20h, '
         'enviará amanhã).'),
        ('Paciente diz que não recebeu',
         'Verifique o status do contato na campanha. Se mostra "ENVIADO", a mensagem foi enviada. '
         'O paciente pode ter bloqueado mensagens de desconhecidos no WhatsApp.'),
    ]
    for titulo_erro, solucao in erros:
        pdf.set_font('dvb', '', 10)
        pdf.set_text_color(*VERMELHO)
        pdf.cell(0, 7, f'Problema: {titulo_erro}', new_x='LMARGIN', new_y='NEXT')
        pdf.set_text_color(*PRETO)
        pdf.set_font('dv', '', 10)
        pdf.multi_cell(0, 5.5, f'Solução: {solucao}')
        pdf.ln(4)

    # =========================================================================
    # RESUMO RÁPIDO
    # =========================================================================
    pdf.add_page()
    pdf.titulo_secao('11', 'Resumo Rápido – Passo a Passo')
    pdf.ln(3)
    passos = [
        ('1', 'PREPARE A PLANILHA',
         'Crie um Excel com colunas: Nome, Telefone, Procedimento'),
        ('2', 'ACESSE O SISTEMA',
         'Faça login com seu e-mail e senha'),
        ('3', 'CRIE A CAMPANHA',
         'Clique em "Nova Campanha", dê um nome e faça upload da planilha'),
        ('4', 'CONFIGURE',
         'Defina meta diária (50), horários (08:00–18:00) e clique em criar'),
        ('5', 'AGUARDE',
         'O sistema processa a planilha e normaliza os procedimentos'),
        ('6', 'INICIE OS ENVIOS',
         'Clique em "Iniciar Envios" na página da campanha'),
        ('7', 'ACOMPANHE',
         'Veja os resultados em tempo real no Dashboard'),
        ('8', 'ATENDA TICKETS',
         'Responda dúvidas que o FAQ não conseguiu resolver'),
        ('9', 'EXPORTE',
         'Baixe o relatório completo em Excel quando precisar'),
    ]
    for num, titulo_p, desc in passos:
        pdf.set_fill_color(*AZUL)
        pdf.set_text_color(*BRANCO)
        pdf.set_font('dvb', '', 12)
        pdf.cell(10, 9, f' {num}', border=0, new_x='RIGHT', new_y='TOP', fill=True, align='C')
        pdf.set_text_color(*PRETO)
        pdf.set_font('dvb', '', 10)
        pdf.cell(55, 9, f'  {titulo_p}')
        pdf.set_font('dv', '', 10)
        pdf.cell(0, 9, desc, new_x='LMARGIN', new_y='NEXT')
        pdf.ln(2)

    pdf.ln(10)
    pdf.set_draw_color(*AZUL)
    pdf.set_line_width(0.5)
    pdf.line(40, pdf.get_y(), 170, pdf.get_y())
    pdf.ln(8)
    pdf.set_font('dvi', '', 11)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 8, 'Em caso de dúvidas, entre em contato com o suporte técnico.',
             new_x='LMARGIN', new_y='NEXT', align='C')
    pdf.cell(0, 8, 'Hospital Universitário Walter Cantídio – HUWC',
             new_x='LMARGIN', new_y='NEXT', align='C')

    output_path = '/home/user/git3/tutorial_fila_cirurgica.pdf'
    pdf.output(output_path)
    print(f'PDF gerado: {output_path}')
    return output_path


if __name__ == '__main__':
    gerar_tutorial()
