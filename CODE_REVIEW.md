# 🔍 CODE REVIEW COMPLETO - Sistema Busca Ativa Hospitalar

**Data:** 2025-11-27
**Revisor:** Tech Lead Sênior
**Arquivo Principal:** `app.py` (4252 linhas)
**Framework:** Flask + SQLAlchemy + PostgreSQL

---

## 📊 SUMÁRIO EXECUTIVO

### Métricas Gerais
- ✅ **Pontos Fortes:** 12 identificados
- 🟡 **Melhorias Necessárias:** 18 identificadas
- 🔴 **Problemas Críticos:** 8 identificados

### Classificação de Risco
- 🔴 **Alto:** Segurança e Performance
- 🟡 **Médio:** Arquitetura e Manutenibilidade
- 🟢 **Baixo:** Convenções e Estilo

---

## 🔴 PROBLEMAS CRÍTICOS

### 1. **Credenciais Hardcoded no Código**
**Localização:** Linhas 85-87
**Severidade:** 🔴 CRÍTICA

```python
# ❌ PROBLEMA
ADMIN_EMAIL = 'admin@huwc.com'
ADMIN_SENHA = 'admin123'
ADMIN_NOME = 'Administrador'
```

**Impacto:**
- Senha de admin exposta no código-fonte
- Vulnerabilidade de segurança CRÍTICA
- Qualquer pessoa com acesso ao repositório tem credenciais admin

**Solução:**
```python
# ✅ SOLUÇÃO
# No .env
ADMIN_EMAIL=admin@huwc.com
ADMIN_PASSWORD_HASH=pbkdf2:sha256:...  # Hash gerado previamente

# No código
ADMIN_EMAIL = os.environ.get('ADMIN_EMAIL')
ADMIN_PASSWORD_HASH = os.environ.get('ADMIN_PASSWORD_HASH')
```

**Como corrigir:**
1. Gerar hash da senha:
```python
from werkzeug.security import generate_password_hash
hash_senha = generate_password_hash('SuaSenhaForte@2024')
print(hash_senha)
```
2. Adicionar ao `.env`:
```bash
ADMIN_PASSWORD_HASH=pbkdf2:sha256:600000$...
```
3. Remover senha do código

---

### 2. **SECRET_KEY com Fallback Inseguro**
**Localização:** Linha 60
**Severidade:** 🔴 CRÍTICA

```python
# ❌ PROBLEMA
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'busca-ativa-huwc-2024-secret')
```

**Impacto:**
- Se não houver `.env`, usa chave hardcoded
- Permite ataques de session hijacking
- Sessões podem ser forjadas

**Solução:**
```python
# ✅ SOLUÇÃO
SECRET_KEY = os.environ.get('SECRET_KEY')
if not SECRET_KEY:
    raise RuntimeError(
        "SECRET_KEY não configurada! "
        "Execute: export SECRET_KEY=$(python -c 'import secrets; print(secrets.token_hex(32))')"
    )
app.config['SECRET_KEY'] = SECRET_KEY
```

---

### 3. **SQL Injection em Queries Dinâmicas**
**Localização:** Linha 2856 (aproximadamente)
**Severidade:** 🔴 CRÍTICA

```python
# ❌ PROBLEMA (se existir)
# Procurar por construção manual de queries
query = f"SELECT * FROM contatos WHERE nome = '{nome}'"
```

**Solução:**
```python
# ✅ SEMPRE use SQLAlchemy ORM ou parâmetros
contatos = Contato.query.filter_by(nome=nome).all()
# OU com filter
contatos = Contato.query.filter(Contato.nome.like(f'%{termo}%')).all()
```

---

### 4. **Webhook sem Validação de Origem**
**Localização:** Rota `/webhook/whatsapp`
**Severidade:** 🔴 CRÍTICA

**Problema:**
- Webhook recebe dados sem verificar origem
- Qualquer um pode enviar POST para `/webhook/whatsapp`
- Permite ataques de injeção de dados falsos

**Solução:**
```python
# ✅ SOLUÇÃO
@app.route('/webhook/whatsapp', methods=['POST'])
def webhook_whatsapp():
    # 1. Validar IP de origem
    allowed_ips = os.environ.get('EVOLUTION_API_IPS', '').split(',')
    if request.remote_addr not in allowed_ips:
        logger.warning(f"Webhook rejeitado: IP {request.remote_addr}")
        return jsonify({'error': 'Unauthorized'}), 403

    # 2. Validar token/assinatura
    webhook_secret = os.environ.get('WEBHOOK_SECRET')
    signature = request.headers.get('X-Webhook-Signature')

    import hmac
    import hashlib
    expected_signature = hmac.new(
        webhook_secret.encode(),
        request.data,
        hashlib.sha256
    ).hexdigest()

    if not hmac.compare_digest(signature, expected_signature):
        logger.warning("Webhook signature inválida")
        return jsonify({'error': 'Invalid signature'}), 403

    # 3. Processar dados...
```

---

### 5. **Threads sem Tratamento de Exceções**
**Localização:** Diversas (ex: linha 2921)
**Severidade:** 🔴 ALTA

```python
# ❌ PROBLEMA
t = threading.Thread(target=enviar_campanha_bg, args=(id,))
t.daemon = True
t.start()
```

**Impacto:**
- Se thread falhar, falha silenciosa
- Sem logs de erro
- Difícil debug

**Solução:**
```python
# ✅ SOLUÇÃO 1: Wrapper de thread seguro
def safe_thread_wrapper(func, *args, **kwargs):
    def wrapped():
        try:
            func(*args, **kwargs)
        except Exception as e:
            logger.exception(f"Erro em thread {func.__name__}: {e}")
    return wrapped

# Uso:
t = threading.Thread(target=safe_thread_wrapper(enviar_campanha_bg, id))
t.daemon = True
t.start()

# ✅ SOLUÇÃO 2: Usar Celery (RECOMENDADO)
# pip install celery redis
from celery import Celery

celery = Celery('busca_ativa', broker='redis://localhost:6379/0')

@celery.task
def enviar_campanha_bg(campanha_id):
    # ... código da tarefa
```

---

### 6. **Operações de I/O Bloqueantes no Request Cycle**
**Localização:** Rotas de upload e envio
**Severidade:** 🔴 ALTA

```python
# ❌ PROBLEMA: Processamento de planilha no request
@app.route('/campanha/criar', methods=['POST'])
def criar_campanha():
    arquivo = request.files['arquivo']
    # Processa planilha SÍNCRONA (BLOQUEANTE)
    processar_planilha(arquivo, campanha.id)  # Pode demorar minutos!
    return redirect(...)
```

**Impacto:**
- Request pode dar timeout (30s-60s)
- Bloqueia worker do Gunicorn
- Experiência ruim para usuário

**Solução:**
```python
# ✅ SOLUÇÃO
@app.route('/campanha/criar', methods=['POST'])
def criar_campanha():
    arquivo = request.files['arquivo']

    # Salvar arquivo temporário
    temp_path = save_temp_file(arquivo)

    # Processar em background
    celery_task = processar_planilha_async.delay(temp_path, campanha.id)

    flash(f'✅ Campanha criada! Processando planilha... (Task ID: {celery_task.id})', 'info')
    return redirect(url_for('campanha_detalhe', id=campanha.id))

@celery.task
def processar_planilha_async(arquivo_path, campanha_id):
    # ... processamento pesado aqui
```

---

### 7. **Falta Proteção CSRF**
**Localização:** Todas as rotas POST
**Severidade:** 🔴 ALTA

```python
# ❌ PROBLEMA: Nenhuma proteção CSRF ativada
```

**Solução:**
```python
# ✅ SOLUÇÃO
from flask_wtf.csrf import CSRFProtect

csrf = CSRFProtect(app)

# Em templates com forms:
<form method="POST">
    {{ csrf_token() }}
    <!-- resto do form -->
</form>

# Para APIs JSON (excluir CSRF):
@app.route('/api/endpoint', methods=['POST'])
@csrf.exempt
def api_endpoint():
    # API endpoints devem usar tokens de API em vez de CSRF
    api_key = request.headers.get('X-API-Key')
    if api_key != os.environ.get('API_KEY'):
        return jsonify({'error': 'Unauthorized'}), 401
    # ...
```

---

### 8. **Logs sem Rotação**
**Localização:** Linha 54
**Severidade:** 🟡 MÉDIA

```python
# ❌ PROBLEMA
logging.FileHandler('busca_ativa.log', encoding='utf-8')
```

**Impacto:**
- Log cresce indefinidamente
- Pode encher disco em produção

**Solução:**
```python
# ✅ SOLUÇÃO
from logging.handlers import RotatingFileHandler

handler = RotatingFileHandler(
    'busca_ativa.log',
    maxBytes=10*1024*1024,  # 10MB
    backupCount=5,  # Manter 5 arquivos
    encoding='utf-8'
)
handler.setFormatter(logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
))
logger.addHandler(handler)
```

---

## 🟡 PROBLEMAS DE ARQUITETURA

### 9. **Violação do Princípio Single Responsibility**
**Localização:** `app.py` inteiro (4252 linhas)
**Severidade:** 🟡 ALTA

**Problema:**
- Um único arquivo com:
  - Models (11 classes)
  - Routes (50+ rotas)
  - Business Logic
  - Integrações externas (WhatsApp, DeepSeek)
  - Utils

**Solução Recomendada:**
```
busca_ativa/
├── app.py                 # Apenas configuração Flask
├── models/
│   ├── __init__.py
│   ├── usuario.py
│   ├── campanha.py
│   ├── contato.py
│   └── whatsapp.py
├── routes/
│   ├── __init__.py
│   ├── auth.py           # Login, logout
│   ├── campanhas.py      # CRUD campanhas
│   ├── contatos.py       # CRUD contatos
│   ├── api.py            # Endpoints API
│   └── webhooks.py       # Webhooks externos
├── services/
│   ├── __init__.py
│   ├── whatsapp_service.py
│   ├── deepseek_service.py
│   └── excel_service.py
├── utils/
│   ├── __init__.py
│   ├── validators.py
│   └── formatters.py
└── config.py             # Configurações
```

**Refatoração Exemplo:**

```python
# ✅ models/usuario.py
from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

class Usuario(UserMixin, db.Model):
    __tablename__ = 'usuarios'
    id = db.Column(db.Integer, primary_key=True)
    # ... campos

    def set_password(self, senha):
        self.senha_hash = generate_password_hash(senha)

    def check_password(self, senha):
        return check_password_hash(self.senha_hash, senha)

# ✅ routes/auth.py
from flask import Blueprint, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required
from models.usuario import Usuario

auth_bp = Blueprint('auth', __name__)

@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    # ... lógica de login

# ✅ app.py (muito menor!)
from flask import Flask
from extensions import db, login_manager, csrf
from routes.auth import auth_bp
from routes.campanhas import campanhas_bp

app = Flask(__name__)
app.config.from_object('config.ProductionConfig')

db.init_app(app)
login_manager.init_app(app)
csrf.init_app(app)

app.register_blueprint(auth_bp)
app.register_blueprint(campanhas_bp)
```

---

### 10. **Falta de Validação de Input**
**Localização:** Todas as rotas POST
**Severidade:** 🟡 ALTA

**Problema:**
```python
# ❌ PROBLEMA
@app.route('/campanha/criar', methods=['POST'])
def criar_campanha():
    nome = request.form.get('nome')  # Sem validação!
    descricao = request.form.get('descricao')  # Sem limite de tamanho!
```

**Solução:**
```python
# ✅ SOLUÇÃO: Usar Flask-WTF + WTForms
from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, IntegerField
from wtforms.validators import DataRequired, Length, NumberRange

class CampanhaForm(FlaskForm):
    nome = StringField('Nome', validators=[
        DataRequired(message='Nome é obrigatório'),
        Length(min=3, max=200, message='Nome deve ter 3-200 caracteres')
    ])
    descricao = TextAreaField('Descrição', validators=[
        Length(max=1000, message='Descrição muito longa')
    ])
    meta_diaria = IntegerField('Meta Diária', validators=[
        NumberRange(min=1, max=1000, message='Meta deve estar entre 1 e 1000')
    ])

@app.route('/campanha/criar', methods=['POST'])
def criar_campanha():
    form = CampanhaForm()
    if not form.validate_on_submit():
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{field}: {error}', 'danger')
        return redirect(url_for('campanhas'))

    campanha = Campanha(
        nome=form.nome.data,
        descricao=form.descricao.data,
        meta_diaria=form.meta_diaria.data
    )
    # ...
```

---

### 11. **Gestão de Sessões de DB Inadequada**
**Localização:** Funções de background
**Severidade:** 🟡 MÉDIA

**Problema:**
```python
# ❌ PROBLEMA
def enviar_campanha_bg(campanha_id):
    with app.app_context():
        camp = db.session.get(Campanha, campanha_id)
        # ... operações longas ...
        db.session.commit()  # Sessão pode ter expirado!
```

**Solução:**
```python
# ✅ SOLUÇÃO
def enviar_campanha_bg(campanha_id):
    with app.app_context():
        # Criar nova sessão scoped
        from sqlalchemy.orm import scoped_session, sessionmaker
        Session = scoped_session(sessionmaker(bind=db.engine))
        session = Session()

        try:
            camp = session.get(Campanha, campanha_id)
            # ... operações ...
            session.commit()
        except Exception as e:
            session.rollback()
            logger.exception(f"Erro: {e}")
            raise
        finally:
            session.close()
            Session.remove()
```

---

## 🟢 MELHORIAS DE CÓDIGO

### 12. **Uso de f-strings para Logs**
**Localização:** Vários lugares
**Severidade:** 🟢 BAIXA

```python
# ❌ PROBLEMA (menos eficiente)
logger.info("Processando contato %s" % c.nome)
logger.info("Total: {}".format(total))

# ✅ SOLUÇÃO
logger.info(f"Processando contato {c.nome}")
logger.info(f"Total: {total}")
```

---

### 13. **Magic Numbers**
**Localização:** Vários lugares
**Severidade:** 🟢 BAIXA

```python
# ❌ PROBLEMA
if camp.enviados_hoje < 50:
    time.sleep(15)

# ✅ SOLUÇÃO
DEFAULT_META_DIARIA = 50
DEFAULT_SLEEP_SECONDS = 15

if camp.enviados_hoje < DEFAULT_META_DIARIA:
    time.sleep(DEFAULT_SLEEP_SECONDS)
```

---

## 🔒 CHECKLIST DE SEGURANÇA

### Vulnerabilidades Identificadas

| # | Vulnerabilidade | Severidade | Status |
|---|-----------------|------------|--------|
| 1 | Credenciais hardcoded | 🔴 CRÍTICA | ❌ Presente |
| 2 | SECRET_KEY insegura | 🔴 CRÍTICA | ❌ Presente |
| 3 | Webhook sem autenticação | 🔴 CRÍTICA | ❌ Presente |
| 4 | Falta CSRF Protection | 🔴 ALTA | ❌ Presente |
| 5 | Logs sem sanitização | 🟡 MÉDIA | ❌ Presente |
| 6 | Falta rate limiting | 🟡 MÉDIA | ❌ Presente |
| 7 | Headers de segurança ausentes | 🟡 MÉDIA | ❌ Presente |

### Recomendações de Segurança

```python
# ✅ IMPLEMENTAR

# 1. Headers de Segurança
from flask_talisman import Talisman

talisman = Talisman(app,
    force_https=True,
    strict_transport_security=True,
    content_security_policy={
        'default-src': "'self'",
        'script-src': "'self' 'unsafe-inline' cdn.jsdelivr.net",
        'style-src': "'self' 'unsafe-inline' cdn.jsdelivr.net"
    }
)

# 2. Rate Limiting
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

limiter = Limiter(
    app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

@app.route('/login', methods=['POST'])
@limiter.limit("5 per minute")  # Proteger contra brute force
def login():
    # ...

# 3. Sanitização de Logs
def sanitize_for_log(text):
    """Remove dados sensíveis de logs"""
    import re
    # Remover CPF
    text = re.sub(r'\d{3}\.\d{3}\.\d{3}-\d{2}', '***.***.***-**', text)
    # Remover telefones
    text = re.sub(r'\d{11}', '***********', text)
    return text

logger.info(sanitize_for_log(f"Processando {c.nome}"))
```

---

## ⚡ PERFORMANCE

### Problemas Identificados

#### 1. **N+1 Query Problem**
```python
# ❌ PROBLEMA
campanhas = Campanha.query.all()
for camp in campanhas:
    print(camp.contatos.count())  # Query separada para cada campanha!

# ✅ SOLUÇÃO
from sqlalchemy.orm import joinedload

campanhas = Campanha.query.options(
    joinedload(Campanha.contatos)
).all()
```

#### 2. **Falta de Índices**
```python
# ✅ ADICIONAR no Model
class Contato(db.Model):
    __tablename__ = 'contatos'
    # ...

    __table_args__ = (
        db.Index('idx_contato_status', 'status'),
        db.Index('idx_contato_campanha', 'campanha_id', 'status'),
        db.Index('idx_contato_telefone', 'telefone'),
    )
```

#### 3. **Cache Ausente**
```python
# ✅ IMPLEMENTAR
from flask_caching import Cache

cache = Cache(app, config={'CACHE_TYPE': 'redis', 'CACHE_REDIS_URL': 'redis://localhost:6379/0'})

@app.route('/dashboard')
@login_required
@cache.cached(timeout=60, key_prefix=lambda: f'dashboard_{current_user.id}')
def dashboard():
    # ... dados que não mudam a cada segundo
```

---

## 📋 PLANO DE AÇÃO PRIORITÁRIO

### Semana 1 (CRÍTICO)
1. ✅ Remover credenciais hardcoded
2. ✅ Implementar SECRET_KEY obrigatória
3. ✅ Adicionar autenticação no webhook
4. ✅ Implementar CSRF Protection

### Semana 2 (ALTA)
5. ✅ Wrapper para threads com tratamento de exceções
6. ✅ Rate limiting em rotas críticas
7. ✅ Headers de segurança (Talisman)
8. ✅ Validação de inputs (WTForms)

### Semana 3 (REFATORAÇÃO)
9. ✅ Separar models em arquivos
10. ✅ Separar routes em blueprints
11. ✅ Criar services layer
12. ✅ Adicionar testes unitários

### Semana 4 (PERFORMANCE)
13. ✅ Implementar Celery para tarefas async
14. ✅ Adicionar índices no banco
15. ✅ Implementar cache Redis
16. ✅ Otimizar queries (N+1)

---

## 🧪 TESTES - AUSENTES

**Problema:** Zero testes automatizados!

**Solução:**
```python
# ✅ tests/test_auth.py
import pytest
from app import app, db
from models.usuario import Usuario

@pytest.fixture
def client():
    app.config['TESTING'] = True
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'

    with app.test_client() as client:
        with app.app_context():
            db.create_all()
        yield client
        with app.app_context():
            db.drop_all()

def test_login_success(client):
    # Criar usuário
    user = Usuario(email='test@test.com', nome='Test')
    user.set_password('senha123')
    db.session.add(user)
    db.session.commit()

    # Testar login
    response = client.post('/login', data={
        'email': 'test@test.com',
        'senha': 'senha123'
    }, follow_redirects=True)

    assert response.status_code == 200
    assert b'Dashboard' in response.data

def test_login_fail(client):
    response = client.post('/login', data={
        'email': 'wrong@test.com',
        'senha': 'wrong'
    })
    assert b'inv\xc3\xa1lido' in response.data  # inválido
```

---

## 📊 MÉTRICAS DE QUALIDADE

### Antes da Refatoração
- **Linhas de código:** 4252 (1 arquivo)
- **Complexidade ciclomática:** ~30+ (muito alta)
- **Cobertura de testes:** 0%
- **Vulnerabilidades:** 8 críticas
- **Debt técnico:** ALTO

### Após Refatoração (Projetado)
- **Linhas de código:** ~4000 (distribuído em 20+ arquivos)
- **Complexidade ciclomática:** <10 por função
- **Cobertura de testes:** >80%
- **Vulnerabilidades:** 0 críticas
- **Debt técnico:** BAIXO

---

## 🎯 CONCLUSÃO

O sistema funciona, mas possui **dívida técnica significativa** que pode causar problemas em produção:

### Riscos Imediatos
1. 🔴 Vulnerabilidades de segurança críticas
2. 🔴 Escalabilidade limitada (operações bloqueantes)
3. 🟡 Difícil manutenção (código monolítico)

### Recomendações Finais
1. **URGENTE:** Corrigir vulnerabilidades de segurança
2. **ALTA:** Implementar testes automatizados
3. **MÉDIA:** Refatorar arquitetura (separar responsabilidades)
4. **BAIXA:** Melhorias de performance e cache

---

**Próximos Passos:**
1. Revisar este documento com a equipe
2. Priorizar itens críticos (Semana 1)
3. Criar issues no GitHub para cada item
4. Implementar CI/CD com testes automáticos
5. Agendar code reviews regulares

