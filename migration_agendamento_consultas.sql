-- ============================================================================
-- MIGRATION: Agendamento de Consultas
-- Data: 2025-12-30
-- Descrição: Adiciona tabela de agendamento de consultas e campo tipo_sistema
-- ============================================================================

-- 1. Adicionar campo tipo_sistema na tabela usuarios
-- (se já existir, ignora o erro)
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'usuarios' AND column_name = 'tipo_sistema'
    ) THEN
        ALTER TABLE usuarios ADD COLUMN tipo_sistema VARCHAR(50) DEFAULT 'FILA_CIRURGICA';
    END IF;
END $$;

-- 2. Criar tabela lotes_consultas
CREATE TABLE IF NOT EXISTS lotes_consultas (
    id SERIAL PRIMARY KEY,
    nome VARCHAR(200) NOT NULL,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    tipo VARCHAR(50),  -- RETORNO ou INTERCONSULTA

    -- Configurações de envio
    meta_diaria INTEGER DEFAULT 50,
    hora_inicio INTEGER DEFAULT 8,
    hora_fim INTEGER DEFAULT 18,
    tempo_entre_envios INTEGER DEFAULT 15,  -- segundos

    -- Controle diário
    enviados_hoje INTEGER DEFAULT 0,
    data_ultimo_envio DATE,

    -- Status
    status VARCHAR(50) DEFAULT 'pendente',
    -- pendente, enviando, pausado, concluido

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_inicio TIMESTAMP,
    data_fim TIMESTAMP
);

-- 3. Criar tabela agendamentos_consultas
CREATE TABLE IF NOT EXISTS agendamentos_consultas (
    id SERIAL PRIMARY KEY,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    lote_id INTEGER REFERENCES lotes_consultas(id) ON DELETE SET NULL,

    -- Dados da planilha
    pasta VARCHAR(50),
    od_maste VARCHAR(50),
    codigo_agh VARCHAR(50),
    paciente VARCHAR(200) NOT NULL,
    telefone_cadas VARCHAR(20),
    telefone_regist VARCHAR(20),
    tipo VARCHAR(50) NOT NULL,  -- RETORNO ou INTERCONSULTA

    -- Dados da consulta
    sub_especialidade VARCHAR(200),
    especialidade VARCHAR(200),
    grade VARCHAR(50),
    prioridade VARCHAR(50),
    data_aghu VARCHAR(50),  -- Data da consulta
    hora_consulta VARCHAR(10),  -- Hora da consulta
    dia_semana VARCHAR(20),
    unidade_funcional VARCHAR(200),
    profissional VARCHAR(200),

    -- Campo específico para INTERCONSULTA
    paciente_voltar_posto_sms VARCHAR(10),  -- SIM ou NÃO

    -- Controle de status
    status VARCHAR(50) DEFAULT 'AGUARDANDO_CONFIRMACAO',
    -- Status: AGUARDANDO_CONFIRMACAO, AGUARDANDO_COMPROVANTE, CONFIRMADO, CANCELADO, REJEITADO

    -- Controle de envio de mensagens
    mensagem_enviada BOOLEAN DEFAULT FALSE,
    data_envio_mensagem TIMESTAMP,

    -- Comprovante
    comprovante_path VARCHAR(255),

    -- Observações
    observacoes TEXT,

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_confirmacao TIMESTAMP,
    data_cancelamento TIMESTAMP
);

-- 4. Criar índices para melhor performance
CREATE INDEX IF NOT EXISTS idx_lotes_usuario_id ON lotes_consultas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_lotes_status ON lotes_consultas(status);

CREATE INDEX IF NOT EXISTS idx_agendamentos_usuario_id ON agendamentos_consultas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_agendamentos_lote_id ON agendamentos_consultas(lote_id);
CREATE INDEX IF NOT EXISTS idx_agendamentos_status ON agendamentos_consultas(status);
CREATE INDEX IF NOT EXISTS idx_agendamentos_tipo ON agendamentos_consultas(tipo);
CREATE INDEX IF NOT EXISTS idx_agendamentos_created_at ON agendamentos_consultas(created_at);
CREATE INDEX IF NOT EXISTS idx_agendamentos_mensagem_enviada ON agendamentos_consultas(mensagem_enviada);

-- 4. Criar função de trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_agendamentos_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

-- 5. Criar trigger
DROP TRIGGER IF EXISTS trigger_update_agendamentos_updated_at ON agendamentos_consultas;
CREATE TRIGGER trigger_update_agendamentos_updated_at
    BEFORE UPDATE ON agendamentos_consultas
    FOR EACH ROW
    EXECUTE FUNCTION update_agendamentos_updated_at();

-- Confirmação
SELECT 'Migration completed successfully!' AS status;
