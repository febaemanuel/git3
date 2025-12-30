-- Migração: Criar tabela telefones_consultas e migrar dados
-- Data: 2025-12-30
-- Descrição: Sistema de múltiplos telefones para consultas (igual fila cirúrgica)

-- 1. Criar tabela telefones_consultas
CREATE TABLE IF NOT EXISTS telefones_consultas (
    id SERIAL PRIMARY KEY,
    consulta_id INTEGER NOT NULL REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
    numero VARCHAR(20) NOT NULL,
    numero_fmt VARCHAR(20),
    whatsapp_valido BOOLEAN DEFAULT NULL,
    jid VARCHAR(50),
    data_validacao TIMESTAMP,
    enviado BOOLEAN DEFAULT FALSE,
    data_envio TIMESTAMP,
    msg_id VARCHAR(100),
    resposta TEXT,
    data_resposta TIMESTAMP,
    tipo_resposta VARCHAR(20),
    prioridade INTEGER DEFAULT 1
);

-- 2. Criar índices
CREATE INDEX IF NOT EXISTS idx_telefones_consultas_consulta_id ON telefones_consultas(consulta_id);
CREATE INDEX IF NOT EXISTS idx_telefones_consultas_numero ON telefones_consultas(numero);
CREATE INDEX IF NOT EXISTS idx_telefones_consultas_enviado ON telefones_consultas(enviado);

-- 3. Migrar dados existentes (telefone_cadas e telefone_regist)
-- Inserir telefone_cadas como prioridade 1
INSERT INTO telefones_consultas (consulta_id, numero, prioridade, enviado, data_envio)
SELECT
    id,
    telefone_cadas,
    1,
    mensagem_enviada,
    data_envio_mensagem
FROM agendamentos_consultas
WHERE telefone_cadas IS NOT NULL
  AND telefone_cadas != ''
  AND NOT EXISTS (
      SELECT 1 FROM telefones_consultas tc
      WHERE tc.consulta_id = agendamentos_consultas.id
      AND tc.numero = agendamentos_consultas.telefone_cadas
  );

-- Inserir telefone_regist como prioridade 2 (se diferente do cadas)
INSERT INTO telefones_consultas (consulta_id, numero, prioridade, enviado, data_envio)
SELECT
    id,
    telefone_regist,
    2,
    FALSE,
    NULL
FROM agendamentos_consultas
WHERE telefone_regist IS NOT NULL
  AND telefone_regist != ''
  AND telefone_regist != telefone_cadas
  AND NOT EXISTS (
      SELECT 1 FROM telefones_consultas tc
      WHERE tc.consulta_id = agendamentos_consultas.id
      AND tc.numero = agendamentos_consultas.telefone_regist
  );

-- 4. Mensagem de conclusão
DO $$
DECLARE
    total_telefones INTEGER;
    total_consultas INTEGER;
BEGIN
    SELECT COUNT(*) INTO total_telefones FROM telefones_consultas;
    SELECT COUNT(DISTINCT consulta_id) INTO total_consultas FROM telefones_consultas;

    RAISE NOTICE 'Migração concluída com sucesso!';
    RAISE NOTICE 'Total de telefones cadastrados: %', total_telefones;
    RAISE NOTICE 'Total de consultas com telefones: %', total_consultas;
END $$;
