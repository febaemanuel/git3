-- Script para alterar o modo do usuário admin de FILA para CONSULTA
-- Execute este script no seu banco de dados

-- 1. LISTAR usuários admin atuais
SELECT
    id,
    nome,
    email,
    tipo_sistema AS modo_atual,
    ativo,
    is_admin
FROM usuarios
WHERE is_admin = 1;

-- 2. ATUALIZAR todos os usuários admin para modo CONSULTA
-- Descomente a linha abaixo para executar a atualização:
-- UPDATE usuarios SET tipo_sistema = 'AGENDAMENTO_CONSULTA' WHERE is_admin = 1;

-- 3. OU se quiser atualizar um usuário específico por EMAIL:
-- UPDATE usuarios SET tipo_sistema = 'AGENDAMENTO_CONSULTA' WHERE email = 'seu_email@exemplo.com';

-- 4. OU se quiser atualizar um usuário específico por ID:
-- UPDATE usuarios SET tipo_sistema = 'AGENDAMENTO_CONSULTA' WHERE id = 1;

-- 5. VERIFICAR a alteração
SELECT
    id,
    nome,
    email,
    tipo_sistema AS modo_atual,
    ativo,
    is_admin
FROM usuarios
WHERE is_admin = 1;
