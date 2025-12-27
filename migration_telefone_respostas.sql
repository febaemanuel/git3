-- Migration: Add response tracking fields to Telefones table
-- Purpose: Track individual responses from each phone number
-- Date: 2025-12-27

-- Add response tracking columns to Telefones table
ALTER TABLE telefones ADD COLUMN IF NOT EXISTS resposta TEXT;
ALTER TABLE telefones ADD COLUMN IF NOT EXISTS data_resposta TIMESTAMP;
ALTER TABLE telefones ADD COLUMN IF NOT EXISTS tipo_resposta VARCHAR(20); -- 'confirmado', 'rejeitado', 'desconheco', null
ALTER TABLE telefones ADD COLUMN IF NOT EXISTS validacao_pendente BOOLEAN DEFAULT FALSE; -- true if waiting for birth date validation

-- Add index for faster queries
CREATE INDEX IF NOT EXISTS idx_telefones_tipo_resposta ON telefones(tipo_resposta);
CREATE INDEX IF NOT EXISTS idx_telefones_data_resposta ON telefones(data_resposta);

-- Migrate existing response data from Contatos to Telefones
-- This will associate existing responses with the primary phone number
UPDATE telefones t
SET
    resposta = c.resposta,
    data_resposta = c.data_resposta,
    tipo_resposta = CASE
        WHEN c.confirmado = TRUE THEN 'confirmado'
        WHEN c.rejeitado = TRUE THEN 'rejeitado'
        ELSE NULL
    END
FROM contatos c
WHERE t.contato_id = c.id
    AND t.prioridade = 1  -- Only migrate to primary phone
    AND c.resposta IS NOT NULL;

-- Add comments for documentation
COMMENT ON COLUMN telefones.resposta IS 'Texto da resposta recebida deste número específico';
COMMENT ON COLUMN telefones.data_resposta IS 'Data/hora que este número enviou a resposta';
COMMENT ON COLUMN telefones.tipo_resposta IS 'Tipo de resposta: confirmado, rejeitado, desconheco, ou NULL se pendente';
COMMENT ON COLUMN telefones.validacao_pendente IS 'TRUE se aguardando validação da data de nascimento';
