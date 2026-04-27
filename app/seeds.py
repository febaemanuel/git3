"""Seed data + admin bootstrap (criar_admin, criar_faqs_padrao,
criar_tutoriais_padrao).

Run from the application factory once the DB is reachable.
"""

import json
import logging
from datetime import datetime

from sqlalchemy.exc import IntegrityError

from app.extensions import db
from app.models import RespostaAutomatica, Tutorial, Usuario


logger = logging.getLogger(__name__)


ADMIN_EMAIL = 'admin@huwc.com'
ADMIN_SENHA = 'admin123'
ADMIN_NOME = 'Administrador'


def criar_faqs_padrao():
    """Cria FAQs padrão se não existirem"""
    try:
        if RespostaAutomatica.query.count() > 0:
            return

        faqs_padrao = [
            {
                'categoria': 'horario',
                'gatilhos': ['horário', 'horario', 'que horas', 'hora', 'quando'],
                'resposta': '📋 O agendamento será feito após sua confirmação. A equipe entrará em contato para definir data e horário.',
                'prioridade': 5
            },
            {
                'categoria': 'endereco',
                'gatilhos': ['endereço', 'endereco', 'onde fica', 'localização', 'local', 'chegar'],
                'resposta': '📍 *Hospital Universitário Walter Cantídio*\nRua Capitão Francisco Pedro, 1290 - Rodolfo Teófilo\nFortaleza - CE\nCEP: 60430-370',
                'prioridade': 5
            },
            {
                'categoria': 'documento',
                'gatilhos': ['documento', 'levar', 'precisar', 'necessário', 'necessario', 'precisa levar'],
                'resposta': '📄 *Documentos necessários:*\n• RG e CPF\n• Cartão do SUS\n• Encaminhamento médico\n• Exames anteriores (se houver)',
                'prioridade': 4
            },
            {
                'categoria': 'preparo',
                'gatilhos': ['jejum', 'preparo', 'preparar', 'antes da cirurgia', 'cuidados'],
                'resposta': '🏥 As orientações de preparo serão fornecidas pela equipe médica no momento do agendamento. Cada procedimento tem suas especificidades.',
                'prioridade': 3
            },
            {
                'categoria': 'acompanhante',
                'gatilhos': ['acompanhante', 'acompanhar', 'pode ir com', 'levar alguém', 'levar alguem'],
                'resposta': '👥 Sim, você pode e deve trazer um acompanhante maior de 18 anos. O acompanhante é essencial para o pós-operatório.',
                'prioridade': 3
            },
            {
                'categoria': 'agendamento',
                'gatilhos': ['prazo', 'quanto tempo', 'demora', 'demorar', 'tempo de espera'],
                'resposta': '⏱️ O prazo para contato varia conforme a fila de espera. Nossa equipe priorizará seu atendimento após sua confirmação.',
                'prioridade': 4
            },
            {
                'categoria': 'cancelamento',
                'gatilhos': ['cancelar', 'desmarcar', 'não posso', 'nao posso', 'remarcar'],
                'resposta': '📞 Para cancelar ou remarcar, entre em contato pelo telefone (85) 3366-8000 ou responda esta mensagem informando sua situação.',
                'prioridade': 5
            },
            {
                'categoria': 'convenio',
                'gatilhos': ['plano', 'convênio', 'convenio', 'particular', 'sus', 'pagar'],
                'resposta': '🏥 O Hospital Universitário Walter Cantídio atende pelo SUS (Sistema Único de Saúde). O atendimento é gratuito.',
                'prioridade': 4
            },
            {
                'categoria': 'resultado_exames',
                'gatilhos': ['resultado', 'exame', 'laudo', 'buscar resultado'],
                'resposta': '📋 Resultados de exames podem ser retirados na recepção do hospital com documento de identidade.',
                'prioridade': 3
            },
            {
                'categoria': 'telefone',
                'gatilhos': ['contato', 'falar', 'ligar', 'telefone', 'telefone hospital'],
                'resposta': '📱 *Telefones do HUWC:*\n• Central: (85) 3366-8000\n• Agendamento: (85) 3366-8001\n• Horário: Segunda a Sexta, 7h às 18h',
                'prioridade': 5
            },
            {
                'categoria': 'pos_operatorio',
                'gatilhos': ['depois', 'pós', 'pos', 'recuperação', 'recuperacao', 'repouso'],
                'resposta': '🏠 As orientações de pós-operatório serão fornecidas pela equipe médica. Geralmente inclui repouso, cuidados com a ferida e retorno ambulatorial.',
                'prioridade': 3
            },
            {
                'categoria': 'medicacao',
                'gatilhos': ['remédio', 'remedio', 'medicamento', 'comprar', 'farmácia', 'farmacia'],
                'resposta': '💊 As medicações necessárias serão prescritas pelo médico. Algumas são fornecidas pelo hospital, outras podem precisar ser adquiridas.',
                'prioridade': 3
            },
            {
                'categoria': 'estacionamento',
                'gatilhos': ['estacionar', 'carro', 'vaga', 'estacionamento', 'onde parar'],
                'resposta': '🚗 O hospital possui estacionamento próprio. Há também estacionamento rotativo nas ruas próximas.',
                'prioridade': 2
            },
            {
                'categoria': 'alimentacao',
                'gatilhos': ['comer', 'beber', 'alimento', 'café', 'lanche', 'alimentar'],
                'resposta': '🍽️ As orientações sobre alimentação pré-operatória serão passadas pela equipe. Geralmente é necessário jejum antes de cirurgias.',
                'prioridade': 3
            },
            {
                'categoria': 'covid',
                'gatilhos': ['covid', 'máscara', 'mascara', 'teste', 'vacina', 'coronavirus'],
                'resposta': '😷 *Protocolos COVID-19:*\n• Uso de máscara obrigatório\n• Evite aglomerações\n• Higienize as mãos\n• Um acompanhante por paciente',
                'prioridade': 4
            },
            {
                'categoria': 'transporte',
                'gatilhos': ['transporte', 'ônibus', 'onibus', 'como chegar', 'uber'],
                'resposta': '🚌 *Como chegar:*\n• Ônibus: Linhas 051, 072, 073\n• Endereço para apps: Rua Cap. Francisco Pedro, 1290\n• Hospital fica próximo à Av. da Universidade',
                'prioridade': 2
            }
        ]

        for faq_data in faqs_padrao:
            faq = RespostaAutomatica(
                categoria=faq_data['categoria'],
                resposta=faq_data['resposta'],
                prioridade=faq_data['prioridade'],
                global_faq=True,  # FAQs padrão são globais (todos veem)
                criador_id=None  # FAQs globais não tem criador
            )
            faq.set_gatilhos(faq_data['gatilhos'])
            db.session.add(faq)

        db.session.commit()
        logger.info("FAQs padrão globais criadas")

    except Exception as e:
        logger.error(f"Erro ao criar FAQs padrão: {e}")


def criar_tutoriais_padrao():
    """Cria tutoriais padrão se não existirem"""
    try:
        if Tutorial.query.count() > 0:
            return

        tutoriais = [
            {
                'titulo': 'Bem-vindo ao Sistema de Busca Ativa',
                'categoria': 'inicio',
                'ordem': 1,
                'descricao': 'Introdução completa ao sistema',
                'conteudo': '''
<h4>🎯 Bem-vindo ao Sistema de Busca Ativa - HUWC</h4>
<p>Este sistema foi desenvolvido especialmente para gerenciar <strong>campanhas de busca ativa de pacientes em lista de espera cirúrgica</strong>, automatizando o contato via WhatsApp e organizando o atendimento.</p>

<h5>📋 Principais funcionalidades:</h5>
<ul>
    <li>📊 <strong>Dashboard Executivo:</strong> Visão completa com estatísticas, gráficos e progresso em tempo real</li>
    <li>📋 <strong>Gestão de Campanhas:</strong> Criar, importar contatos via Excel, validar números e enviar mensagens automaticamente</li>
    <li>⏰ <strong>Agendamento Inteligente:</strong> Sistema de meta diária com cálculo automático de intervalos e controle de horários</li>
    <li>📞 <strong>Múltiplos Telefones:</strong> Suporte para vários números por paciente com validação individual</li>
    <li>🎂 <strong>Verificação de Nascimento:</strong> Aguarda aniversário antes de enviar (JIT - Just In Time)</li>
    <li>⚙️ <strong>Configurações:</strong> Integração com WhatsApp via Evolution API + sistema de follow-up automático</li>
    <li>👤 <strong>Atendimento Inteligente:</strong> Tickets automáticos para mensagens urgentes, com análise de sentimento</li>
    <li>💬 <strong>FAQ Automático:</strong> Respostas instantâneas para dúvidas frequentes com sistema de gatilhos</li>
    <li>📈 <strong>Relatórios Avançados:</strong> Gráficos interativos por campanha com exportação para Excel</li>
</ul>

<h5>🚀 Fluxo básico de uso:</h5>
<ol>
    <li><strong>Configure o WhatsApp</strong> nas Configurações (Evolution API + QR Code)</li>
    <li><strong>Crie FAQs automáticos</strong> para responder dúvidas comuns</li>
    <li><strong>Configure o follow-up</strong> para mensagens após envio inicial</li>
    <li><strong>Crie uma campanha</strong> importando planilha Excel com dados dos pacientes</li>
    <li><strong>Defina meta diária</strong> e horários de funcionamento (intervalo é calculado automaticamente!)</li>
    <li><strong>Valide números</strong> (opcional, mas recomendado para economizar tempo)</li>
    <li><strong>Inicie os envios</strong> e acompanhe em tempo real</li>
    <li><strong>Atenda tickets</strong> de dúvidas complexas no painel de atendimento</li>
    <li><strong>Analise relatórios</strong> com gráficos e estatísticas detalhadas</li>
</ol>

<div class="alert alert-success">
    <strong>💡 Dica Importante:</strong> O sistema utiliza <strong>validação JIT (Just In Time)</strong>, ou seja, só valida números quando realmente necessário, evitando validar 3000+ números de uma vez e sobrecarregar a API!
</div>

<div class="alert alert-info">
    <strong>🎯 Começando:</strong> Siga a ordem dos tutoriais para entender completamente cada funcionalidade. Tempo estimado: 15-20 minutos.
</div>
                '''
            },
            {
                'titulo': 'Como Criar uma Campanha',
                'categoria': 'campanhas',
                'ordem': 2,
                'descricao': 'Guia completo de criação e configuração',
                'conteudo': '''
<h4>📋 Criando sua primeira campanha</h4>

<h5>📊 Passo 1: Preparar a planilha Excel</h5>
<p>A planilha deve estar no formato <strong>.xlsx ou .xls</strong> com as seguintes colunas:</p>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Coluna</th>
            <th>Obrigatório?</th>
            <th>Formato</th>
            <th>Exemplo</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Nome</strong> ou <strong>Usuario</strong></td>
            <td>✅ Sim</td>
            <td>Texto</td>
            <td>João Silva</td>
        </tr>
        <tr>
            <td><strong>Telefone</strong></td>
            <td>✅ Sim</td>
            <td>Número com DDD (11 dígitos)</td>
            <td>85992231683</td>
        </tr>
        <tr>
            <td><strong>Nascimento</strong></td>
            <td>❌ Opcional</td>
            <td>DD/MM/AAAA ou AAAA-MM-DD</td>
            <td>15/08/1985</td>
        </tr>
        <tr>
            <td><strong>Procedimento</strong></td>
            <td>❌ Opcional</td>
            <td>Texto</td>
            <td>Cirurgia de Catarata</td>
        </tr>
    </tbody>
</table>

<div class="alert alert-info">
    <strong>💡 Múltiplos telefones:</strong> Você pode adicionar várias linhas para a mesma pessoa! O sistema agrupa automaticamente por nome e permite até 5 telefones por paciente.
</div>

<h5>➕ Passo 2: Criar a campanha no Dashboard</h5>
<ol>
    <li>Clique no botão <strong>"Nova Campanha"</strong> no Dashboard</li>
    <li>Preencha:
        <ul>
            <li><strong>Nome da Campanha:</strong> Ex: "Busca Ativa Novembro 2024"</li>
            <li><strong>Descrição:</strong> Opcional, para referência interna</li>
            <li><strong>Mensagem:</strong> Personalize usando variáveis:
                <ul>
                    <li><code>{nome}</code> - Nome do paciente</li>
                    <li><code>{procedimento}</code> - Procedimento cadastrado</li>
                </ul>
            </li>
        </ul>
    </li>
    <li>Faça <strong>upload da planilha Excel</strong></li>
</ol>

<h5>⏰ Passo 3: Configurar Agendamento Inteligente</h5>
<p>O sistema calcula <strong>automaticamente</strong> o intervalo ideal entre envios!</p>
<ul>
    <li><strong>Meta Diária:</strong> Quantas mensagens enviar por dia (ex: 50)</li>
    <li><strong>Horário Início:</strong> Quando começar os envios (ex: 08:00)</li>
    <li><strong>Horário Fim:</strong> Quando parar os envios (ex: 18:00)</li>
    <li><strong>Duração:</strong> Quantos dias a campanha vai durar (0 = até acabar)</li>
</ul>

<div class="alert alert-success">
    <strong>✨ Exemplo de cálculo:</strong><br>
    Meta: 50 mensagens/dia | Horário: 08:00 às 18:00 (10 horas)<br>
    <strong>Intervalo calculado:</strong> 1 envio a cada 12 minutos automaticamente!
</div>

<p>O sistema respeita os <strong>dias da semana</strong> configurados e <strong>não envia em finais de semana</strong> se desabilitado.</p>

<h5>✅ Passo 4: Validar números (Opcional mas recomendado)</h5>
<p>Após criar a campanha, clique em <strong>"Validar Números"</strong> para:</p>
<ul>
    <li>✅ Verificar quais números têm WhatsApp ativo</li>
    <li>❌ Marcar números inválidos automaticamente</li>
    <li>⏱️ Economizar tempo não enviando para números inexistentes</li>
</ul>

<div class="alert alert-warning">
    <strong>⚡ Validação JIT (Just In Time):</strong> O sistema valida apenas os números que ainda não foram validados. Se você tem 3000 contatos, ele valida em lotes conforme necessário, evitando sobrecarga da API!
</div>

<h5>🚀 Passo 5: Iniciar envios</h5>
<ol>
    <li>Certifique-se que o <strong>WhatsApp está conectado</strong> (indicador verde no topo)</li>
    <li>Clique em <strong>"Iniciar Envios"</strong> na página da campanha</li>
    <li>O sistema começará a enviar automaticamente seguindo:
        <ul>
            <li>✅ Intervalo calculado</li>
            <li>✅ Horários configurados</li>
            <li>✅ Dias da semana permitidos</li>
            <li>✅ Verificação de data de nascimento (se configurado)</li>
        </ul>
    </li>
</ol>

<h5>📊 Acompanhamento em tempo real</h5>
<p>Na página da campanha você verá:</p>
<ul>
    <li>📈 Gráfico de progresso</li>
    <li>📊 Estatísticas: Total, Enviados, Confirmados, Rejeitados, Pendentes</li>
    <li>📋 Lista de todos os contatos com status individual</li>
    <li>⏰ Próximo envio agendado</li>
</ul>

<div class="alert alert-danger">
    <strong>⚠️ Importante:</strong> O WhatsApp DEVE estar conectado antes de iniciar os envios! Caso contrário, os envios ficarão em fila e só serão processados quando conectar.
</div>
                '''
            },
            {
                'titulo': 'Configurando o WhatsApp',
                'categoria': 'configuracoes',
                'ordem': 3,
                'descricao': 'Guia completo de configuração da Evolution API',
                'conteudo': '''
<h4>📱 Conectando o WhatsApp via Evolution API</h4>

<h5>🔧 Requisitos:</h5>
<ul>
    <li>✅ <strong>Evolution API v2</strong> instalada e rodando em um servidor</li>
    <li>✅ <strong>URL da API:</strong> Ex: https://evolution.seudominio.com</li>
    <li>✅ <strong>Nome da instância:</strong> Identificador único (ex: huwc_busca_ativa)</li>
    <li>✅ <strong>API Key:</strong> Chave de autenticação da Evolution API</li>
    <li>✅ <strong>Número de WhatsApp:</strong> Um chip dedicado para o sistema</li>
</ul>

<div class="alert alert-info">
    <strong>💡 O que é Evolution API?</strong> É uma API open-source que permite integrar WhatsApp com sistemas externos de forma oficial e segura, sem riscos de ban.
</div>

<h5>⚙️ Passo a passo da configuração:</h5>
<ol>
    <li><strong>Acesse as Configurações:</strong> Clique em "Configurações" no menu lateral</li>
    <li><strong>Preencha os dados da Evolution API:</strong>
        <ul>
            <li><strong>API Base URL:</strong> URL completa (ex: https://evolution.seudominio.com)</li>
            <li><strong>Instance Name:</strong> Nome da instância (ex: huwc_busca)</li>
            <li><strong>API Key:</strong> Chave de autenticação</li>
        </ul>
    </li>
    <li><strong>Ative o WhatsApp:</strong> Marque o checkbox "WhatsApp Ativo"</li>
    <li><strong>Salve as configurações:</strong> Clique em "Salvar"</li>
    <li><strong>Gere o QR Code:</strong> Clique no botão "Gerar QR Code"</li>
    <li><strong>Conecte o WhatsApp:</strong>
        <ul>
            <li>Abra o WhatsApp no celular</li>
            <li>Vá em Configurações → Aparelhos Conectados</li>
            <li>Clique em "Conectar um aparelho"</li>
            <li>Escaneie o QR Code exibido na tela</li>
        </ul>
    </li>
</ol>

<div class="alert alert-success">
    <strong>✅ Pronto!</strong> Quando conectado, você verá um indicador <span class="badge bg-success">WhatsApp Conectado</span> no topo de todas as páginas.
</div>

<h5>🔄 Configuração de Follow-Up</h5>
<p>O sistema pode enviar mensagens automáticas de acompanhamento após o primeiro contato:</p>
<ul>
    <li><strong>Ativar Follow-up:</strong> Marque o checkbox na seção "Follow-up"</li>
    <li><strong>Mensagem:</strong> Digite a mensagem que será enviada (ex: "Olá {nome}, conseguiu confirmar sua disponibilidade?")</li>
    <li><strong>Dias de espera:</strong> Quantos dias aguardar antes de enviar (ex: 3 dias)</li>
</ul>

<div class="alert alert-warning">
    <strong>⚠️ Importante:</strong> O follow-up só é enviado para contatos que não responderam nem confirmaram após o primeiro envio!
</div>

<h5>📅 Configuração de Dias da Semana</h5>
<p>Escolha em quais dias da semana o sistema pode enviar mensagens:</p>
<ul>
    <li>✅ Marque os dias permitidos (ex: Segunda a Sexta)</li>
    <li>❌ Desmarque finais de semana se não quiser enviar nesses dias</li>
    <li>💡 O sistema respeitará automaticamente essa configuração</li>
</ul>

<h5>🔍 Testando a conexão:</h5>
<ol>
    <li>Após escanear o QR Code, aguarde alguns segundos</li>
    <li>Atualize a página (F5)</li>
    <li>Verifique se o indicador mudou para "Conectado" (verde)</li>
    <li>Se não conectar, clique novamente em "Gerar QR Code"</li>
</ol>

<h5>❓ Problemas comuns:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Problema</th>
            <th>Solução</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td>QR Code não aparece</td>
            <td>Verifique se a URL da API está correta e acessível</td>
        </tr>
        <tr>
            <td>QR Code expira rápido</td>
            <td>Normal! Clique em "Gerar QR Code" novamente</td>
        </tr>
        <tr>
            <td>Não conecta após escanear</td>
            <td>Verifique a API Key e o nome da instância</td>
        </tr>
        <tr>
            <td>Desconecta sozinho</td>
            <td>Pode ser problema no servidor da Evolution API</td>
        </tr>
    </tbody>
</table>

<div class="alert alert-danger">
    <strong>🚨 Segurança:</strong> Use um chip dedicado apenas para o sistema! Não use seu WhatsApp pessoal ou compartilhado.
</div>
                '''
            },
            {
                'titulo': 'Sistema de Atendimento Inteligente',
                'categoria': 'atendimento',
                'ordem': 4,
                'descricao': 'Gestão completa de tickets e atendimento',
                'conteudo': '''
<h4>🎯 Sistema de Atendimento de Tickets</h4>

<p>O sistema possui <strong>inteligência artificial</strong> que analisa todas as mensagens recebidas e cria tickets automaticamente quando detecta situações que precisam de atenção humana.</p>

<h5>🤖 Quando um ticket é criado automaticamente:</h5>
<ul>
    <li>🚨 <strong>Mensagens urgentes:</strong> Palavras como "emergência", "urgente", "dor", "grave", "hospital"</li>
    <li>😠 <strong>Análise de sentimento negativo:</strong> Sistema detecta insatisfação, raiva ou frustração</li>
    <li>❓ <strong>Dúvidas complexas:</strong> Mensagens que não encontram resposta no FAQ automático</li>
    <li>📝 <strong>Mensagens longas:</strong> Textos com mais de 200 caracteres (indica situação complexa)</li>
    <li>❌ <strong>Rejeições:</strong> Paciente indica que não pode ou não quer participar</li>
</ul>

<h5>🎫 Tipos de tickets:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Tipo</th>
            <th>Prioridade</th>
            <th>Quando aparece</th>
        </tr>
    </thead>
    <tbody>
        <tr class="table-danger">
            <td><strong>🚨 URGENTE</strong></td>
            <td>Alta</td>
            <td>Palavras de emergência, sentimento muito negativo</td>
        </tr>
        <tr class="table-warning">
            <td><strong>⚠️ IMPORTANTE</strong></td>
            <td>Média</td>
            <td>Rejeições, dúvidas não respondidas pelo FAQ</td>
        </tr>
        <tr class="table-info">
            <td><strong>ℹ️ NORMAL</strong></td>
            <td>Baixa</td>
            <td>Mensagens longas, perguntas específicas</td>
        </tr>
    </tbody>
</table>

<h5>👨‍💼 Como atender um ticket:</h5>
<ol>
    <li><strong>Acesse o painel:</strong> Clique em "Atendimento" no menu lateral</li>
    <li><strong>Visualize os tickets:</strong> Veja lista ordenada por prioridade (urgentes primeiro)</li>
    <li><strong>Filtre se necessário:</strong> Use os filtros para ver apenas urgentes, pendentes, ou em atendimento</li>
    <li><strong>Abra o ticket:</strong> Clique no ticket para ver todos os detalhes:
        <ul>
            <li>Nome do paciente</li>
            <li>Campanha relacionada</li>
            <li>Mensagem completa recebida</li>
            <li>Histórico de interações</li>
            <li>Análise de sentimento</li>
        </ul>
    </li>
    <li><strong>Assuma o ticket:</strong> Clique em "Assumir Ticket" para marcar que você está atendendo</li>
    <li><strong>Responda:</strong> Digite sua resposta personalizada na caixa de texto</li>
    <li><strong>Envie:</strong> Clique em "Enviar Resposta" - a mensagem vai direto para o WhatsApp do paciente!</li>
    <li><strong>Finalize:</strong> Após resolver, clique em "Resolver" para fechar o ticket</li>
</ol>

<div class="alert alert-success">
    <strong>✅ Automação:</strong> A resposta é enviada automaticamente via WhatsApp sem você precisar abrir o aplicativo! O sistema já registra tudo no histórico.
</div>

<h5>📊 Dashboard de tickets:</h5>
<p>No topo da página de Atendimento você vê:</p>
<ul>
    <li>🔴 <strong>Tickets Urgentes:</strong> Contador em tempo real</li>
    <li>🟡 <strong>Tickets Pendentes:</strong> Aguardando atendimento</li>
    <li>🟢 <strong>Em Atendimento:</strong> Que você já assumiu</li>
    <li>⚫ <strong>Resolvidos:</strong> Finalizados nas últimas 24h</li>
</ul>

<h5>💬 Sistema de FAQ Automático:</h5>
<p>Para reduzir a quantidade de tickets, configure respostas automáticas!</p>
<ol>
    <li>Vá em <strong>FAQ</strong> no menu</li>
    <li>Clique em "Nova Resposta Automática"</li>
    <li>Configure:
        <ul>
            <li><strong>Categoria:</strong> Ex: horário, endereço, documentos</li>
            <li><strong>Gatilhos:</strong> Palavras-chave que ativam a resposta (ex: "que horas", "horário", "quando")</li>
            <li><strong>Resposta:</strong> Mensagem que será enviada automaticamente</li>
            <li><strong>Prioridade:</strong> 1 (baixa) a 10 (alta)</li>
        </ul>
    </li>
    <li>Salve e pronto! O sistema responderá automaticamente quando detectar os gatilhos</li>
</ol>

<div class="alert alert-warning">
    <strong>⚡ Importante:</strong> O FAQ só responde se a mensagem NÃO for urgente. Mensagens urgentes sempre viram ticket, mesmo que tenham gatilhos de FAQ!
</div>

<h5>📈 Estatísticas de atendimento:</h5>
<p>O sistema registra automaticamente:</p>
<ul>
    <li>⏱️ Tempo médio de resposta</li>
    <li>✅ Taxa de resolução</li>
    <li>📊 Tickets por categoria</li>
    <li>👤 Atendimentos por operador</li>
    <li>😊 Análise de satisfação (baseada em respostas)</li>
</ul>

<div class="alert alert-info">
    <strong>💡 Dica Pro:</strong> Tickets urgentes aparecem em VERMELHO no topo da lista. Atenda-os primeiro para evitar situações críticas!
</div>
                '''
            },
            {
                'titulo': 'Entendendo os Status dos Contatos',
                'categoria': 'campanhas',
                'ordem': 5,
                'descricao': 'Fluxo completo e significado de cada status',
                'conteudo': '''
<h4>📊 Fluxo de Status dos Contatos</h4>

<p>Cada contato passa por diferentes status durante a campanha. Entender cada um é essencial para acompanhar o progresso!</p>

<h5>🔄 Ciclo de vida de um contato:</h5>

<table class="table table-bordered">
    <thead>
        <tr>
            <th>Status</th>
            <th>Badge</th>
            <th>Significado</th>
            <th>Próxima ação</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>pendente</strong></td>
            <td><span class="badge bg-secondary">Pendente</span></td>
            <td>Contato importado, aguardando processamento</td>
            <td>Sistema validará e preparará para envio</td>
        </tr>
        <tr>
            <td><strong>pronto_envio</strong></td>
            <td><span class="badge bg-info">Pronto</span></td>
            <td>Número validado, aguardando vez na fila</td>
            <td>Aguarda horário agendado para envio</td>
        </tr>
        <tr class="table-warning">
            <td><strong>aguardando_nascimento</strong></td>
            <td><span class="badge bg-warning">Aguard. Aniversário</span></td>
            <td>Esperando data de nascimento chegar</td>
            <td>Sistema envia automaticamente no aniversário</td>
        </tr>
        <tr>
            <td><strong>enviado</strong></td>
            <td><span class="badge bg-primary">Enviado</span></td>
            <td>Mensagem enviada com sucesso</td>
            <td>Aguarda resposta do paciente</td>
        </tr>
        <tr class="table-success">
            <td><strong>concluido</strong></td>
            <td><span class="badge bg-success">Concluído</span></td>
            <td>Paciente confirmou ou rejeitou</td>
            <td>Processo finalizado para este contato</td>
        </tr>
        <tr class="table-danger">
            <td><strong>erro</strong></td>
            <td><span class="badge bg-danger">Erro</span></td>
            <td>Falha no envio (número inválido, etc)</td>
            <td>Verificar erro e reenviar se possível</td>
        </tr>
    </tbody>
</table>

<h5>🎂 Status especial: aguardando_nascimento</h5>
<div class="alert alert-warning">
    <strong>⚡ Validação JIT (Just In Time):</strong><br>
    Quando um contato tem data de nascimento no futuro, o sistema <strong>NÃO envia imediatamente</strong>.
    Ele espera a data de nascimento chegar e só então envia automaticamente!<br><br>
    <strong>Por que?</strong> Para evitar contatar pacientes antes do aniversário deles, respeitando regras específicas de alguns procedimentos.
</div>

<h5>✅ Confirmações e Rejeições:</h5>
<p>Além dos status principais, cada contato pode ter flags adicionais:</p>
<ul>
    <li>✅ <strong>confirmado = True:</strong> Paciente disse "SIM", quer participar
        <ul>
            <li>Palavras detectadas: "sim", "confirmo", "quero", "aceito", "ok"</li>
        </ul>
    </li>
    <li>❌ <strong>rejeitado = True:</strong> Paciente disse "NÃO", não quer participar
        <ul>
            <li>Palavras detectadas: "não", "nao", "recuso", "desisto", "cancelar"</li>
        </ul>
    </li>
    <li>❓ <strong>duvida = True:</strong> Paciente tem dúvidas (cria ticket automaticamente)
        <ul>
            <li>Mensagens que não são sim/não claros</li>
        </ul>
    </li>
</ul>

<h5>🔄 Transições automáticas:</h5>
<p>O sistema muda os status automaticamente:</p>

<pre class="bg-light p-3">
1. IMPORTAÇÃO ──→ pendente
2. VALIDAÇÃO ───→ pronto_envio (se válido) ou erro (se inválido)
3. VERIFICAÇÃO ─→ aguardando_nascimento (se nascimento no futuro)
4. ENVIO ────────→ enviado (se sucesso) ou erro (se falha)
5. RESPOSTA ────→ concluido (após confirmação/rejeição)
</pre>

<h5>📞 Múltiplos telefones:</h5>
<p>Quando um contato tem vários telefones:</p>
<ul>
    <li>🔄 O sistema tenta o <strong>1º telefone</strong> primeiro</li>
    <li>⏱️ Se não houver resposta em <strong>X dias</strong>, tenta o próximo</li>
    <li>✅ Para ao receber confirmação ou rejeição</li>
    <li>📊 Cada telefone tem seu próprio status de validação</li>
</ul>

<div class="alert alert-info">
    <strong>💡 Dica:</strong> Na página da campanha, você pode filtrar contatos por status para focar em grupos específicos (ex: ver apenas os que erraram para reenviar).
</div>
                '''
            },
            {
                'titulo': 'Relatórios e Análise de Dados',
                'categoria': 'campanhas',
                'ordem': 6,
                'descricao': 'Gráficos interativos e exportação de dados',
                'conteudo': '''
<h4>📈 Sistema de Relatórios Avançados</h4>

<p>O sistema oferece análise completa de cada campanha com gráficos interativos e exportação para Excel!</p>

<h5>📊 Acessando relatórios:</h5>
<ol>
    <li>No <strong>Dashboard</strong>, clique no ícone 📊 ao lado de qualquer campanha</li>
    <li>Ou na página da campanha, clique em <strong>"Ver Relatórios"</strong></li>
    <li>Você verá uma página completa com gráficos e estatísticas</li>
</ol>

<h5>📉 Gráficos disponíveis:</h5>

<div class="row">
    <div class="col-md-6">
        <h6>1️⃣ Gráfico de Pizza - Distribuição de Status</h6>
        <ul>
            <li>Visualiza proporção de cada status</li>
            <li>Cores diferentes para cada categoria</li>
            <li>Clique nas legendas para ocultar/mostrar</li>
        </ul>
    </div>
    <div class="col-md-6">
        <h6>2️⃣ Gráfico de Barras - Respostas</h6>
        <ul>
            <li>Compara confirmados vs rejeitados vs pendentes</li>
            <li>Fácil visualização de taxa de sucesso</li>
            <li>Atualiza em tempo real</li>
        </ul>
    </div>
</div>

<div class="row mt-3">
    <div class="col-md-6">
        <h6>3️⃣ Gráfico de Linha - Progresso no Tempo</h6>
        <ul>
            <li>Mostra envios ao longo dos dias</li>
            <li>Identifica padrões e picos</li>
            <li>Ajuda a planejar próximas campanhas</li>
        </ul>
    </div>
    <div class="col-md-6">
        <h6>4️⃣ Taxa de Conversão</h6>
        <ul>
            <li>Percentual de confirmações sobre total</li>
            <li>Indicador de efetividade da campanha</li>
            <li>Comparação com meta estabelecida</li>
        </ul>
    </div>
</div>

<h5>📊 Estatísticas detalhadas:</h5>
<table class="table table-bordered">
    <thead>
        <tr>
            <th>Métrica</th>
            <th>Descrição</th>
        </tr>
    </thead>
    <tbody>
        <tr>
            <td><strong>Total de Contatos</strong></td>
            <td>Quantidade total importada da planilha</td>
        </tr>
        <tr>
            <td><strong>Enviados</strong></td>
            <td>Mensagens enviadas com sucesso</td>
        </tr>
        <tr>
            <td><strong>Confirmados</strong></td>
            <td>Pacientes que disseram SIM</td>
        </tr>
        <tr>
            <td><strong>Rejeitados</strong></td>
            <td>Pacientes que disseram NÃO</td>
        </tr>
        <tr>
            <td><strong>Pendentes</strong></td>
            <td>Ainda não receberam ou não responderam</td>
        </tr>
        <tr>
            <td><strong>Erros</strong></td>
            <td>Falhas no envio (números inválidos, etc)</td>
        </tr>
        <tr>
            <td><strong>Taxa de Resposta</strong></td>
            <td>(Confirmados + Rejeitados) / Enviados × 100</td>
        </tr>
        <tr>
            <td><strong>Taxa de Sucesso</strong></td>
            <td>Confirmados / Enviados × 100</td>
        </tr>
    </tbody>
</table>

<h5>📥 Exportação para Excel:</h5>
<p>Exporte todos os dados da campanha em formato Excel:</p>
<ol>
    <li>Na página da campanha, clique no botão <strong>"Exportar Excel"</strong> (ícone de download)</li>
    <li>O arquivo será baixado automaticamente com nome: <code>campanha_[nome]_[data].xlsx</code></li>
    <li>Contém todas as informações:
        <ul>
            <li>Nome, telefone(s), data de nascimento</li>
            <li>Procedimento</li>
            <li>Status atual</li>
            <li>Data de envio</li>
            <li>Confirmado/Rejeitado</li>
            <li>Resposta recebida</li>
            <li>Data de resposta</li>
        </ul>
    </li>
</ol>

<div class="alert alert-success">
    <strong>✅ Use o Excel para:</strong>
    <ul class="mb-0">
        <li>Análises customizadas com tabelas dinâmicas</li>
        <li>Compartilhar resultados com gestores</li>
        <li>Criar apresentações de resultados</li>
        <li>Backup dos dados da campanha</li>
    </ul>
</div>

<h5>🔄 Atualização em tempo real:</h5>
<p>Os gráficos são gerados dinamicamente! Sempre que:</p>
<ul>
    <li>✉️ Uma nova mensagem é enviada</li>
    <li>💬 Um paciente responde</li>
    <li>✅ Um contato confirma ou rejeita</li>
</ul>
<p>Os relatórios são atualizados automaticamente. Basta <strong>recarregar a página</strong> (F5) para ver os dados mais recentes!</p>

<div class="alert alert-info">
    <strong>💡 Dica Pro:</strong> Compare relatórios de diferentes campanhas para identificar qual tipo de mensagem ou horário tem melhor taxa de conversão!
</div>
                '''
            },
            {
                'titulo': 'Solução de Problemas Comuns',
                'categoria': 'inicio',
                'ordem': 7,
                'descricao': 'Troubleshooting e perguntas frequentes',
                'conteudo': '''
<h4>🔧 Solução de Problemas</h4>

<p>Encontrou algum problema? Aqui estão as soluções para os erros mais comuns!</p>

<h5>❌ Problemas com WhatsApp:</h5>

<div class="card mb-3">
    <div class="card-header bg-danger text-white">
        <strong>WhatsApp não conecta</strong>
    </div>
    <div class="card-body">
        <p><strong>Sintomas:</strong> QR Code não aparece ou não conecta após escanear</p>
        <p><strong>Soluções:</strong></p>
        <ol>
            <li>Verifique se a URL da Evolution API está correta e acessível</li>
            <li>Confirme que a API Key está correta</li>
            <li>Verifique se o nome da instância não tem espaços ou caracteres especiais</li>
            <li>Teste acessar a URL da API diretamente no navegador</li>
            <li>Reinicie o servidor da Evolution API se tiver acesso</li>
        </ol>
    </div>
</div>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>WhatsApp desconecta sozinho</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas comuns:</strong></p>
        <ul>
            <li>Servidor da Evolution API reiniciou ou caiu</li>
            <li>WhatsApp foi desconectado manualmente no celular</li>
            <li>Problema de conectividade do servidor</li>
        </ul>
        <p><strong>Solução:</strong> Reconecte usando "Gerar QR Code" novamente</p>
    </div>
</div>

<h5>📊 Problemas com Campanhas:</h5>

<div class="card mb-3">
    <div class="card-header bg-info text-white">
        <strong>Envios não estão saindo</strong>
    </div>
    <div class="card-body">
        <p><strong>Verifique:</strong></p>
        <ol>
            <li>✅ WhatsApp está conectado? (indicador verde no topo)</li>
            <li>✅ Campanha está com status "Em andamento"?</li>
            <li>✅ Está dentro do horário configurado? (ex: 08:00 às 18:00)</li>
            <li>✅ Hoje é um dia da semana permitido?</li>
            <li>✅ Há contatos com status "pronto_envio"?</li>
            <li>✅ O intervalo entre envios não está muito longo?</li>
        </ol>
    </div>
</div>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>Planilha não é importada</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas comuns:</strong></p>
        <ul>
            <li>Arquivo não está em formato .xlsx ou .xls</li>
            <li>Faltam colunas obrigatórias (Nome e Telefone)</li>
            <li>Nomes das colunas estão errados (use: Nome ou Usuario, Telefone)</li>
            <li>Planilha está vazia ou sem dados na primeira linha</li>
        </ul>
        <p><strong>Solução:</strong> Use o modelo correto com colunas: Nome, Telefone, Nascimento, Procedimento</p>
    </div>
</div>

<h5>📞 Problemas com Telefones:</h5>

<div class="card mb-3">
    <div class="card-header bg-danger text-white">
        <strong>Muitos números inválidos</strong>
    </div>
    <div class="card-body">
        <p><strong>Causas:</strong></p>
        <ul>
            <li>Números sem DDD ou com formato incorreto</li>
            <li>Números antigos (8 dígitos em vez de 9)</li>
            <li>Números de telefone fixo sem WhatsApp</li>
        </ul>
        <p><strong>Solução:</strong></p>
        <ol>
            <li>Certifique-se que os números têm 11 dígitos (DDD + 9 dígitos)</li>
            <li>Formato: 85992231683 (sem espaços, traços ou parênteses)</li>
            <li>Use a validação automática antes de enviar</li>
        </ol>
    </div>
</div>

<h5>⏰ Problemas com Agendamento:</h5>

<div class="card mb-3">
    <div class="card-header bg-info text-white">
        <strong>Envios muito lentos ou muito rápidos</strong>
    </div>
    <div class="card-body">
        <p><strong>O intervalo é calculado automaticamente!</strong></p>
        <p>Fórmula: <code>Intervalo = (Horas disponíveis × 3600) / Meta diária</code></p>
        <p><strong>Exemplo:</strong></p>
        <ul>
            <li>Meta: 50 mensagens/dia</li>
            <li>Horário: 08:00 às 18:00 (10 horas = 36000 segundos)</li>
            <li>Intervalo: 36000 ÷ 50 = <strong>720 segundos (12 minutos)</strong></li>
        </ul>
        <p><strong>Para ajustar:</strong></p>
        <ul>
            <li>Aumente a meta diária = envios mais rápidos</li>
            <li>Diminua a meta diária = envios mais lentos</li>
            <li>Amplie o horário = mais tempo para distribuir os envios</li>
        </ul>
    </div>
</div>

<h5>🎂 Status aguardando_nascimento:</h5>

<div class="card mb-3">
    <div class="card-header bg-warning">
        <strong>Contatos ficam muito tempo aguardando</strong>
    </div>
    <div class="card-body">
        <p><strong>Isso é NORMAL!</strong></p>
        <p>O sistema usa <strong>validação JIT (Just In Time)</strong>:</p>
        <ul>
            <li>Se a data de nascimento está no futuro, o contato fica em "aguardando_nascimento"</li>
            <li>No dia do aniversário, o sistema envia automaticamente</li>
            <li>Isso evita contatar pacientes antes do momento certo</li>
        </ul>
        <p><strong>Para enviar imediatamente:</strong> Edite o contato e remova a data de nascimento, ou altere para uma data passada</p>
    </div>
</div>

<h5>❓ Perguntas Frequentes:</h5>

<div class="card mb-2">
    <div class="card-header"><strong>Posso pausar uma campanha?</strong></div>
    <div class="card-body">Sim! Clique em "Pausar Envios" na página da campanha. Para retomar, clique em "Retomar Envios".</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Como adicionar mais contatos a uma campanha existente?</strong></div>
    <div class="card-body">Atualmente não é possível. Crie uma nova campanha com os novos contatos ou edite manualmente usando "Adicionar Contato".</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>O sistema envia em finais de semana?</strong></div>
    <div class="card-body">Depende da configuração! Vá em Configurações e marque/desmarque os dias da semana permitidos. Se sábado e domingo estiverem desmarcados, não enviará.</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Posso usar o mesmo número para várias pessoas?</strong></div>
    <div class="card-body">Sim! O sistema agrupa automaticamente contatos com o mesmo nome, permitindo até 5 telefones por pessoa.</div>
</div>

<div class="card mb-2">
    <div class="card-header"><strong>Como reenviar para quem não respondeu?</strong></div>
    <div class="card-body">Na página da campanha, use o botão "Reenviar" ao lado de cada contato. Ou configure o follow-up automático nas Configurações!</div>
</div>

<div class="alert alert-success mt-4">
    <strong>💚 Ainda com dúvidas?</strong><br>
    Entre em contato com o suporte técnico ou consulte a documentação completa da Evolution API em:
    <a href="https://doc.evolution-api.com" target="_blank">doc.evolution-api.com</a>
</div>
                '''
            },
        ]

        for tut_data in tutoriais:
            tut = Tutorial(
                titulo=tut_data['titulo'],
                categoria=tut_data['categoria'],
                ordem=tut_data['ordem'],
                descricao=tut_data['descricao'],
                conteudo=tut_data['conteudo']
            )
            db.session.add(tut)

        db.session.commit()
        logger.info("Tutoriais padrão criados")

    except Exception as e:
        logger.error(f"Erro ao criar tutoriais: {e}")


def criar_admin():
    try:
        admin = Usuario.query.filter_by(email=ADMIN_EMAIL).first()
        if not admin:
            u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL, is_admin=True)
            u.set_password(ADMIN_SENHA)
            db.session.add(u)
            db.session.commit()
            logger.info(f"Admin criado: {ADMIN_EMAIL}")
        else:
            # Garantir que o admin existente tenha is_admin=True
            if not admin.is_admin:
                admin.is_admin = True
                db.session.commit()
                logger.info(f"Admin atualizado com flag is_admin: {ADMIN_EMAIL}")
    except Exception as e:
        logger.warning(f"Erro ao criar admin (banco desatualizado?): {e}")
        # Tentar recriar tabelas
        db.session.rollback()
        db.drop_all()
        db.create_all()
        u = Usuario(nome=ADMIN_NOME, email=ADMIN_EMAIL, is_admin=True)
        u.set_password(ADMIN_SENHA)
        db.session.add(u)
        db.session.commit()
        logger.info(f"Banco recriado e admin criado: {ADMIN_EMAIL}")


# =============================================================================
# FLASK-LOGIN
# =============================================================================
