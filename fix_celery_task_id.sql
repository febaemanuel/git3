-- =====================================================
-- FIX: Adicionar coluna celery_task_id faltante
-- =====================================================
-- Corrige erro: column campanhas_consultas.celery_task_id does not exist

-- Adicionar coluna celery_task_id se não existir
ALTER TABLE campanhas_consultas
ADD COLUMN IF NOT EXISTS celery_task_id VARCHAR(100);

-- Verificar se foi adicionada
SELECT column_name, data_type, character_maximum_length
FROM information_schema.columns
WHERE table_name = 'campanhas_consultas' AND column_name = 'celery_task_id';

-- Mensagem de sucesso
SELECT '✓ Coluna celery_task_id adicionada com sucesso!' as status;
