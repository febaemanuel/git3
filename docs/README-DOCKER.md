# 🐳 Guia de Deploy com Docker

Este guia explica como executar o sistema Busca Ativa usando Docker e Docker Compose.

## 📋 Pré-requisitos

- Docker instalado (versão 20.10+)
- Docker Compose instalado (versão 2.0+)

## 🚀 Início Rápido

### 1. Configurar Variáveis de Ambiente

Edite o arquivo `docker-compose.yml` e configure suas credenciais da Evolution API:

```yaml
environment:
  EVOLUTION_API_URL: https://sua-evolution-api.com
  EVOLUTION_API_KEY: sua-api-key-aqui
  EVOLUTION_INSTANCE: sua-instancia
```

### 2. Iniciar os Containers

```bash
# Construir e iniciar todos os serviços
docker-compose up -d

# Ver logs em tempo real
docker-compose logs -f web
```

### 3. Acessar a Aplicação

A aplicação estará disponível em: **http://localhost:5000**

**Credenciais padrão:**
- Email: `admin@huwc.com`
- Senha: `admin123`

## 🔧 Comandos Úteis

### Gerenciamento de Containers

```bash
# Parar os containers
docker-compose down

# Parar e remover volumes (ATENÇÃO: apaga o banco de dados)
docker-compose down -v

# Reiniciar apenas a aplicação web
docker-compose restart web

# Ver status dos containers
docker-compose ps

# Ver logs
docker-compose logs -f web    # Logs da aplicação
docker-compose logs -f db     # Logs do banco de dados
```

### Banco de Dados

```bash
# Acessar o PostgreSQL
docker-compose exec db psql -U buscaativa -d buscaativa_db

# Fazer backup do banco
docker-compose exec db pg_dump -U buscaativa buscaativa_db > backup.sql

# Restaurar backup
cat backup.sql | docker-compose exec -T db psql -U buscaativa buscaativa_db
```

### Manutenção

```bash
# Reconstruir a imagem após alterações no código
docker-compose build web

# Reiniciar com reconstrução
docker-compose up -d --build

# Ver uso de recursos
docker stats

# Limpar containers, imagens e volumes não utilizados
docker system prune -a
```

## 📁 Estrutura de Volumes

O Docker Compose configura os seguintes volumes:

- `postgres_data`: Armazena os dados do PostgreSQL (persistente)
- `./uploads`: Armazena arquivos enviados (mapeado para o host)
- `./busca_ativa.log`: Logs da aplicação (mapeado para o host)

## 🔐 Segurança

### Alterar Senhas Padrão

1. **Secret Key do Flask** - Em `docker-compose.yml`:
```yaml
SECRET_KEY: sua-chave-secreta-aqui-muito-segura
```

2. **Senha do PostgreSQL** - Em `docker-compose.yml`:
```yaml
POSTGRES_PASSWORD: sua-senha-segura
DATABASE_URL: postgresql://buscaativa:sua-senha-segura@db:5432/buscaativa_db
```

3. **Senha do Admin** - Após o primeiro login, altere a senha no sistema.

## 🌐 Deploy em Produção

### Usando um Servidor Remoto

1. **Copiar arquivos para o servidor:**
```bash
scp -r . usuario@servidor:/caminho/busca-ativa/
```

2. **No servidor, iniciar os containers:**
```bash
cd /caminho/busca-ativa/
docker-compose up -d
```

### Usando Nginx como Proxy Reverso

Exemplo de configuração Nginx:

```nginx
server {
    listen 80;
    server_name busca-ativa.seudominio.com;

    location / {
        proxy_pass http://localhost:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

### SSL/HTTPS com Let's Encrypt

```bash
# Instalar Certbot
apt-get install certbot python3-certbot-nginx

# Obter certificado
certbot --nginx -d busca-ativa.seudominio.com
```

## 🐛 Troubleshooting

### Container Web não inicia

```bash
# Ver logs detalhados
docker-compose logs web

# Verificar se o banco está acessível
docker-compose exec web nc -zv db 5432
```

### Erro de conexão com banco de dados

```bash
# Reiniciar o banco de dados
docker-compose restart db

# Aguardar até que o health check passe
docker-compose ps
```

### Limpar e recomeçar

```bash
# ATENÇÃO: Isso apaga TODOS os dados
docker-compose down -v
docker-compose up -d
```

## 📊 Monitoramento

### Ver uso de recursos em tempo real

```bash
docker stats busca-ativa-web busca-ativa-db
```

### Logs estruturados

```bash
# Ver apenas erros
docker-compose logs web | grep ERROR

# Ver logs das últimas 100 linhas
docker-compose logs --tail=100 web
```

## 🔄 Atualização

Para atualizar a aplicação:

```bash
# 1. Fazer backup do banco
docker-compose exec db pg_dump -U buscaativa buscaativa_db > backup_$(date +%Y%m%d).sql

# 2. Parar os containers
docker-compose down

# 3. Atualizar código (git pull ou copiar novos arquivos)
git pull

# 4. Reconstruir e reiniciar
docker-compose up -d --build

# 5. Verificar logs
docker-compose logs -f web
```

## 📝 Variáveis de Ambiente Disponíveis

| Variável | Descrição | Padrão |
|----------|-----------|--------|
| `SECRET_KEY` | Chave secreta do Flask | - |
| `DATABASE_URL` | URL de conexão PostgreSQL | - |
| `EVOLUTION_API_URL` | URL da Evolution API | - |
| `EVOLUTION_API_KEY` | Chave de API | - |
| `EVOLUTION_INSTANCE` | Nome da instância | - |

## 🆘 Suporte

Em caso de problemas:

1. Verifique os logs: `docker-compose logs -f`
2. Verifique o status: `docker-compose ps`
3. Reinicie os serviços: `docker-compose restart`
4. Consulte a documentação do projeto no README.md principal
