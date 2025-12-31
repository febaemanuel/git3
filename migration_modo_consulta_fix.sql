-- =====================================================
-- CORREÇÃO: Migration Modo Consulta
-- =====================================================
-- Adiciona campos faltantes

-- 1. Adicionar campo motivo_rejeicao se não existir
ALTER TABLE agendamentos_consultas
ADD COLUMN IF NOT EXISTS motivo_rejeicao TEXT;

COMMENT ON COLUMN agendamentos_consultas.motivo_rejeicao IS 'Motivo informado pelo paciente quando rejeita a consulta';

-- 2. Ajustar valor padrão de tipo_sistema (BUSCA_ATIVA em vez de FILA_CIRURGICA)
ALTER TABLE usuarios
ALTER COLUMN tipo_sistema SET DEFAULT 'BUSCA_ATIVA';

-- 3. Atualizar usuários existentes que têm FILA_CIRURGICA para BUSCA_ATIVA
UPDATE usuarios
SET tipo_sistema = 'BUSCA_ATIVA'
WHERE tipo_sistema = 'FILA_CIRURGICA' OR tipo_sistema IS NULL;

-- Verificação
SELECT 'Correção aplicada com sucesso!' as status;

SELECT COUNT(*) as total_usuarios, tipo_sistema
FROM usuarios
GROUP BY tipo_sistema;
