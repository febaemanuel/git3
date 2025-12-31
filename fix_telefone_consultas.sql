-- =====================================================================
-- Script para corrigir números de telefone sem código do país (55)
-- =====================================================================
-- Este script adiciona o código 55 aos números que têm 10 ou 11 dígitos
-- e ainda não começam com 55
-- =====================================================================

-- Atualizar números na tabela telefone_consulta
UPDATE telefone_consulta
SET numero = '55' || numero
WHERE
    numero IS NOT NULL
    AND numero != ''
    AND numero NOT LIKE '55%'
    AND (
        LENGTH(numero) = 10  -- DDD (2) + Telefone (8)
        OR LENGTH(numero) = 11  -- DDD (2) + Celular (9)
    );

-- Atualizar telefone_cadastro na tabela agendamento_consulta
UPDATE agendamento_consulta
SET telefone_cadastro = '55' || telefone_cadastro
WHERE
    telefone_cadastro IS NOT NULL
    AND telefone_cadastro != ''
    AND telefone_cadastro NOT LIKE '55%'
    AND (
        LENGTH(telefone_cadastro) = 10
        OR LENGTH(telefone_cadastro) = 11
    );

-- Atualizar telefone_registro na tabela agendamento_consulta
UPDATE agendamento_consulta
SET telefone_registro = '55' || telefone_registro
WHERE
    telefone_registro IS NOT NULL
    AND telefone_registro != ''
    AND telefone_registro NOT LIKE '55%'
    AND (
        LENGTH(telefone_registro) = 10
        OR LENGTH(telefone_registro) = 11
    );

-- Verificar resultados
SELECT 'Telefones corrigidos na tabela telefone_consulta:' as info, COUNT(*) as total
FROM telefone_consulta
WHERE numero LIKE '55%';

SELECT 'Total de consultas:' as info, COUNT(*) as total
FROM agendamento_consulta;
