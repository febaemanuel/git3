-- Adiciona coluna task_id na tabela campanhas para rastrear tasks Celery
-- Execute este script se estiver usando banco existente

ALTER TABLE campanhas ADD COLUMN IF NOT EXISTS task_id VARCHAR(100);

-- Verificar se foi adicionada
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'campanhas' AND column_name = 'task_id';
