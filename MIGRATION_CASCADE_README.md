# Correção de Foreign Keys - CASCADE DELETE

## Problema Resolvido

Ao tentar excluir uma campanha, o sistema retornava erro:
```
ForeignKeyViolation: update or delete on table "contatos" violates foreign key constraint "logs_contato_id_fkey" on table "logs"
```

Isso acontecia porque as foreign keys não tinham `ON DELETE CASCADE` configurado.

## Correções Aplicadas

### 1. Modelos Python (app.py) ✅

Todas as foreign keys foram atualizadas nos modelos:

**CASCADE DELETE** (quando pai é excluído, filho também é excluído):
- `Contato.campanha_id` → `campanhas.id`
- `Telefone.contato_id` → `contatos.id`
- `LogMsg.campanha_id` → `campanhas.id`
- `LogMsg.contato_id` → `contatos.id`
- `TicketAtendimento.contato_id` → `contatos.id`
- `TicketAtendimento.campanha_id` → `campanhas.id`
- `TentativaContato.contato_id` → `contatos.id`

**SET NULL** (quando pai é excluído, FK do filho vira NULL):
- `Campanha.criador_id` → `usuarios.id`
- `RespostaAutomatica.criador_id` → `usuarios.id`
- `TicketAtendimento.atendente_id` → `usuarios.id`

### 2. Migration SQL (migration_cascade_fix.sql) ✅

Arquivo criado com comandos ALTER TABLE para atualizar constraints existentes.

## Como Aplicar a Migration

### Opção 1: Via Docker (RECOMENDADO)

```bash
# Copiar arquivo SQL para o container
docker cp migration_cascade_fix.sql busca-ativa-db:/tmp/

# Executar migration
docker exec -i busca-ativa-db psql -U buscaativa -d buscaativa_db -f /tmp/migration_cascade_fix.sql

# Verificar se funcionou
docker exec -i busca-ativa-db psql -U buscaativa -d buscaativa_db -c "
SELECT
    tc.table_name,
    kcu.column_name,
    ccu.table_name AS foreign_table,
    rc.delete_rule
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.referential_constraints AS rc
  ON rc.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
ORDER BY tc.table_name, kcu.column_name;
"
```

### Opção 2: Via psql Direto

```bash
psql -U buscaativa -d buscaativa_db -f migration_cascade_fix.sql
```

### Opção 3: Recriando o Banco (se for ambiente de desenvolvimento)

```bash
# ATENÇÃO: Isso apaga todos os dados!
docker-compose down
docker volume rm busca-ativa_postgres_data
docker-compose up -d
```

## Verificar se a Migration foi Aplicada

Execute este comando para ver as regras de DELETE de todas as foreign keys:

```bash
docker exec -i busca-ativa-db psql -U buscaativa -d buscaativa_db -c "
SELECT
    tc.table_name AS tabela,
    kcu.column_name AS coluna,
    ccu.table_name AS referencia,
    rc.delete_rule AS delete_rule
FROM information_schema.table_constraints AS tc
JOIN information_schema.key_column_usage AS kcu
  ON tc.constraint_name = kcu.constraint_name
JOIN information_schema.constraint_column_usage AS ccu
  ON ccu.constraint_name = tc.constraint_name
JOIN information_schema.referential_constraints AS rc
  ON rc.constraint_name = tc.constraint_name
WHERE tc.constraint_type = 'FOREIGN KEY'
  AND tc.table_schema = 'public'
  AND tc.table_name IN ('contatos', 'telefones', 'logs', 'tickets_atendimento', 'tentativas_contato', 'campanhas', 'respostas_automaticas')
ORDER BY tc.table_name, kcu.column_name;
"
```

Você deve ver:
- `CASCADE` para as relações campanha→contato→telefone→logs→tickets→tentativas
- `SET NULL` para criador_id e atendente_id

## Testar a Correção

Após aplicar a migration:

1. Acesse o sistema
2. Crie uma campanha de teste
3. Adicione alguns contatos
4. Tente excluir a campanha
5. **Deve funcionar sem erros!** ✅

## Ordem de Exclusão (CASCADE)

Quando você excluir uma **Campanha**, o sistema automaticamente excluirá em cascata:

```
Campanha
  └─> Contatos (CASCADE)
       ├─> Telefones (CASCADE)
       ├─> Logs (CASCADE)
       ├─> Tickets de Atendimento (CASCADE)
       └─> Tentativas de Contato (CASCADE)
```

## Observações Importantes

1. **Backup**: Sempre faça backup antes de aplicar migrations em produção
2. **Rollback**: Se precisar reverter, basta remover o `ON DELETE CASCADE/SET NULL` das constraints
3. **Desempenho**: Exclusões em cascata podem ser lentas se houver muitos registros relacionados
4. **Log**: O PostgreSQL vai logar todas as exclusões em cascata

## Arquivos Modificados

- ✅ `app.py` - Modelos atualizados com ondelete
- ✅ `migration_cascade_fix.sql` - Script SQL para atualizar constraints
- ✅ `MIGRATION_CASCADE_README.md` - Esta documentação
