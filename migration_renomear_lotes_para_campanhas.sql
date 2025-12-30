-- ============================================================================
-- MIGRATION: Renomear Lotes para Campanhas de Consultas
-- Data: 2025-12-30
-- Descrição: Renomeia tabelas e campos de "lote" para "campanha" e adiciona novos campos
-- ============================================================================

-- 1. Renomear tabela lotes_consultas para campanhas_consultas
ALTER TABLE IF EXISTS lotes_consultas RENAME TO campanhas_consultas;

-- 2. Renomear coluna lote_id para campanha_id em agendamentos_consultas
ALTER TABLE IF EXISTS agendamentos_consultas
    RENAME COLUMN lote_id TO campanha_id;

-- 3. Adicionar novos campos em campanhas_consultas
DO $$
BEGIN
    -- Adicionar campo descricao
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'descricao'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN descricao TEXT;
    END IF;

    -- Adicionar campo arquivo
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'arquivo'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN arquivo VARCHAR(255);
    END IF;

    -- Adicionar campo status_msg
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'status_msg'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN status_msg VARCHAR(255);
    END IF;

    -- Adicionar campo task_id
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'task_id'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN task_id VARCHAR(100);
    END IF;

    -- Adicionar campos de estatísticas
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_consultas'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_consultas INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_enviados'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_enviados INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_confirmados'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_confirmados INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_aguardando_comprovante'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_aguardando_comprovante INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_cancelados'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_cancelados INTEGER DEFAULT 0;
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'total_rejeitados'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN total_rejeitados INTEGER DEFAULT 0;
    END IF;
END $$;

-- 4. Atualizar índices
DROP INDEX IF EXISTS idx_lotes_usuario_id;
DROP INDEX IF EXISTS idx_lotes_status;
DROP INDEX IF EXISTS idx_agendamentos_lote_id;

CREATE INDEX IF NOT EXISTS idx_campanhas_usuario_id ON campanhas_consultas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_campanhas_status ON campanhas_consultas(status);
CREATE INDEX IF NOT EXISTS idx_agendamentos_campanha_id ON agendamentos_consultas(campanha_id);

-- Confirmação
SELECT 'Migração de lotes para campanhas concluída com sucesso!' AS status;
