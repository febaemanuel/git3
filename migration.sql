-- =====================================================
-- MIGRAÇÃO: Sistema Simplificado WhatsApp
-- =====================================================

-- 1. CRIAR TABELA config_global
CREATE TABLE IF NOT EXISTS config_global (
    id SERIAL PRIMARY KEY,
    evolution_api_url VARCHAR(200),
    evolution_api_key VARCHAR(200),
    ativo BOOLEAN DEFAULT FALSE,
    atualizado_em TIMESTAMP DEFAULT NOW(),
    atualizado_por INTEGER REFERENCES usuarios(id)
);

-- Inserir registro inicial
INSERT INTO config_global (ativo)
SELECT FALSE
WHERE NOT EXISTS (SELECT 1 FROM config_global);

-- 2. ADICIONAR COLUNAS À tabela respostas_automaticas (FAQ)
ALTER TABLE respostas_automaticas
ADD COLUMN IF NOT EXISTS criador_id INTEGER REFERENCES usuarios(id);

ALTER TABLE respostas_automaticas
ADD COLUMN IF NOT EXISTS global_faq BOOLEAN DEFAULT FALSE;

-- Marcar FAQs existentes como globais
UPDATE respostas_automaticas
SET global_faq = TRUE
WHERE criador_id IS NULL;

-- 3. ADICIONAR COLUNAS À tabela contatos (Procedimento Normalizado)
ALTER TABLE contatos
ADD COLUMN IF NOT EXISTS procedimento_normalizado VARCHAR(300);

-- 4. CRIAR TABELA procedimentos_normalizados (Cache AI)
CREATE TABLE IF NOT EXISTS procedimentos_normalizados (
    id SERIAL PRIMARY KEY,
    termo_original VARCHAR(300) UNIQUE NOT NULL,
    termo_normalizado VARCHAR(300),
    termo_simples VARCHAR(200),
    explicacao TEXT,
    usado_count INTEGER DEFAULT 0,
    criado_em TIMESTAMP DEFAULT NOW(),
    atualizado_em TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_proc_norm_original ON procedimentos_normalizados(termo_original);

-- 5. MODIFICAR TABELA config_whatsapp
-- Primeiro, adicionar usuario_id (permitir NULL temporariamente)
ALTER TABLE config_whatsapp
ADD COLUMN IF NOT EXISTS usuario_id INTEGER REFERENCES usuarios(id);

-- Adicionar novos campos
ALTER TABLE config_whatsapp
ADD COLUMN IF NOT EXISTS conectado BOOLEAN DEFAULT FALSE;

ALTER TABLE config_whatsapp
ADD COLUMN IF NOT EXISTS data_conexao TIMESTAMP;

-- Gerar instance_name se não existir
UPDATE config_whatsapp
SET instance_name = 'hospital_legacy'
WHERE instance_name IS NULL OR instance_name = '';

-- Associar config existente ao primeiro usuário admin
UPDATE config_whatsapp
SET usuario_id = (SELECT id FROM usuarios WHERE is_admin = TRUE ORDER BY id LIMIT 1)
WHERE usuario_id IS NULL;

-- Se não tiver admin, associar ao primeiro usuário
UPDATE config_whatsapp
SET usuario_id = (SELECT id FROM usuarios ORDER BY id LIMIT 1)
WHERE usuario_id IS NULL;

-- Agora tornar usuario_id obrigatório e único
ALTER TABLE config_whatsapp
ALTER COLUMN usuario_id SET NOT NULL;

ALTER TABLE config_whatsapp
ADD CONSTRAINT config_whatsapp_usuario_id_unique UNIQUE (usuario_id);

-- Remover campos antigos que não são mais usados
ALTER TABLE config_whatsapp DROP COLUMN IF EXISTS api_url;
ALTER TABLE config_whatsapp DROP COLUMN IF EXISTS api_key;
ALTER TABLE config_whatsapp DROP COLUMN IF EXISTS ativo;

-- =====================================================
-- MIGRAÇÃO CONCLUÍDA
-- =====================================================
