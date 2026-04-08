#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Gerador do Guia do Usuário - Modo Cirurgia (Fila Cirúrgica / Busca Ativa)
Hospital Universitário Walter Cantídio
"""

from fpdf import FPDF
from datetime import datetime


class GuidePDF(FPDF):
    """PDF customizado para o guia do usuário."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=25)

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(130, 130, 130)
        self.cell(0, 8, "Guia do Usuario - Modo Cirurgia (Busca Ativa) | HUWC", align="L")
        self.cell(0, 8, f"Pagina {self.page_no()}", align="R", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(200, 200, 200)
        self.line(10, 16, 200, 16)
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 7)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Documento gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} | Hospital Universitario Walter Cantidio", align="C")

    # ── Helpers ──────────────────────────────────────────────
    def chapter_title(self, number, title):
        self.ln(6)
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(25, 60, 120)
        self.cell(0, 10, f"{number}. {title}", new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(25, 60, 120)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def section_title(self, title):
        self.ln(3)
        self.set_font("Helvetica", "B", 12)
        self.set_text_color(50, 90, 160)
        self.cell(0, 8, title, new_x="LMARGIN", new_y="NEXT")
        self.ln(2)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 6, text)
        self.ln(2)

    def bullet(self, text, indent=15):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 6, f"-  {text}")

    def bold_bullet(self, bold_part, text, indent=15):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.set_x(self.l_margin + indent)
        self.multi_cell(0, 6, f"-  {bold_part} {text}")

    def note_box(self, text, bg_r=230, bg_g=240, bg_b=255):
        self.ln(2)
        y = self.get_y()
        self.set_fill_color(bg_r, bg_g, bg_b)
        self.set_draw_color(100, 140, 200)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(30, 60, 120)
        self.cell(15, 6, " NOTA:", fill=True)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 6, f" {text}", fill=True)
        self.ln(3)

    def warning_box(self, text):
        self.ln(2)
        self.set_fill_color(255, 248, 220)
        self.set_draw_color(200, 170, 50)
        self.set_font("Helvetica", "B", 9)
        self.set_text_color(150, 100, 0)
        self.cell(25, 6, " ATENCAO:", fill=True)
        self.set_font("Helvetica", "", 9)
        self.multi_cell(0, 6, f" {text}", fill=True)
        self.ln(3)

    def status_badge(self, label, r, g, b, text_r=255, text_g=255, text_b=255):
        self.set_fill_color(r, g, b)
        self.set_text_color(text_r, text_g, text_b)
        self.set_font("Helvetica", "B", 9)
        w = self.get_string_width(f" {label} ") + 6
        self.cell(w, 7, f" {label} ", fill=True)
        self.cell(3, 7, "")  # spacing

    def table_header(self, headers, widths):
        self.set_fill_color(40, 70, 130)
        self.set_text_color(255, 255, 255)
        self.set_font("Helvetica", "B", 9)
        for i, h in enumerate(headers):
            self.cell(widths[i], 8, h, border=1, fill=True, align="C")
        self.ln()

    def table_row(self, cells, widths, fill=False):
        if fill:
            self.set_fill_color(245, 248, 255)
        else:
            self.set_fill_color(255, 255, 255)
        self.set_text_color(40, 40, 40)
        self.set_font("Helvetica", "", 8)

        max_h = 8
        # Calculate max height needed
        for i, c in enumerate(cells):
            lines = self.multi_cell(widths[i], 5, c, dry_run=True, output="LINES")
            h = len(lines) * 5
            if h > max_h:
                max_h = h

        x_start = self.get_x()
        y_start = self.get_y()

        for i, c in enumerate(cells):
            self.set_xy(x_start + sum(widths[:i]), y_start)
            self.cell(widths[i], max_h, "", border=1, fill=fill)
            self.set_xy(x_start + sum(widths[:i]) + 1, y_start + 1)
            self.multi_cell(widths[i] - 2, 5, c)

        self.set_xy(x_start, y_start + max_h)


def build_pdf():
    pdf = GuidePDF()

    # ══════════════════════════════════════════════════════════
    # CAPA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(30)

    # Header line
    pdf.set_draw_color(25, 60, 120)
    pdf.set_line_width(1)
    pdf.line(30, 50, 180, 50)

    pdf.ln(15)
    pdf.set_font("Helvetica", "B", 28)
    pdf.set_text_color(25, 60, 120)
    pdf.cell(0, 15, "GUIA DO USUARIO", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 20)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 12, "Modo Cirurgia", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 12, "(Fila Cirurgica / Busca Ativa)", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_draw_color(25, 60, 120)
    pdf.set_line_width(0.5)
    pdf.line(60, pdf.get_y(), 150, pdf.get_y())

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 13)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 10, "Sistema de Busca Ativa via WhatsApp", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 10, "Hospital Universitario Walter Cantidio", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(20)
    pdf.set_fill_color(240, 245, 255)
    pdf.set_draw_color(25, 60, 120)
    pdf.rect(40, pdf.get_y(), 130, 30, style="DF")
    pdf.set_font("Helvetica", "B", 11)
    pdf.set_text_color(25, 60, 120)
    pdf.set_x(40)
    pdf.cell(130, 10, "Versao: 1.0", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_x(40)
    pdf.cell(130, 10, f"Data: {datetime.now().strftime('%d/%m/%Y')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_x(40)
    pdf.cell(130, 10, "Documento baseado no codigo-fonte do sistema", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(15)
    pdf.set_draw_color(25, 60, 120)
    pdf.set_line_width(1)
    pdf.line(30, pdf.get_y(), 180, pdf.get_y())

    # ══════════════════════════════════════════════════════════
    # SUMARIO
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 18)
    pdf.set_text_color(25, 60, 120)
    pdf.cell(0, 12, "SUMARIO", new_x="LMARGIN", new_y="NEXT")
    pdf.set_draw_color(25, 60, 120)
    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(8)

    sumario = [
        ("1", "O que e o Modo Cirurgia?"),
        ("2", "Acessando o Modo Cirurgia"),
        ("3", "Painel Principal (Dashboard)"),
        ("4", "Criando uma Nova Campanha"),
        ("5", "Planilha de Importacao - Colunas Obrigatorias"),
        ("6", "Processamento da Campanha"),
        ("7", "Gerenciando Contatos"),
        ("8", "Status dos Contatos - Cores e Significados"),
        ("9", "Fluxo de Mensagens Automaticas"),
        ("10", "Respostas do Paciente"),
        ("11", "Acoes Manuais sobre Contatos"),
        ("12", "Chat / Historico de Mensagens"),
        ("13", "Exportacao de Dados para Excel"),
        ("14", "Graficos e Relatorios"),
        ("15", "Dicas e Boas Praticas"),
    ]

    for num, title in sumario:
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(25, 60, 120)
        pdf.cell(12, 7, num)
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(60, 60, 60)
        pdf.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════════════
    # 1. O QUE E O MODO CIRURGIA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("1", "O que e o Modo Cirurgia?")

    pdf.body_text(
        "O Modo Cirurgia (tambem chamado de Fila Cirurgica ou Busca Ativa) e um "
        "subsistema do sistema de comunicacao via WhatsApp do Hospital Universitario "
        "Walter Cantidio. Ele permite entrar em contato automaticamente com pacientes "
        "que estao na fila de espera para procedimentos cirurgicos, verificando se "
        "ainda possuem interesse em realizar a cirurgia."
    )

    pdf.section_title("Objetivos principais")
    pdf.bold_bullet("Busca Ativa:", "Contatar pacientes da fila cirurgica automaticamente via WhatsApp")
    pdf.bold_bullet("Confirmacao:", "Registrar se o paciente confirma ou rejeita o procedimento")
    pdf.bold_bullet("Motivo:", "Coletar o motivo quando o paciente rejeita a cirurgia")
    pdf.bold_bullet("Gestao:", "Fornecer estatisticas e relatorios sobre a fila cirurgica")
    pdf.bold_bullet("Retentativa:", "Reenviar mensagens automaticamente para quem nao respondeu")

    pdf.ln(3)
    pdf.section_title("Diferenca entre Modo Cirurgia e Modo Consulta")

    headers = ["Caracteristica", "Modo Cirurgia (Fila)", "Modo Consulta"]
    widths = [55, 65, 65]
    pdf.table_header(headers, widths)

    rows = [
        ("Finalidade", "Busca ativa em fila cirurgica", "Agendamento de consultas"),
        ("Identificador no sistema", "BUSCA_ATIVA", "AGENDAMENTO_CONSULTA"),
        ("Icone no painel", "Icone de pessoas (bi-people-fill)", "Icone de calendario (bi-calendar-check)"),
        ("Cor no dashboard", "Escuro (btn-dark)", "Verde (btn-success)"),
        ("Opcoes do paciente", "SIM / NAO / DESCONHECO", "Confirmacao de consulta"),
        ("Retentativas", "2 retentativas automaticas", "Variavel"),
        ("Coleta de motivo", "Sim, ao rejeitar", "Sim"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════════════
    # 2. ACESSANDO O MODO CIRURGIA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("2", "Acessando o Modo Cirurgia")

    pdf.body_text(
        "Para acessar o Modo Cirurgia, voce precisa estar logado no sistema como "
        "administrador ou usuario com permissao de Busca Ativa."
    )

    pdf.section_title("Passo a passo")
    pdf.bold_bullet("1.", "Faca login no sistema com suas credenciais")
    pdf.bold_bullet("2.", "No Painel Administrativo, localize o seletor de modo no topo da pagina")
    pdf.bold_bullet("3.", "Clique no botao 'Modo Fila' (cor escura, icone de pessoas)")
    pdf.ln(2)

    pdf.section_title("Botoes do Seletor de Modo")

    headers = ["Botao", "Icone", "Cor", "Funcao"]
    widths = [40, 40, 35, 70]
    pdf.table_header(headers, widths)
    rows = [
        ("Modo Consulta", "bi-calendar-check", "Verde (success)", "Visualiza campanhas de agendamento"),
        ("Modo Fila", "bi-people-fill", "Escuro (dark)", "Visualiza campanhas de busca ativa"),
        ("Todos", "bi-grid", "Azul (primary)", "Visualiza todas as campanhas"),
        ("Atualizar", "bi-arrow-clockwise", "Cinza (secondary)", "Recarrega dados do painel"),
        ("Exportar Excel", "bi-file-earmark-excel", "Verde (success)", "Abre modal de exportacao"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.note_box("O seletor de modo lembra sua ultima selecao. Ao voltar ao painel, o modo anterior e mantido.")

    # ══════════════════════════════════════════════════════════
    # 3. PAINEL PRINCIPAL
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("3", "Painel Principal (Dashboard)")

    pdf.body_text(
        "Ao selecionar o Modo Fila, o dashboard exibe cartoes de resumo e graficos "
        "especificos para campanhas de Busca Ativa."
    )

    pdf.section_title("Cartoes de Resumo (Cards)")

    headers = ["Cartao", "Cor", "O que mostra"]
    widths = [45, 40, 100]
    pdf.table_header(headers, widths)
    rows = [
        ("Campanhas Fila", "Borda escura (dark)", "Quantidade total de campanhas de fila + ativas"),
        ("Contatos", "Texto azul (info)", "Total de contatos importados nas campanhas"),
        ("Enviados", "Texto azul (info)", "Total de mensagens ja enviadas"),
        ("Confirmados", "Texto verde (success)", "Total de pacientes que confirmaram + percentual"),
        ("Rejeitados", "Texto amarelo (warning)", "Total de pacientes que rejeitaram"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Cartao Comparativo - Modo Fila")
    pdf.body_text(
        "Abaixo dos cartoes de resumo, existe um cartao com cabecalho escuro (bg-dark) "
        "intitulado 'Modo Fila (Busca Ativa)' com icone bi-people-fill. Ele apresenta:"
    )
    pdf.bold_bullet("Campanhas e Contatos:", "Numeros totais lado a lado")
    pdf.bold_bullet("Enviados / Confirmados / Rejeitados:", "Tres colunas coloridas (azul, verde, amarelo)")
    pdf.bold_bullet("Taxa de Confirmacao:", "Barra de progresso verde mostrando o percentual")
    pdf.bold_bullet("Erros de envio:", "Alerta amarelo com icone de exclamacao (bi-exclamation-triangle)")

    # ══════════════════════════════════════════════════════════
    # 4. CRIANDO UMA NOVA CAMPANHA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("4", "Criando uma Nova Campanha")

    pdf.body_text(
        "Uma campanha no Modo Cirurgia e um lote de pacientes que serao contatados "
        "via WhatsApp para verificar interesse em procedimentos cirurgicos."
    )

    pdf.section_title("Campos do formulario de nova campanha")

    headers = ["Campo", "Tipo", "Obrigatorio", "Descricao"]
    widths = [35, 25, 20, 105]
    pdf.table_header(headers, widths)
    rows = [
        ("Nome", "Texto", "Sim", "Nome identificador da campanha"),
        ("Descricao", "Texto longo", "Nao", "Descricao detalhada da campanha"),
        ("Arquivo Excel", "Upload (.xlsx)", "Sim", "Planilha com dados dos pacientes"),
        ("Meta Diaria", "Numero", "Sim", "Quantidade de envios por dia (padrao variavel)"),
        ("Hora Inicio", "Numero (8-23)", "Sim", "Hora de inicio dos envios (padrao: 8h)"),
        ("Hora Fim", "Numero (8-23)", "Sim", "Hora de fim dos envios (padrao: 17h)"),
        ("Tempo entre envios", "Segundos", "Sim", "Intervalo entre cada envio"),
        ("Dias de duracao", "Numero", "Nao", "Duracao em dias (0 = ilimitado)"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.warning_box(
        "O arquivo Excel deve seguir o formato especificado na proxima secao. "
        "Arquivos fora do padrao podem causar erros no processamento."
    )

    # ══════════════════════════════════════════════════════════
    # 5. PLANILHA DE IMPORTACAO
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("5", "Planilha de Importacao - Colunas Obrigatorias")

    pdf.body_text(
        "A planilha Excel (.xlsx) que voce faz upload deve conter as seguintes colunas. "
        "O sistema identifica as colunas pelo nome do cabecalho."
    )

    pdf.section_title("Colunas obrigatorias da planilha")

    headers = ["Coluna", "Obrigatoria", "Formato", "Exemplo"]
    widths = [40, 22, 55, 68]
    pdf.table_header(headers, widths)
    rows = [
        ("NOME", "Sim", "Texto - nome completo do paciente", "MARIA DA SILVA SANTOS"),
        ("DATA_NASCIMENTO", "Sim", "Data no formato DD/MM/AAAA", "15/03/1985"),
        ("PROCEDIMENTO", "Sim", "Texto - nome do procedimento", "COLECISTECTOMIA"),
        ("TELEFONE1", "Sim", "Numero com DDD (10-11 digitos)", "85999887766"),
        ("TELEFONE2", "Nao", "Numero adicional (secundario)", "8533661234"),
        ("TELEFONE3", "Nao", "Numero adicional (terciario)", "85988776655"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Regras de processamento dos telefones")
    pdf.bold_bullet("Prioridade:", "TELEFONE1 tem prioridade 1 (principal), TELEFONE2 prioridade 2, etc.")
    pdf.bold_bullet("Validacao:", "O sistema verifica automaticamente se cada numero possui WhatsApp")
    pdf.bold_bullet("Formatacao:", "Numeros sao formatados para o padrao internacional (55 + DDD + numero)")
    pdf.bold_bullet("Multiplos:", "Cada paciente pode ter ate 3 telefones cadastrados")

    pdf.ln(2)
    pdf.section_title("Normalizacao de procedimentos")
    pdf.body_text(
        "O sistema utiliza inteligencia artificial para normalizar os nomes de "
        "procedimentos. Exemplo: 'COLECISTECT.' sera normalizado para "
        "'COLECISTECTOMIA'. O nome original e mantido para referencia."
    )

    pdf.note_box(
        "A coluna 'procedimento_normalizado' e preenchida automaticamente pelo sistema. "
        "Na tabela de contatos, o nome normalizado aparece em VERDE e o original em cinza abaixo."
    )

    # ══════════════════════════════════════════════════════════
    # 6. PROCESSAMENTO DA CAMPANHA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("6", "Processamento da Campanha")

    pdf.body_text(
        "Apos o upload da planilha, o sistema processa automaticamente os dados. "
        "Uma tela de progresso e exibida."
    )

    pdf.section_title("Tela de Progresso")
    pdf.body_text(
        "A tela mostra um cartao com cabecalho 'Processando Campanha' e icone de "
        "ampulheta (bi-hourglass-split). Elementos visiveis:"
    )
    pdf.bold_bullet("Barra de progresso:", "Barra verde animada com listras (striped) mostrando o percentual")
    pdf.bold_bullet("Texto de status:", "Mensagem dinamica informando a etapa atual")
    pdf.bold_bullet("Detalhes:", "Texto complementar com informacoes adicionais")
    pdf.bold_bullet("Alerta:", "Aviso para nao fechar a pagina durante o processamento")
    pdf.bold_bullet("Log detalhado:", "Exibido apos o inicio, mostra cada etapa (ex: validacao de numeros)")

    pdf.ln(2)
    pdf.section_title("Etapas do processamento")
    pdf.bold_bullet("1. Leitura:", "O sistema le a planilha e extrai os dados")
    pdf.bold_bullet("2. Cadastro:", "Cria os registros de contatos e telefones no banco")
    pdf.bold_bullet("3. Normalizacao:", "IA normaliza os nomes dos procedimentos")
    pdf.bold_bullet("4. Validacao:", "Verifica quais numeros possuem WhatsApp")
    pdf.bold_bullet("5. Finalizacao:", "Atualiza estatisticas e marca como pronta")

    pdf.warning_box("Nao feche a pagina durante o processamento. O tempo depende da quantidade de contatos.")

    # ══════════════════════════════════════════════════════════
    # 7. GERENCIANDO CONTATOS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("7", "Gerenciando Contatos")

    pdf.body_text(
        "Apos o processamento, voce pode visualizar e gerenciar os contatos de "
        "cada campanha. A tela de campanha apresenta os dados organizados em "
        "cartoes de estatisticas e uma tabela de contatos."
    )

    pdf.section_title("Cartoes de Estatisticas da Campanha")

    headers = ["Cartao", "Cor do numero", "Descricao"]
    widths = [40, 35, 110]
    pdf.table_header(headers, widths)
    rows = [
        ("Total de Contatos", "Padrao", "Total de pacientes importados na campanha"),
        ("Enviados", "Azul (text-info)", "Mensagens enviadas com sucesso"),
        ("Confirmados", "Verde (text-success)", "Pacientes que confirmaram interesse"),
        ("Rejeitados", "Amarelo (text-warning)", "Pacientes que rejeitaram"),
        ("Erros", "Vermelho (text-danger)", "Envios que falharam"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Barra de Agendamento e Controle")
    pdf.body_text("Cartao com icone bi-calendar-check que mostra:")
    pdf.bold_bullet("Meta Diaria:", "Quantidade de envios programados por dia")
    pdf.bold_bullet("Enviados Hoje:", "Quantidade ja enviada hoje + barra de progresso")
    pdf.bold_bullet("Horario:", "Janela de envio (ex: 08:00 - 17:00)")
    pdf.bold_bullet("Duracao:", "Dias restantes da campanha")

    pdf.ln(2)
    pdf.section_title("Barra de Progresso do Envio")
    pdf.body_text(
        "Mostra o percentual de envio geral da campanha com barra azul (bg-primary). "
        "Abaixo, exibe o status da campanha e a taxa de confirmacao em verde."
    )

    pdf.ln(2)
    pdf.section_title("Tabela de Contatos - Colunas")

    headers = ["Coluna", "Descricao", "Detalhes"]
    widths = [30, 55, 100]
    pdf.table_header(headers, widths)
    rows = [
        ("Nome", "Nome do paciente", "Em negrito. Pode ter badges: chat (azul), urgente (vermelho), insatisfeito (amarelo)"),
        ("Telefone", "Numero formatado", "Telefone principal do contato"),
        ("Procedimento", "Nome do procedimento", "Normalizado em verde/negrito + original em cinza"),
        ("Status", "Estado atual", "Badge colorido (ver secao 8 para detalhes)"),
        ("Resposta", "Texto da resposta", "Resposta do paciente (truncada em 30 caracteres)"),
        ("Data Envio", "Data/hora do envio", "Formato: dd/mm hh:mm"),
        ("Acoes", "Botoes de acao", "Ver detalhes, confirmar, rejeitar, reenviar"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Filtros da Tabela de Contatos")
    pdf.body_text("No topo da tabela existe um grupo de botoes para filtrar:")

    headers = ["Filtro", "Cor do botao", "O que mostra"]
    widths = [35, 40, 110]
    pdf.table_header(headers, widths)
    rows = [
        ("Todos", "Cinza (outline-secondary)", "Todos os contatos sem filtro"),
        ("Confirmados", "Verde (outline-success)", "Apenas contatos que confirmaram"),
        ("Rejeitados", "Amarelo (outline-warning)", "Apenas contatos que rejeitaram"),
        ("Aguardando", "Azul claro (outline-info)", "Contatos aguardando resposta"),
        ("Pendentes", "Cinza (outline-secondary)", "Contatos ainda nao enviados"),
        ("Erros", "Vermelho (outline-danger)", "Contatos com erro de envio"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════════════
    # 8. STATUS DOS CONTATOS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("8", "Status dos Contatos - Cores e Significados")

    pdf.body_text(
        "Cada contato possui um status representado por um badge (etiqueta colorida). "
        "Os status e suas cores indicam em qual etapa do fluxo o contato se encontra."
    )

    pdf.section_title("Tabela completa de status")

    headers = ["Status", "Badge (Cor)", "Texto exibido", "Significado"]
    widths = [32, 32, 35, 86]
    pdf.table_header(headers, widths)
    rows = [
        ("pendente", "Cinza (bg-secondary)", "Pendente", "Importado, aguardando validacao e processamento"),
        ("pronto_envio", "Azul (bg-primary)", "Pronto para envio", "Numero validado como WhatsApp, aguarda envio"),
        ("aguard_nasc", "Amarelo (bg-warning)", "Aguard. Aniversario", "Data de nascimento futura, aguarda data"),
        ("enviado", "Ciano (bg-info)", "Aguardando resposta", "Mensagem enviada, aguardando paciente responder"),
        ("aguard_motivo", "Amarelo (bg-warning)", "Aguardando motivo", "Paciente disse NAO, aguardando motivo"),
        ("concluido OK", "Verde (bg-success)", "CONFIRMADO", "Paciente confirmou interesse na cirurgia"),
        ("concluido NO", "Amarelo (bg-warning)", "REJEITADO", "Paciente rejeitou e informou motivo"),
        ("sem_resposta", "Cinza (bg-secondary)", "Sem resposta", "Todas as tentativas esgotadas sem resposta"),
        ("erro", "Vermelho (bg-danger)", "Erro: [motivo]", "Falha no envio (numero invalido, API, etc.)"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(4)
    pdf.section_title("Diagrama do fluxo de status")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(40, 40, 40)

    flow_text = (
        "  PENDENTE (cinza)\n"
        "      |\n"
        "      v\n"
        "  PRONTO_ENVIO (azul)\n"
        "      |\n"
        "      v\n"
        "  ENVIADO (ciano) -----> Paciente responde \"1\" SIM\n"
        "      |                        |\n"
        "      |                        v\n"
        "      |                  CONCLUIDO - CONFIRMADO (verde)\n"
        "      |\n"
        "      +---> Paciente responde \"2\" NAO\n"
        "      |           |\n"
        "      |           v\n"
        "      |     AGUARDANDO_MOTIVO (amarelo)\n"
        "      |           |\n"
        "      |           v\n"
        "      |     CONCLUIDO - REJEITADO (amarelo)\n"
        "      |\n"
        "      +---> Paciente responde \"3\" DESCONHECO\n"
        "      |           |\n"
        "      |           v\n"
        "      |     Marca telefone como \"nao pertence\"\n"
        "      |     (se todos: CONCLUIDO - REJEITADO)\n"
        "      |\n"
        "      +---> Sem resposta (apos retentativas)\n"
        "                 |\n"
        "                 v\n"
        "           SEM_RESPOSTA (cinza)"
    )
    pdf.multi_cell(0, 4.5, flow_text)

    # ══════════════════════════════════════════════════════════
    # 9. FLUXO DE MENSAGENS AUTOMATICAS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("9", "Fluxo de Mensagens Automaticas")

    pdf.body_text(
        "O sistema envia mensagens automaticas via WhatsApp seguindo um fluxo "
        "pre-definido com retentativas em caso de nao resposta."
    )

    pdf.section_title("Mensagem Inicial (MSG 0)")
    pdf.body_text("Enviada ao primeiro contato com o paciente:")
    pdf.set_font("Courier", "", 8)
    pdf.set_text_color(40, 80, 40)
    pdf.set_fill_color(245, 255, 245)
    msg1 = (
        '  "Ola, {nome}!\n'
        '   Aqui e da Central de Agendamentos do\n'
        '   Hospital Universitario Walter Cantidio.\n'
        '   Consta em nossos registros que voce esta na\n'
        '   lista de espera para: {procedimento}.\n'
        '   Voce ainda tem interesse?\n'
        '   1 - SIM - Tenho interesse\n'
        '   2 - NAO - Nao tenho mais interesse\n'
        '   3 - DESCONHECO - Nao sou essa pessoa"'
    )
    pdf.multi_cell(0, 4.5, msg1, fill=True)
    pdf.ln(3)

    pdf.section_title("Retentativa 1 (apos 24h sem resposta)")
    pdf.body_text(
        "Se o paciente nao responder em 24h, o sistema envia automaticamente "
        "uma segunda mensagem mais enfatica, alertando que a vaga sera "
        "disponibilizada em 2 dias."
    )

    pdf.section_title("Retentativa 2 - Ultima Tentativa (apos mais 48h)")
    pdf.body_text(
        "Se ainda nao houver resposta, o sistema envia a ULTIMA tentativa com "
        "tom de urgencia, informando que a vaga sera disponibilizada automaticamente."
    )

    pdf.section_title("Mensagem de Encerramento (sem resposta)")
    pdf.body_text(
        "Se mesmo apos todas as tentativas nao houver resposta, o sistema envia "
        "uma mensagem final informando que a vaga foi disponibilizada e fornecendo "
        "o telefone (85) 3366-8000 para contato."
    )

    pdf.note_box(
        "Todas as mensagens sao enviadas apenas dentro do horario configurado "
        "(padrao: 8h as 17h). Fora deste horario, os envios sao pausados automaticamente."
    )

    # ══════════════════════════════════════════════════════════
    # 10. RESPOSTAS DO PACIENTE
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("10", "Respostas do Paciente")

    pdf.body_text(
        "O sistema reconhece automaticamente as respostas dos pacientes. "
        "Abaixo estao todas as variantes aceitas para cada opcao."
    )

    pdf.section_title("Respostas reconhecidas como SIM (Confirma)")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(0, 120, 0)
    pdf.multi_cell(0, 5, '  "1", "SIM", "S", "CONFIRMO", "CONFIRMADO",\n  "TENHO INTERESSE", "ACEITO", "OK", "1 SIM", "1SIM", "SIM 1", "SIM1"')
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.body_text("Ao confirmar, o paciente recebe a mensagem de confirmacao com os proximos passos.")

    pdf.section_title("Respostas reconhecidas como NAO (Rejeita)")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(200, 100, 0)
    pdf.multi_cell(0, 5, '  "2", "NAO", "N", "NAO QUERO", "NAO TENHO INTERESSE",\n  "2 NAO", "2NAO", "NAO 2", "NAO2"')
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.body_text(
        "Ao rejeitar, o sistema solicita o MOTIVO da rejeicao com as seguintes opcoes:"
    )

    headers = ["Opcao", "Motivo"]
    widths = [25, 160]
    pdf.table_header(headers, widths)
    rows = [
        ("1", "Ja realizei em outro hospital"),
        ("2", "Problemas de saude / Nao tenho condicoes"),
        ("3", "Nao quero mais a cirurgia"),
        ("4", "Outro motivo"),
        ("Texto", "O paciente pode digitar livremente o motivo (max 200 caracteres)"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Respostas reconhecidas como DESCONHECO")
    pdf.set_font("Courier", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.multi_cell(0, 5, '  "3", "DESCONHECO", "NAO SOU", "ENGANO",\n  "NUMERO ERRADO", "3 DESCONHECO"')
    pdf.ln(2)

    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(40, 40, 40)
    pdf.body_text(
        "Quando um numero responde DESCONHECO, o telefone e marcado como "
        "'nao pertence ao paciente'. Se TODOS os telefones de um contato "
        "responderem DESCONHECO, o contato e marcado como REJEITADO com motivo "
        "'Paciente nao localizado'."
    )

    pdf.warning_box(
        "Respostas invalidas (fora das opcoes) recebem uma mensagem de ajuda "
        "pedindo que o paciente responda com 1, 2 ou 3."
    )

    # ══════════════════════════════════════════════════════════
    # 11. ACOES MANUAIS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("11", "Acoes Manuais sobre Contatos")

    pdf.body_text(
        "Alem do fluxo automatico, voce pode realizar acoes manuais sobre os "
        "contatos diretamente pela tabela de contatos da campanha."
    )

    pdf.section_title("Botoes de acao na coluna 'Acoes'")

    headers = ["Botao/Icone", "Cor", "Acao", "Quando aparece"]
    widths = [35, 35, 45, 70]
    pdf.table_header(headers, widths)
    rows = [
        ("bi-info-circle", "Azul (outline-info)", "Ver detalhes", "Sempre visivel para todos os contatos"),
        ("bi-check-lg", "Verde (outline-success)", "Confirmar", "Quando nao esta confirmado nem rejeitado"),
        ("bi-x-lg", "Amarelo (outline-warning)", "Rejeitar", "Quando nao esta confirmado nem rejeitado"),
        ("bi-arrow-clockwise", "Azul (outline-primary)", "Reenviar", "Quando status e enviado, aguardando, concluido ou com erro"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Botoes da campanha (cabecalho)")

    headers = ["Botao", "Icone", "Cor", "Funcao"]
    widths = [35, 35, 35, 80]
    pdf.table_header(headers, widths)
    rows = [
        ("Iniciar Envio", "bi-play-fill", "Verde WhatsApp", "Inicia o envio das mensagens da campanha"),
        ("Pausar", "bi-pause-fill", "Amarelo (warning)", "Pausa temporariamente o envio"),
        ("Exportar Excel", "bi-download", "Verde (success)", "Exporta dados da campanha"),
        ("Excluir", "bi-trash", "Vermelho (danger)", "Remove a campanha (menu dropdown)"),
        ("Cancelar", "bi-x-circle", "Vermelho (danger)", "Cancela campanha em andamento (menu dropdown)"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Pagina de Detalhes do Contato")
    pdf.body_text("Ao clicar em 'Ver detalhes' (bi-info-circle), a pagina mostra:")

    pdf.bold_bullet("Cartao de informacoes:", "Nome, status (badge colorido), procedimento, data de nascimento, erro (se houver)")
    pdf.bold_bullet("Cartao de telefones:", "Lista de todos os telefones com validacao WhatsApp, badges de resposta")
    pdf.bold_bullet("Botoes rapidos:", "'Editar Contato' (bi-pencil-square) e 'Imprimir' (bi-printer)")
    pdf.bold_bullet("Chat:", "Historico completo de mensagens trocadas com o paciente")

    # ══════════════════════════════════════════════════════════
    # 12. CHAT
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("12", "Chat / Historico de Mensagens")

    pdf.body_text(
        "A pagina de detalhes do contato inclui um painel de chat que mostra "
        "todo o historico de mensagens trocadas com o paciente."
    )

    pdf.section_title("Elementos do chat")
    pdf.bold_bullet("Cabecalho:", "Fundo roxo/azul degradado com icone bi-chat-dots-fill e badge com contagem de mensagens")
    pdf.bold_bullet("Area de mensagens:", "Fundo texturizado (estilo WhatsApp), rolavel, altura de 600px")
    pdf.bold_bullet("Mensagens enviadas:", "Baloes verdes (#dcf8c6) alinhados a direita")
    pdf.bold_bullet("Mensagens recebidas:", "Baloes brancos alinhados a esquerda")
    pdf.bold_bullet("Timestamps:", "Data/hora no formato dd/mm/aaaa hh:mm:ss com icone bi-clock")
    pdf.bold_bullet("Estado vazio:", "Icone bi-chat-text grande com texto 'Nenhuma mensagem ainda'")

    pdf.ln(2)
    pdf.section_title("Enviando mensagem manual")
    pdf.body_text(
        "Na parte inferior do chat, existe um formulario para envio manual:"
    )
    pdf.bold_bullet("Seletor de telefone:", "Dropdown para escolher qual numero enviar (apenas WhatsApp validos)")
    pdf.bold_bullet("Campo de texto:", "Campo para digitar a mensagem")
    pdf.bold_bullet("Botao enviar:", "Botao azul com icone bi-send-fill")

    pdf.note_box("Os numeros com WhatsApp valido sao marcados com uma estrela no dropdown.")

    # ══════════════════════════════════════════════════════════
    # 13. EXPORTACAO DE DADOS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("13", "Exportacao de Dados para Excel")

    pdf.body_text(
        "O sistema permite exportar os dados das campanhas para planilhas Excel. "
        "A exportacao e acessada pelo botao 'Exportar Excel' (icone bi-file-earmark-excel) "
        "no dashboard."
    )

    pdf.section_title("Modal de Exportacao")
    pdf.body_text(
        "Ao clicar, abre um modal (janela sobreposta) com cabecalho verde e "
        "titulo 'Exportar Dados para Excel'."
    )

    pdf.section_title("Passo 1: Selecionar o modo")
    pdf.body_text(
        "No cartao 'Modo de Exportacao' (cabecalho azul, icone bi-toggles), "
        "selecione 'Modo Fila' clicando no botao de radio correspondente. "
        "O icone e bi-people-fill (escuro) e o subtitulo e '(Busca Ativa)'."
    )

    pdf.section_title("Passo 2: Configurar filtros do Modo Fila")

    headers = ["Filtro", "Tipo", "Opcoes"]
    widths = [40, 30, 115]
    pdf.table_header(headers, widths)
    rows = [
        ("Status", "Checkboxes", "Aguardando, Enviado, Confirmado (verde), Rejeitado (vermelho), Erro (amarelo)"),
        ("Procedimento", "Texto", "Filtrar por nome do procedimento (ex: Cirurgia)"),
        ("Usuario", "Dropdown", "Filtrar por usuario que criou a campanha"),
        ("Data Inicio", "Data", "Data inicial do periodo a exportar"),
        ("Data Fim", "Data", "Data final do periodo a exportar"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(2)
    pdf.body_text(
        "No topo da secao de status, existem dois botoes uteis: 'Todos' "
        "(seleciona todos os checkboxes) e 'Nenhum' (desmarca todos)."
    )

    pdf.section_title("Passo 3: Exportar")
    pdf.body_text(
        "Clique no botao verde 'Exportar para Excel' (icone bi-download). "
        "O botao mostrara um spinner com 'Gerando arquivo...' durante o processamento. "
        "O arquivo sera baixado automaticamente."
    )

    pdf.note_box(
        "Modo Fila: Exporta dados das campanhas de Busca Ativa (fila cirurgica). "
        "A informacao aparece em um alerta azul no modal."
    )

    # ══════════════════════════════════════════════════════════
    # 14. GRAFICOS E RELATORIOS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("14", "Graficos e Relatorios")

    pdf.body_text(
        "O dashboard do Modo Fila exibe graficos interativos para acompanhamento "
        "das campanhas de busca ativa."
    )

    pdf.section_title("Grafico de Atividade dos Ultimos 30 Dias")
    pdf.body_text(
        "Cartao com cabecalho 'Atividade dos Ultimos 30 Dias', icone bi-graph-up "
        "e badge escuro (bg-dark). Exibe um grafico de linhas com 3 series:"
    )
    pdf.bold_bullet("Mensagens Enviadas:", "Linha mostrando o volume de envios diarios")
    pdf.bold_bullet("Confirmados:", "Linha verde mostrando confirmacoes por dia")
    pdf.bold_bullet("Rejeitados:", "Linha mostrando rejeicoes por dia")

    pdf.ln(2)
    pdf.section_title("Grafico de Distribuicao de Status")
    pdf.body_text(
        "Cartao com cabecalho 'Distribuicao de Status', icone bi-pie-chart. "
        "Exibe um grafico tipo rosca (Doughnut) com as seguintes cores por status:"
    )

    headers = ["Status", "Cor no grafico", "Codigo da cor"]
    widths = [50, 65, 70]
    pdf.table_header(headers, widths)
    rows = [
        ("Pendente", "Cinza", "#6c757d"),
        ("Validando", "Ciano", "#0dcaf0"),
        ("Pronto para envio", "Azul", "#0d6efd"),
        ("Enviado", "Laranja", "#fd7e14"),
        ("Aguardando nascimento", "Amarelo", "#ffc107"),
        ("Concluido", "Verde", "#198754"),
        ("Erro", "Vermelho", "#dc3545"),
        ("Sem WhatsApp", "Cinza claro", "#adb5bd"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    pdf.ln(3)
    pdf.section_title("Tabela de Mensagens por Usuario (Fila)")
    pdf.body_text(
        "Cartao com cabecalho escuro (bg-dark) e icone bi-person-badge. "
        "Tabela rolavel (max 300px) com cabecalho fixo exibindo:"
    )

    headers = ["Coluna", "Badge", "Descricao"]
    widths = [40, 40, 105]
    pdf.table_header(headers, widths)
    rows = [
        ("Usuario", "-", "Nome do usuario que criou a campanha"),
        ("Enviadas", "bg-info (azul)", "Total de mensagens enviadas pelo usuario"),
        ("Recebidas", "bg-secondary (cinza)", "Total de respostas recebidas"),
        ("Total", "Negrito", "Soma de enviadas + recebidas"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════════════
    # 15. DICAS E BOAS PRATICAS
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("15", "Dicas e Boas Praticas")

    pdf.section_title("Preparacao da planilha")
    pdf.bold_bullet("Formato:", "Use sempre arquivos .xlsx (Excel)")
    pdf.bold_bullet("Nomes das colunas:", "Respeite exatamente os nomes: NOME, DATA_NASCIMENTO, PROCEDIMENTO, TELEFONE1, etc.")
    pdf.bold_bullet("Telefones:", "Inclua DDD + numero (10 ou 11 digitos). Evite espacos, tracos ou parenteses")
    pdf.bold_bullet("Data de nascimento:", "Use o formato DD/MM/AAAA. Este campo e obrigatorio")
    pdf.bold_bullet("Multiplos telefones:", "Preencha TELEFONE2 e TELEFONE3 quando disponiveis para aumentar as chances de contato")

    pdf.ln(3)
    pdf.section_title("Configuracao da campanha")
    pdf.bold_bullet("Meta diaria:", "Ajuste conforme a capacidade de atendimento. Muitos envios por dia podem sobrecarregar o atendimento")
    pdf.bold_bullet("Horario:", "Configure dentro do horario comercial (8h-17h) para maximizar respostas")
    pdf.bold_bullet("Tempo entre envios:", "Um intervalo adequado evita bloqueios da API do WhatsApp")

    pdf.ln(3)
    pdf.section_title("Acompanhamento")
    pdf.bold_bullet("Monitore diariamente:", "Verifique o dashboard para acompanhar confirmacoes e rejeicoes")
    pdf.bold_bullet("Trate erros:", "Contatos com erro podem ser reenviados usando o botao de reenvio")
    pdf.bold_bullet("Exporte periodicamente:", "Use a exportacao Excel para gerar relatorios para a gestao")
    pdf.bold_bullet("Filtros:", "Use os filtros na tabela de contatos para focar nos status que precisam de atencao")

    pdf.ln(3)
    pdf.section_title("Interpretacao dos resultados")
    pdf.bold_bullet("Taxa de confirmacao:", "Acompanhe no cartao comparativo e na barra de progresso")
    pdf.bold_bullet("Motivos de rejeicao:", "Analise os motivos mais frequentes para melhoria do servico")
    pdf.bold_bullet("Pacientes nao localizados:", "Quando todos os telefones respondem DESCONHECO, o paciente nao foi encontrado")

    pdf.warning_box(
        "Nunca exclua uma campanha em andamento. Use o botao 'Pausar' para "
        "interromper temporariamente e 'Cancelar' apenas quando necessario."
    )

    # ══════════════════════════════════════════════════════════
    # PAGINA FINAL - ICONES
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.chapter_title("", "Referencia Rapida de Icones")

    pdf.body_text(
        "Tabela de referencia com todos os icones Bootstrap usados no Modo Cirurgia "
        "e seus significados no sistema."
    )

    headers = ["Icone (classe)", "Onde aparece", "Significado"]
    widths = [50, 55, 80]
    pdf.table_header(headers, widths)
    rows = [
        ("bi-people-fill", "Seletor de modo", "Modo Fila / Busca Ativa"),
        ("bi-calendar-check", "Seletor de modo", "Modo Consulta / Agendamento"),
        ("bi-grid", "Seletor de modo", "Visualizar todos os modos"),
        ("bi-arrow-clockwise", "Seletor / Acoes", "Atualizar / Reenviar"),
        ("bi-file-earmark-excel", "Dashboard", "Exportar para Excel"),
        ("bi-play-fill", "Campanha", "Iniciar envio"),
        ("bi-pause-fill", "Campanha", "Pausar envio"),
        ("bi-download", "Campanha", "Exportar dados"),
        ("bi-trash", "Campanha (dropdown)", "Excluir campanha"),
        ("bi-x-circle", "Campanha (dropdown)", "Cancelar campanha"),
        ("bi-info-circle", "Tabela de contatos", "Ver detalhes do contato"),
        ("bi-check-lg", "Tabela de contatos", "Confirmar manualmente"),
        ("bi-x-lg", "Tabela de contatos", "Rejeitar manualmente"),
        ("bi-person-fill", "Detalhes do contato", "Avatar do paciente"),
        ("bi-telephone-fill", "Detalhes do contato", "Secao de telefones"),
        ("bi-whatsapp", "Detalhes do contato", "WhatsApp valido (verde)"),
        ("bi-x-circle (vermelho)", "Detalhes do contato", "Numero invalido"),
        ("bi-chat-dots-fill", "Chat", "Cabecalho do historico"),
        ("bi-send-fill", "Chat", "Enviar mensagem manual"),
        ("bi-clock", "Chat / Tabela", "Data/hora do evento"),
        ("bi-pencil-square", "Detalhes do contato", "Editar contato"),
        ("bi-printer", "Detalhes do contato", "Imprimir dados"),
        ("bi-exclamation-triangle", "Dashboard / Detalhes", "Alerta de erro"),
        ("bi-hourglass-split", "Processamento", "Processando campanha"),
        ("bi-graph-up", "Dashboard", "Grafico de atividade"),
        ("bi-pie-chart", "Dashboard", "Distribuicao de status"),
        ("bi-person-badge", "Dashboard", "Mensagens por usuario"),
        ("bi-toggles", "Modal exportacao", "Seletor de modo"),
        ("bi-funnel", "Modal exportacao", "Filtros adicionais"),
        ("bi-shield-lock", "Header", "Painel administrativo"),
        ("bi-house-door", "Breadcrumb", "Voltar ao dashboard"),
        ("bi-megaphone", "Breadcrumb", "Campanha"),
    ]
    for i, r in enumerate(rows):
        pdf.table_row(list(r), widths, fill=(i % 2 == 0))

    # ══════════════════════════════════════════════════════════
    # CONTRACAPA
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    pdf.ln(60)
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(25, 60, 120)
    pdf.cell(0, 12, "Hospital Universitario Walter Cantidio", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(5)
    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(80, 80, 80)
    pdf.cell(0, 8, "Sistema de Busca Ativa via WhatsApp", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 8, "Guia do Usuario - Modo Cirurgia", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.ln(10)
    pdf.set_draw_color(25, 60, 120)
    pdf.line(70, pdf.get_y(), 140, pdf.get_y())

    pdf.ln(10)
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 7, "Telefone: (85) 3366-8000", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, f"Documento gerado em: {datetime.now().strftime('%d/%m/%Y %H:%M')}", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 7, "Gerado automaticamente a partir do codigo-fonte do sistema", align="C", new_x="LMARGIN", new_y="NEXT")

    # ── Salvar ──────────────────────────────────────────────
    output_path = "/home/user/git3/GUIA_MODO_CIRURGIA_USUARIO.pdf"
    pdf.output(output_path)
    print(f"PDF gerado com sucesso: {output_path}")
    return output_path


if __name__ == "__main__":
    build_pdf()
