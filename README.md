# Busca Ativa de Pacientes - HUWC/CHUFC

Sistema web para envio automatizado de mensagens WhatsApp para pacientes em lista de espera cirurgica.

## Funcionalidades

- Upload de planilha Excel com contatos de pacientes
- Verificacao automatica de numeros no WhatsApp (Evolution API)
- Envio automatizado de mensagens personalizadas
- Recepcao de respostas via webhook (SIM/NAO)
- Dashboard com estatisticas em tempo real
- Exportacao de relatorios Excel
- Historico completo de mensagens

## Requisitos

- Python 3.8+
- PostgreSQL 12+ (ou SQLite para desenvolvimento)
- Evolution API v2.x configurada

## Instalacao Rapida

```bash
# 1. Clonar repositorio
git clone <url-do-repositorio>
cd busca-ativa

# 2. Criar ambiente virtual
python -m venv venv

# Windows
venv\Scripts\activate

# Linux/Mac
source venv/bin/activate

# 3. Executar setup
python setup.py
```

O setup vai:
- Instalar dependencias
- Configurar banco de dados
- Criar usuario admin

## Instalacao Manual

```bash
# 1. Instalar dependencias
pip install -r requirements.txt

# 2. Configurar variaveis de ambiente
cp .env.example .env
# Edite o arquivo .env com suas configuracoes

# 3. Inicializar banco
python -c "from app import db, criar_admin; db.create_all(); criar_admin()"

# 4. Executar
python app.py
```

## Configuracao do Banco de Dados

### PostgreSQL (Recomendado para producao)

```bash
# Criar banco
createdb busca_ativa

# Configurar no .env
DATABASE_URL=postgresql://usuario:senha@localhost:5432/busca_ativa
```

### SQLite (Desenvolvimento)

Deixe `DATABASE_URL` vazio no `.env` para usar SQLite automaticamente.

## Variaveis de Ambiente

| Variavel | Descricao | Padrao |
|----------|-----------|--------|
| DATABASE_URL | URL do PostgreSQL | SQLite local |
| SECRET_KEY | Chave secreta Flask | Gerada |
| PORT | Porta do servidor | 5001 |
| DEBUG | Modo debug | False |

## Uso

### Credenciais Padrao

- **Email:** admin@huwc.com
- **Senha:** admin123

### Executar em Desenvolvimento

```bash
python app.py
```

Acesse: http://localhost:5001

### Executar em Producao

```bash
gunicorn -w 4 -b 0.0.0.0:5001 app:app
```

## Configuracao da Evolution API

1. Acesse **Configuracoes** no menu
2. Preencha:
   - URL da Evolution API (ex: https://sua-api.com)
   - Nome da Instancia
   - API Key
3. Ative o WhatsApp
4. Clique em "Gerar QR Code"
5. Escaneie com o WhatsApp

### Webhook

Configure na Evolution API o webhook:
```
POST http://seu-servidor:5001/webhook/whatsapp
```

## Formato da Planilha Excel

Colunas obrigatorias:
- **Nome** ou **Usuario**: Nome do paciente
- **Telefone**: Numero com DDD (ex: 85999999999)

Colunas opcionais:
- **Procedimento**: Nome do procedimento cirurgico

## Personalizacao da Mensagem

Use as variaveis para personalizar:
- `{nome}`: Sera substituido pelo nome do paciente
- `{procedimento}`: Sera substituido pelo procedimento

## Respostas Automaticas

O sistema reconhece automaticamente:
- **Confirmacao**: SIM, S, 1, CONFIRMO, QUERO, TENHO INTERESSE
- **Rejeicao**: NAO, N, 2, NAO QUERO, DESISTO

## Estrutura do Projeto

```
busca-ativa/
├── app.py              # Aplicacao principal
├── setup.py            # Script de instalacao
├── requirements.txt    # Dependencias Python
├── .env.example        # Exemplo de configuracao
├── .env                # Configuracao (nao versionar)
├── templates/          # Templates HTML
│   ├── base.html
│   ├── login.html
│   ├── dashboard.html
│   ├── campanha.html
│   ├── configuracoes.html
│   └── logs.html
└── uploads/            # Arquivos enviados
```

## Comandos Uteis

```bash
# Verificar configuracao
python setup.py --check

# Inicializar banco
python setup.py --init-db

# Criar admin
python setup.py --create-admin

# Inicializar banco via Flask CLI
flask init-db
```

## Suporte

Para duvidas ou problemas, entre em contato com a equipe de TI do HUWC.
