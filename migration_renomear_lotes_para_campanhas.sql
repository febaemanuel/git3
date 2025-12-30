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

-- 3. Renomear usuario_id para criador_id e created_at para data_criacao
DO $$
BEGIN
    -- Renomear usuario_id para criador_id
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'usuario_id'
    ) THEN
        ALTER TABLE campanhas_consultas RENAME COLUMN usuario_id TO criador_id;
    END IF;

    -- Renomear created_at para data_criacao
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'created_at'
    ) THEN
        ALTER TABLE campanhas_consultas RENAME COLUMN created_at TO data_criacao;
    END IF;
END $$;

-- 4. Adicionar novos campos em campanhas_consultas
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

    -- Adicionar campo limite_diario (IGUAL à fila)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'limite_diario'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN limite_diario INTEGER DEFAULT 50;
    END IF;

    -- Adicionar campo dias_duracao (IGUAL à fila)
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'campanhas_consultas' AND column_name = 'dias_duracao'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN dias_duracao INTEGER DEFAULT 0;
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

-- 5. Atualizar índices
DROP INDEX IF EXISTS idx_lotes_usuario_id;
DROP INDEX IF EXISTS idx_lotes_status;
DROP INDEX IF EXISTS idx_agendamentos_lote_id;
DROP INDEX IF EXISTS idx_campanhas_usuario_id;

CREATE INDEX IF NOT EXISTS idx_campanhas_criador_id ON campanhas_consultas(criador_id);
CREATE INDEX IF NOT EXISTS idx_campanhas_status ON campanhas_consultas(status);
CREATE INDEX IF NOT EXISTS idx_agendamentos_campanha_id ON agendamentos_consultas(campanha_id);

-- Confirmação
SELECT 'Migração de lotes para campanhas concluída com sucesso!' AS status;
