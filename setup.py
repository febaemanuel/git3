#!/usr/bin/env python3
"""
=============================================================================
SETUP - Busca Ativa de Pacientes HUWC/CHUFC
=============================================================================

Script de instalacao e configuracao do sistema.

Uso:
    python setup.py              # Instalacao completa
    python setup.py --init-db    # Apenas inicializar banco
    python setup.py --create-admin  # Apenas criar admin
    python setup.py --check      # Verificar configuracao
"""

import os
import sys
import subprocess
import getpass

def print_header():
    print("""
╔═══════════════════════════════════════════════════════════════╗
║       BUSCA ATIVA DE PACIENTES - HUWC/CHUFC                   ║
║                    Setup v2.0                                  ║
╚═══════════════════════════════════════════════════════════════╝
    """)

def check_python():
    print("[1/6] Verificando Python...")
    version = sys.version_info
    if version.major < 3 or (version.major == 3 and version.minor < 8):
        print(f"   ERRO: Python 3.8+ necessario (atual: {version.major}.{version.minor})")
        return False
    print(f"   OK: Python {version.major}.{version.minor}.{version.micro}")
    return True

def install_dependencies():
    print("\n[2/6] Instalando dependencias...")
    try:
        subprocess.check_call([sys.executable, '-m', 'pip', 'install', '-r', 'requirements.txt', '-q'])
        print("   OK: Dependencias instaladas")
        return True
    except subprocess.CalledProcessError:
        print("   ERRO: Falha ao instalar dependencias")
        return False

def setup_env():
    print("\n[3/6] Configurando variaveis de ambiente...")

    env_file = '.env'
    env_example = '.env.example'

    if os.path.exists(env_file):
        print(f"   INFO: {env_file} ja existe")
        return True

    # Perguntar configuracoes
    print("\n   Configure o banco de dados PostgreSQL:")
    print("   (Deixe em branco para usar SQLite local)")

    db_host = input("   Host [localhost]: ").strip() or 'localhost'
    db_port = input("   Porta [5432]: ").strip() or '5432'
    db_name = input("   Nome do banco [busca_ativa]: ").strip() or 'busca_ativa'
    db_user = input("   Usuario [postgres]: ").strip() or 'postgres'
    db_pass = getpass.getpass("   Senha: ").strip()

    if db_pass:
        database_url = f"postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
    else:
        database_url = ""
        print("   INFO: Usando SQLite (senha nao fornecida)")

    # Gerar secret key
    import secrets
    secret_key = secrets.token_hex(32)

    # Criar arquivo .env
    env_content = f"""# Busca Ativa - Configuracao
# Gerado automaticamente pelo setup.py

# Banco de Dados PostgreSQL
# Formato: postgresql://usuario:senha@host:porta/banco
DATABASE_URL={database_url}

# Chave secreta para sessoes (NAO COMPARTILHE!)
SECRET_KEY={secret_key}

# Porta do servidor (padrao: 5001)
PORT=5001

# Modo debug (True para desenvolvimento, False para producao)
DEBUG=False
"""

    with open(env_file, 'w') as f:
        f.write(env_content)

    print(f"   OK: Arquivo {env_file} criado")
    return True

def init_database():
    print("\n[4/6] Inicializando banco de dados...")
    try:
        # Carregar variaveis de ambiente
        from dotenv import load_dotenv
        load_dotenv()

        # Importar app e criar tabelas
        from app import app, db, criar_admin

        with app.app_context():
            db.create_all()
            print("   OK: Tabelas criadas")
            criar_admin()
            print("   OK: Usuario admin criado")

        return True
    except Exception as e:
        print(f"   ERRO: {e}")
        return False

def create_directories():
    print("\n[5/6] Criando diretorios...")
    dirs = ['uploads', 'logs']
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        print(f"   OK: {d}/")
    return True

def show_summary():
    print("\n[6/6] Configuracao concluida!")
    print("""
╔═══════════════════════════════════════════════════════════════╗
║                    INSTALACAO CONCLUIDA!                       ║
╠═══════════════════════════════════════════════════════════════╣
║                                                                ║
║  Credenciais de acesso:                                        ║
║  ----------------------                                        ║
║  Email: admin@huwc.com                                         ║
║  Senha: admin123                                               ║
║                                                                ║
║  Para iniciar o servidor:                                      ║
║  -------------------------                                     ║
║  Desenvolvimento:  python app.py                               ║
║  Producao:         gunicorn -w 4 -b 0.0.0.0:5001 app:app      ║
║                                                                ║
║  Acesse: http://localhost:5001                                 ║
║                                                                ║
╚═══════════════════════════════════════════════════════════════╝
    """)

def check_config():
    """Verifica configuracao atual"""
    print_header()
    print("Verificando configuracao...\n")

    # Python
    version = sys.version_info
    print(f"Python: {version.major}.{version.minor}.{version.micro}")

    # .env
    if os.path.exists('.env'):
        print(".env: Encontrado")
        from dotenv import load_dotenv
        load_dotenv()
        db_url = os.environ.get('DATABASE_URL', '')
        if db_url:
            # Ocultar senha
            if '@' in db_url:
                parts = db_url.split('@')
                print(f"Database: PostgreSQL ({parts[1]})")
            else:
                print(f"Database: {db_url[:50]}...")
        else:
            print("Database: SQLite (local)")
    else:
        print(".env: Nao encontrado")

    # Diretorios
    for d in ['uploads', 'logs']:
        status = "OK" if os.path.exists(d) else "Falta"
        print(f"Diretorio {d}: {status}")

    # Testar conexao com banco
    try:
        from app import app, db
        with app.app_context():
            db.engine.connect()
            print("\nConexao com banco: OK")
    except Exception as e:
        print(f"\nConexao com banco: ERRO - {e}")

def main():
    args = sys.argv[1:]

    if '--check' in args:
        check_config()
        return

    if '--init-db' in args:
        print_header()
        init_database()
        return

    if '--create-admin' in args:
        print_header()
        try:
            from dotenv import load_dotenv
            load_dotenv()
            from app import app, db, criar_admin
            with app.app_context():
                criar_admin()
                print("Admin criado: admin@huwc.com / admin123")
        except Exception as e:
            print(f"Erro: {e}")
        return

    # Instalacao completa
    print_header()

    if not check_python():
        sys.exit(1)

    if not install_dependencies():
        sys.exit(1)

    if not setup_env():
        sys.exit(1)

    if not create_directories():
        sys.exit(1)

    if not init_database():
        print("   AVISO: Execute 'python setup.py --init-db' apos corrigir o banco")

    show_summary()

if __name__ == '__main__':
    main()
