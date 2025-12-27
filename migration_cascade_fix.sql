-- =====================================================
-- MIGRAÇÃO: Corrigir CASCADE DELETE em Foreign Keys
-- Data: 2025-11-27
-- Objetivo: Permitir exclusão de campanhas sem erros
-- =====================================================

-- 1. CONTATOS -> CAMPANHAS (CASCADE)
ALTER TABLE contatos
DROP CONSTRAINT IF EXISTS contatos_campanha_id_fkey;

ALTER TABLE contatos
ADD CONSTRAINT contatos_campanha_id_fkey
FOREIGN KEY (campanha_id) REFERENCES campanhas(id) ON DELETE CASCADE;

-- 2. TELEFONES -> CONTATOS (CASCADE)
ALTER TABLE telefones
DROP CONSTRAINT IF EXISTS telefones_contato_id_fkey;

ALTER TABLE telefones
ADD CONSTRAINT telefones_contato_id_fkey
FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE;

-- 3. LOGS -> CAMPANHAS (CASCADE)
ALTER TABLE logs
DROP CONSTRAINT IF EXISTS logs_campanha_id_fkey;

ALTER TABLE logs
ADD CONSTRAINT logs_campanha_id_fkey
FOREIGN KEY (campanha_id) REFERENCES campanhas(id) ON DELETE CASCADE;

-- 4. LOGS -> CONTATOS (CASCADE)
ALTER TABLE logs
DROP CONSTRAINT IF EXISTS logs_contato_id_fkey;

ALTER TABLE logs
ADD CONSTRAINT logs_contato_id_fkey
FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE;

-- 5. TICKETS_ATENDIMENTO -> CONTATOS (CASCADE)
ALTER TABLE tickets_atendimento
DROP CONSTRAINT IF EXISTS tickets_atendimento_contato_id_fkey;

ALTER TABLE tickets_atendimento
ADD CONSTRAINT tickets_atendimento_contato_id_fkey
FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE;

-- 6. TICKETS_ATENDIMENTO -> CAMPANHAS (CASCADE)
ALTER TABLE tickets_atendimento
DROP CONSTRAINT IF EXISTS tickets_atendimento_campanha_id_fkey;

ALTER TABLE tickets_atendimento
ADD CONSTRAINT tickets_atendimento_campanha_id_fkey
FOREIGN KEY (campanha_id) REFERENCES campanhas(id) ON DELETE CASCADE;

-- 7. TICKETS_ATENDIMENTO -> USUARIOS/ATENDENTE (SET NULL)
ALTER TABLE tickets_atendimento
DROP CONSTRAINT IF EXISTS tickets_atendimento_atendente_id_fkey;

ALTER TABLE tickets_atendimento
ADD CONSTRAINT tickets_atendimento_atendente_id_fkey
FOREIGN KEY (atendente_id) REFERENCES usuarios(id) ON DELETE SET NULL;

-- 8. TENTATIVAS_CONTATO -> CONTATOS (CASCADE)
ALTER TABLE tentativas_contato
DROP CONSTRAINT IF EXISTS tentativas_contato_contato_id_fkey;

ALTER TABLE tentativas_contato
ADD CONSTRAINT tentativas_contato_contato_id_fkey
FOREIGN KEY (contato_id) REFERENCES contatos(id) ON DELETE CASCADE;

-- 9. CAMPANHAS -> USUARIOS/CRIADOR (SET NULL)
ALTER TABLE campanhas
DROP CONSTRAINT IF EXISTS campanhas_criador_id_fkey;

ALTER TABLE campanhas
ADD CONSTRAINT campanhas_criador_id_fkey
FOREIGN KEY (criador_id) REFERENCES usuarios(id) ON DELETE SET NULL;

-- 10. RESPOSTAS_AUTOMATICAS -> USUARIOS/CRIADOR (SET NULL)
ALTER TABLE respostas_automaticas
DROP CONSTRAINT IF EXISTS respostas_automaticas_criador_id_fkey;

ALTER TABLE respostas_automaticas
ADD CONSTRAINT respostas_automaticas_criador_id_fkey
FOREIGN KEY (criador_id) REFERENCES usuarios(id) ON DELETE SET NULL;

-- =====================================================
-- VERIFICAÇÃO (opcional - executar para confirmar)
-- =====================================================
-- SELECT
--     tc.table_name,
--     kcu.column_name,
--     ccu.table_name AS foreign_table_name,
--     rc.delete_rule
-- FROM information_schema.table_constraints AS tc
-- JOIN information_schema.key_column_usage AS kcu
--   ON tc.constraint_name = kcu.constraint_name
-- JOIN information_schema.constraint_column_usage AS ccu
--   ON ccu.constraint_name = tc.constraint_name
-- JOIN information_schema.referential_constraints AS rc
--   ON rc.constraint_name = tc.constraint_name
-- WHERE tc.constraint_type = 'FOREIGN KEY'
--   AND tc.table_schema = 'public'
-- ORDER BY tc.table_name, kcu.column_name;

-- =====================================================
-- MIGRAÇÃO CONCLUÍDA
-- =====================================================
