# 🏥 Busca Ativa de Pacientes - HUWC/CHUFC

[![Python](https://img.shields.io/badge/Python-3.8+-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-3.0+-green.svg)](https://flask.palletsprojects.com/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

Sistema completo de gestão de busca ativa de pacientes em lista de espera cirúrgica com **inteligência artificial**, atendimento automatizado e gestão de relacionamento com o paciente via WhatsApp.

---

## 📋 Índice

- [Visão Geral](#-visão-geral)
- [Funcionalidades](#-funcionalidades)
- [Tecnologias](#-tecnologias)
- [Requisitos](#-requisitos)
- [Instalação](#-instalação)
- [Configuração](#-configuração)
- [Uso do Sistema](#-uso-do-sistema)
- [Estrutura do Projeto](#-estrutura-do-projeto)
- [API e Integrações](#-api-e-integrações)
- [Automação](#-automação)
- [Contribuição](#-contribuição)
- [Suporte](#-suporte)

---

## 🎯 Visão Geral

O **Sistema de Busca Ativa** é uma plataforma completa para gerenciamento de campanhas de contato com pacientes em lista de espera cirúrgica. O sistema utiliza **WhatsApp** como canal de comunicação principal e oferece recursos avançados de automação, análise de sentimento e atendimento inteligente.

### Destaques

- ✅ **100% Automatizado** - Envio, validação e follow-up automáticos
- 🤖 **Inteligência Artificial** - Análise de sentimento e respostas automáticas
- 👤 **Atendimento Humanizado** - Sistema de tickets para casos complexos
- 📊 **Analytics Completo** - Dashboard com insights e estatísticas
- 🔒 **Seguro e Confiável** - Validação de identidade por data de nascimento
- 📱 **Responsivo** - Interface moderna e adaptável

---

## ✨ Funcionalidades

### 📊 **Gestão de Campanhas**
- Upload de planilha Excel com contatos de pacientes
- Validação automática de números no WhatsApp (Evolution API)
- Envio automatizado de mensagens personalizadas
- Controle de limite diário e tempo entre envios
- Validação JIT (Just-In-Time) - valida números apenas antes do envio
- Suporte a múltiplos telefones por paciente
- Exportação de relatórios em Excel

### 💬 **Sistema de FAQ - Respostas Automáticas**
- Criação e gerenciamento de respostas automáticas
- Detecção inteligente por palavras-chave (gatilhos)
- Priorização de respostas
- Contador de uso para medir efetividade
- **5 FAQs pré-configuradas:**
  - Horários de atendimento
  - Endereço do hospital
  - Documentos necessários
  - Preparo para cirurgia
  - Informações sobre acompanhante

### 🎫 **Sistema de Tickets para Atendimento**
- **Criação automática** baseada em análise de sentimento
- 4 níveis de prioridade: urgente, alta, média, baixa
- Painel de atendimento com filtros avançados
- Resposta direta via WhatsApp integrada
- Histórico completo de conversas
- Estatísticas em tempo real

**Detecção automática de:**
- 🚨 Mensagens urgentes (emergência, dor, socorro)
- 😠 Insatisfação do paciente
- ❓ Dúvidas complexas
- 📝 Mensagens muito longas
- 🔁 Múltiplas tentativas de contato

### 🧠 **Análise de Sentimento**
Classificação automática em 6 categorias:
- 😊 **Positivo** - Satisfação e gratidão
- 😐 **Neutro** - Mensagens informativas
- 😟 **Negativo** - Insatisfação leve
- 🚨 **Urgente** - Necessidade imediata
- 😠 **Insatisfeito** - Reclamações severas
- ❓ **Dúvida** - Questões e perguntas

**Dashboard de análise** com:
- Estatísticas por sentimento
- Tickets por prioridade
- FAQs mais utilizadas
- Insights para melhoria do atendimento

### 🔄 **Follow-up Automático**
- Configuração de tentativas e intervalos
- Mensagens progressivas personalizadas:
  - **1ª tentativa:** Lembrete amigável
  - **2ª tentativa:** Aviso de penúltima tentativa
  - **3ª tentativa:** Última oportunidade
- Marcação automática de "sem resposta"
- Execução via Cron Job ou manual

### 📚 **Sistema de Tutoriais**
**4 tutoriais interativos pré-criados:**
1. Bem-vindo ao Sistema
2. Como Criar uma Campanha
3. Configurando o WhatsApp
4. Sistema de Atendimento

Categorias: Início, Campanhas, Configurações, Atendimento

### 👤 **Gestão de Usuários**
- Cadastro público de novos usuários
- Autenticação segura com hash de senha
- Sistema de permissões
- Histórico de acessos

### 📱 **Validação de Identidade**
- Validação por data de nascimento
- Máquina de estados para conversação
- Proteção contra respostas não autorizadas
- Reconhecimento de múltiplas respostas (SIM/NÃO/DESCONHEÇO)

### 📈 **Dashboard e Relatórios**
- Estatísticas em tempo real
- Widgets de tickets urgentes e pendentes
- Atualização automática via AJAX
- Gráficos de progresso
- Exportação de dados em Excel
- Histórico completo de mensagens (logs)

---

## 🛠 Tecnologias

### Backend
- **Python 3.8+**
- **Flask 3.0** - Framework web
- **SQLAlchemy** - ORM para banco de dados
- **Flask-Login** - Gerenciamento de sessões
- **Pandas** - Processamento de planilhas Excel
- **Requests** - Integração com APIs

### Frontend
- **Bootstrap 5.3** - Framework CSS
- **Bootstrap Icons** - Ícones
- **JavaScript (Vanilla)** - Interatividade
- **AJAX** - Atualizações assíncronas

### Banco de Dados
- **PostgreSQL 12+** (Produção - recomendado)
- **SQLite** (Desenvolvimento)

### Integrações
- **Evolution API v2.x** - WhatsApp Business API

---

## 📦 Requisitos

### Sistema
- Python 3.8 ou superior
- PostgreSQL 12+ (ou SQLite para desenvolvimento)
- 2GB RAM mínimo
- 10GB espaço em disco

### Evolution API
- Evolution API v2.x instalada e configurada
- Instância WhatsApp ativa
- Webhook configurado

### Dependências Python
Todas listadas em `requirements.txt`:
```
Flask==3.0.0
Flask-SQLAlchemy==3.1.1
Flask-Login==0.6.3
Werkzeug==3.0.1
pandas==2.1.3
openpyxl==3.1.2
requests==2.31.0
psycopg2-binary==2.9.9
python-dotenv==1.0.0
gunicorn==21.2.0
```

---

## 🚀 Instalação

### Método 1: Instalação Rápida (Recomendado)

```bash
# 1. Clonar repositório
git clone <url-do-repositorio>
cd busca-ativa

# 2. Criar ambiente virtual
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Executar setup automático
python setup.py
```

O script `setup.py` irá:
- ✅ Instalar todas as dependências
- ✅ Configurar banco de dados
- ✅ Criar usuário admin padrão
- ✅ Criar FAQs e tutoriais padrão

### Método 2: Instalação Manual

```bash
# 1. Criar ambiente virtual
python -m venv venv
source venv/bin/activate  # Linux/Mac
# ou
venv\Scripts\activate     # Windows

# 2. Instalar dependências
pip install -r requirements.txt

# 3. Configurar variáveis de ambiente
cp .env.example .env
# Edite o arquivo .env com suas configurações

# 4. Inicializar banco de dados
python -c "from app import db, criar_admin, criar_faqs_padrao, criar_tutoriais_padrao; db.create_all(); criar_admin(); criar_faqs_padrao(); criar_tutoriais_padrao()"

# 5. Executar aplicação
python app.py
```

---

## ⚙️ Configuração

### 1. Banco de Dados

#### PostgreSQL (Produção)
```bash
# Criar banco
createdb busca_ativa

# Configurar no .env
DATABASE_URL=postgresql://usuario:senha@localhost:5432/busca_ativa
```

#### SQLite (Desenvolvimento)
Deixe `DATABASE_URL` vazio no `.env` - SQLite será usado automaticamente.

### 2. Variáveis de Ambiente

Crie o arquivo `.env` na raiz do projeto:

```env
# Banco de Dados
DATABASE_URL=postgresql://usuario:senha@localhost:5432/busca_ativa

# Segurança
SECRET_KEY=sua-chave-secreta-aqui-use-algo-randomico

# Servidor
PORT=5001
DEBUG=False

# WhatsApp (opcional - pode configurar via interface)
EVOLUTION_API_URL=https://sua-evolution-api.com
EVOLUTION_INSTANCE=nome-da-instancia
EVOLUTION_API_KEY=sua-api-key
```

### 3. Evolution API

#### Via Interface Web (Recomendado)
1. Acesse: http://localhost:5001
2. Faça login com credenciais padrão
3. Menu **Configurações > WhatsApp**
4. Preencha:
   - URL da Evolution API
   - Nome da Instância
   - API Key
5. Ative o checkbox "WhatsApp Ativo"
6. Clique em "Salvar"
7. Clique em "Gerar QR Code"
8. Escaneie com WhatsApp

#### Configurar Webhook na Evolution API
Configure o webhook para receber respostas:
```
POST http://seu-servidor:5001/webhook/whatsapp
```

---

## 📖 Uso do Sistema

### Credenciais Padrão

```
Email: admin@huwc.com
Senha: admin123
```

⚠️ **IMPORTANTE:** Altere a senha padrão após o primeiro acesso!

### Executar em Desenvolvimento

```bash
python app.py
```

Acesse: http://localhost:5001

### Executar em Produção

```bash
# Com Gunicorn (4 workers)
gunicorn -w 4 -b 0.0.0.0:5001 app:app

# Com logs
gunicorn -w 4 -b 0.0.0.0:5001 app:app --access-logfile access.log --error-logfile error.log
```

---

## 📱 Guia de Uso

### 1. Criar uma Campanha

1. **Dashboard** > Botão "Nova Campanha"
2. Preencha:
   - Nome da campanha
   - Descrição (opcional)
   - Upload da planilha Excel
   - Mensagem personalizada
   - Limite diário
   - Tempo entre envios
3. Clique em "Criar Campanha"

#### Formato da Planilha Excel

**Colunas Obrigatórias:**
- `Nome` ou `Usuario`: Nome do paciente
- `Telefone`: Número com DDD (ex: 85999999999)

**Colunas Opcionais:**
- `Nascimento` ou `Data_Nascimento`: Data no formato DD/MM/AAAA
- `Procedimento`: Nome do procedimento cirúrgico

**Exemplo:**
```
| Nome              | Telefone    | Nascimento | Procedimento        |
|-------------------|-------------|------------|---------------------|
| João Silva        | 85987654321 | 15/03/1980 | Catarata OE         |
| Maria Santos      | 85912345678 | 22/07/1965 | Prótese de Joelho   |
```

#### Personalização da Mensagem

Use variáveis para personalizar:
- `{nome}` - Substituído pelo nome do paciente
- `{procedimento}` - Substituído pelo procedimento

**Exemplo:**
```
Olá, {nome}!

Você está na lista de espera para: {procedimento}.

Você ainda tem interesse?
1 - SIM
2 - NÃO
```

### 2. Iniciar Campanha

1. Acesse a campanha criada
2. **(Opcional)** Clique em "Validar Números" para verificar WhatsApp antes
3. Clique em "Iniciar Envios"
4. Aguarde o processamento
5. Acompanhe em tempo real no dashboard

### 3. Gerenciar FAQs

1. Menu **FAQ**
2. Clique em "Nova Resposta"
3. Preencha:
   - Categoria (ex: horario)
   - Gatilhos (palavras-chave separadas por vírgula)
   - Resposta automática
   - Prioridade (1-10)
4. Salvar

**Exemplo de FAQ:**
- **Categoria:** horario
- **Gatilhos:** horário, horario, que horas, hora
- **Resposta:** "O agendamento será feito após sua confirmação. A equipe entrará em contato para definir data e horário."

### 4. Atendimento de Tickets

1. Menu **Atendimento**
2. Visualize tickets pendentes/urgentes
3. Clique no ticket para ver detalhes
4. Clique em "Assumir Ticket"
5. Digite sua resposta
6. Clique em "Enviar Resposta e Resolver"

A resposta é enviada automaticamente via WhatsApp!

### 5. Configurar Follow-up Automático

1. Menu **Configurações > Follow-up**
2. Ative o checkbox "Ativar Follow-up Automático"
3. Configure:
   - Número máximo de tentativas (padrão: 3)
   - Intervalo entre tentativas em dias (padrão: 3)
4. Salvar

#### Automatizar com Cron (Linux)

```bash
# Editar crontab
crontab -e

# Adicionar linha para executar todo dia às 9h
0 9 * * * cd /caminho/para/busca-ativa && /caminho/para/venv/bin/python -c "from app import processar_followup_bg; processar_followup_bg()"
```

### 6. Ver Análises e Estatísticas

1. Menu **Análises**
2. Visualize:
   - Distribuição de sentimentos
   - Tickets por prioridade
   - FAQs mais utilizadas
   - Insights para melhorias

### 7. Consultar Tutoriais

1. Menu **Tutorial**
2. Escolha a categoria
3. Leia o passo a passo

---

## 📂 Estrutura do Projeto

```
busca-ativa/
├── app.py                      # Aplicação principal (2500+ linhas)
├── setup.py                    # Script de instalação
├── requirements.txt            # Dependências Python
├── .env.example                # Exemplo de configuração
├── .env                        # Configuração (não versionar)
├── .gitignore                  # Arquivos ignorados pelo Git
├── README.md                   # Este arquivo
│
├── templates/                  # Templates HTML
│   ├── base.html              # Template base
│   ├── login.html             # Página de login
│   ├── cadastro.html          # Cadastro público
│   ├── dashboard.html         # Dashboard principal
│   ├── campanha.html          # Detalhes da campanha
│   ├── editar_contato.html    # Editar contato
│   ├── configuracoes.html     # Configurações WhatsApp
│   ├── faq.html               # Gerenciamento de FAQ
│   ├── atendimento.html       # Painel de atendimento
│   ├── ticket_detalhe.html    # Detalhes do ticket
│   ├── tutorial.html          # Lista de tutoriais
│   ├── tutorial_detalhe.html  # Visualizar tutorial
│   ├── followup_config.html   # Configurar follow-up
│   ├── sentimentos.html       # Dashboard de sentimentos
│   └── logs.html              # Histórico de mensagens
│
├── uploads/                    # Arquivos enviados (Excel)
│   └── .gitkeep
│
└── busca_ativa.db             # Banco SQLite (desenvolvimento)
```

---

## 🗄️ Banco de Dados

### Tabelas Principais

#### Usuários e Autenticação
- `usuarios` - Usuários do sistema

#### Campanhas e Contatos
- `campanhas` - Campanhas de busca ativa
- `contatos` - Pacientes da campanha
- `telefones` - Múltiplos telefones por contato

#### Automação e Inteligência
- `respostas_automaticas` - FAQs configuradas
- `tickets_atendimento` - Tickets para atendimento humano
- `tentativas_contato` - Histórico de follow-up

#### Configurações
- `config_whatsapp` - Configuração da Evolution API
- `config_tentativas` - Configuração de follow-up

#### Logs e Tutoriais
- `logs` - Histórico de mensagens (com análise de sentimento)
- `tutoriais` - Sistema de tutoriais

---

## 🔌 API e Integrações

### Endpoints Principais

#### APIs Públicas
```
POST /webhook/whatsapp          # Webhook Evolution API
GET  /webhook/whatsapp          # Health check
```

#### APIs Autenticadas
```
# Dashboard
GET  /api/dashboard/tickets     # Estatísticas de tickets

# Campanhas
GET  /api/campanha/<id>/status  # Status da campanha

# Contatos
POST /api/contato/<id>/confirmar  # Confirmar manualmente
POST /api/contato/<id>/rejeitar   # Rejeitar manualmente
POST /api/contato/<id>/reenviar   # Reenviar mensagem
POST /api/contato/<id>/revalidar  # Revalidar telefone

# WhatsApp
GET  /api/whatsapp/qrcode       # Gerar QR Code
GET  /api/whatsapp/status       # Status da conexão
```

### Webhook da Evolution API

O sistema recebe eventos da Evolution API no endpoint:
```
POST /webhook/whatsapp
```

**Eventos processados:**
- `messages.upsert` - Nova mensagem recebida

**Fluxo de processamento:**
1. Recebe mensagem
2. Analisa sentimento
3. Verifica se precisa criar ticket
4. Busca resposta automática (FAQ)
5. Processa máquina de estados
6. Responde ou encaminha para atendente

---

## 🤖 Automação

### Follow-up Automático

#### Configuração via Cron (Recomendado)

```bash
# Executar todo dia às 9h
0 9 * * * cd /caminho/para/busca-ativa && /caminho/para/venv/bin/python -c "from app import processar_followup_bg; processar_followup_bg()"
```

#### Execução Manual (Teste)
1. Menu **Configurações > Follow-up**
2. Clique em "Processar Follow-up Agora (Teste)"

#### Como Funciona
1. Identifica pacientes que receberam mensagem mas não responderam
2. Verifica se passou o intervalo configurado (padrão: 3 dias)
3. Envia nova tentativa com mensagem progressiva
4. Repete até atingir máximo de tentativas (padrão: 3)
5. Marca como "sem resposta" se esgotar tentativas

### Análise de Sentimento Automática

Toda mensagem recebida passa por análise de sentimento:

```python
# Categorias detectadas
POSITIVO = ['obrigado', 'obrigada', 'perfeito', 'ótimo']
NEGATIVO = ['não', 'nunca', 'desisto', 'cancelar']
URGENTE = ['urgente', 'emergência', 'dor', 'socorro']
INSATISFACAO = ['absurdo', 'descaso', 'demora']
DUVIDA = ['?', 'como', 'quando', 'onde']
```

**Ações automáticas:**
- Mensagem urgente → Cria ticket com prioridade "urgente"
- Insatisfação → Cria ticket com prioridade "alta"
- Dúvida complexa → Cria ticket com prioridade "média"

---

## 📊 Respostas Reconhecidas

### Confirmação (SIM)
```
SIM, S, 1, CONFIRMO, QUERO, TENHO INTERESSE, CLARO, POSITIVO
```

### Rejeição (NÃO)
```
NÃO, NAO, N, 2, DESISTO, CANCELA, NEGATIVO, NAO QUERO, NAO TENHO
```

### Desconhecimento
```
3, DESCONHECO, DESCONHEÇO, NAO SOU, ENGANO, ERRADO
```

---

## 🔐 Segurança

### Validação de Identidade
- Confirmação por data de nascimento antes de processar resposta
- Proteção contra respostas não autorizadas
- Máquina de estados para fluxo controlado

### Autenticação
- Hash de senha com Werkzeug
- Sessões seguras com Flask-Login
- Proteção CSRF em formulários

### Dados Sensíveis
- Senhas nunca armazenadas em texto puro
- API Keys protegidas em variáveis de ambiente
- Logs sanitizados

---

## 🐛 Troubleshooting

### WhatsApp não conecta
1. Verifique se Evolution API está rodando
2. Confirme URL, Instância e API Key
3. Tente recriar a instância
4. Verifique logs: `tail -f busca_ativa.log`

### Mensagens não são enviadas
1. Verifique se WhatsApp está conectado (indicador verde)
2. Confirme que há números válidos na campanha
3. Verifique limite diário não foi atingido
4. Veja logs de erro no painel da campanha

### Follow-up não está funcionando
1. Verifique se está ativado em Configurações > Follow-up
2. Confirme que Cron Job está configurado
3. Execute manualmente para testar
4. Verifique logs: `busca_ativa.log`

### Banco de dados não inicia
```bash
# Recriar banco
python -c "from app import db; db.drop_all(); db.create_all()"

# Recriar admin e dados padrão
python -c "from app import criar_admin, criar_faqs_padrao, criar_tutoriais_padrao; criar_admin(); criar_faqs_padrao(); criar_tutoriais_padrao()"
```

---

## 🤝 Contribuição

Contribuições são bem-vindas! Para contribuir:

1. Fork o projeto
2. Crie uma branch para sua feature (`git checkout -b feature/AmazingFeature`)
3. Commit suas mudanças (`git commit -m 'Add some AmazingFeature'`)
4. Push para a branch (`git push origin feature/AmazingFeature`)
5. Abra um Pull Request

---

## 📄 Licença

Este projeto está sob a licença MIT. Veja o arquivo `LICENSE` para mais detalhes.

---

## 📞 Suporte

### Documentação
- Tutorial integrado no sistema (Menu > Tutorial)
- Este README
- Comentários no código

### Contato
- Email: ti@huwc.ufc.br
- Telefone: (85) 3366-8000

### Equipe de TI - HUWC
Hospital Universitário Walter Cantídio
Universidade Federal do Ceará
Fortaleza - CE

---

## 🎉 Agradecimentos

Desenvolvido com ❤️ pela equipe de TI do HUWC/CHUFC para melhorar o atendimento aos pacientes em lista de espera cirúrgica.

---

## 📝 Changelog

### v2.0.0 - Sistema Completo de Gestão (2024)
- ✨ Sistema de FAQ com respostas automáticas
- 🤖 Análise de sentimento com IA
- 🎫 Sistema de tickets para atendimento
- 🔄 Follow-up automático configurável
- 📚 Sistema de tutoriais interativos
- 👤 Cadastro público de usuários
- 📊 Dashboard de análise de sentimentos
- 🎨 Interface completamente renovada
- 📱 Validação de identidade por data de nascimento
- 🗄️ 6 novas tabelas no banco de dados

### v1.0.0 - Sistema Básico (2024)
- Upload de planilha Excel
- Envio automatizado via WhatsApp
- Dashboard básico
- Exportação de relatórios

---

**Made with ❤️ for HUWC/CHUFC**
