-- =====================================================================
-- MIGRAÇÃO DO BANCO - SISTEMA DE CONSULTAS
-- =====================================================================
-- Adiciona campos novos que podem estar faltando
-- Este script é IDEMPOTENT (pode rodar múltiplas vezes sem problemas)
-- =====================================================================

-- Adicionar campo status_msg na tabela campanhas_consultas (se não existir)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='campanhas_consultas' AND column_name='status_msg'
    ) THEN
        ALTER TABLE campanhas_consultas ADD COLUMN status_msg VARCHAR(255);
        RAISE NOTICE 'Campo status_msg adicionado à tabela campanhas_consultas';
    ELSE
        RAISE NOTICE 'Campo status_msg já existe em campanhas_consultas';
    END IF;
END $$;

-- Verificar e exibir informações das tabelas
SELECT
    'campanhas_consultas' as tabela,
    COUNT(*) as total_registros
FROM campanhas_consultas
UNION ALL
SELECT
    'agendamentos_consultas' as tabela,
    COUNT(*) as total_registros
FROM agendamentos_consultas
UNION ALL
SELECT
    'telefones_consultas' as tabela,
    COUNT(*) as total_registros
FROM telefones_consultas
UNION ALL
SELECT
    'logs_msgs_consultas' as tabela,
    COUNT(*) as total_registros
FROM logs_msgs_consultas;

-- Verificar estrutura da tabela campanhas_consultas
SELECT
    column_name,
    data_type,
    character_maximum_length,
    column_default,
    is_nullable
FROM information_schema.columns
WHERE table_name = 'campanhas_consultas'
ORDER BY ordinal_position;
