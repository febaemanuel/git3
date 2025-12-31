-- =====================================================
-- MIGRAÇÃO: MODO CONSULTA - Agendamento de Consultas
-- =====================================================
-- Data: 2025-01-01
-- Descrição: Criação de tabelas para o sistema de agendamento de consultas
-- Mantém intacto o sistema de fila cirúrgica (BUSCA_ATIVA)
-- =====================================================

-- 1. ADICIONAR CAMPO tipo_sistema NA TABELA usuarios
-- =====================================================
ALTER TABLE usuarios
ADD COLUMN IF NOT EXISTS tipo_sistema VARCHAR(50) DEFAULT 'BUSCA_ATIVA';

-- Criar índice para consultas rápidas
CREATE INDEX IF NOT EXISTS idx_usuarios_tipo_sistema ON usuarios(tipo_sistema);

COMMENT ON COLUMN usuarios.tipo_sistema IS 'Tipo de sistema: BUSCA_ATIVA (Fila Cirúrgica) ou AGENDAMENTO_CONSULTA (Consultas)';


-- 2. CRIAR TABELA campanhas_consultas
-- =====================================================
CREATE TABLE IF NOT EXISTS campanhas_consultas (
    id SERIAL PRIMARY KEY,
    criador_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,
    nome VARCHAR(200) NOT NULL,
    descricao TEXT,
    status VARCHAR(50) DEFAULT 'pendente',
    -- Status: pendente, enviando, pausado, concluido, erro

    -- Configurações de envio (mesmas da fila cirúrgica)
    meta_diaria INTEGER DEFAULT 50,
    hora_inicio INTEGER DEFAULT 8,
    hora_fim INTEGER DEFAULT 23,
    tempo_entre_envios INTEGER DEFAULT 15,
    dias_duracao INTEGER DEFAULT 0,

    -- Controle diário
    enviados_hoje INTEGER DEFAULT 0,
    data_ultimo_envio DATE,

    -- Estatísticas
    total_consultas INTEGER DEFAULT 0,
    total_enviados INTEGER DEFAULT 0,
    total_confirmados INTEGER DEFAULT 0,
    total_aguardando_comprovante INTEGER DEFAULT 0,
    total_rejeitados INTEGER DEFAULT 0,

    -- Timestamps
    data_criacao TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_inicio TIMESTAMP,
    data_fim TIMESTAMP,

    -- Task ID do Celery
    celery_task_id VARCHAR(100)
);

CREATE INDEX IF NOT EXISTS idx_campanhas_consultas_criador ON campanhas_consultas(criador_id);
CREATE INDEX IF NOT EXISTS idx_campanhas_consultas_status ON campanhas_consultas(status);

COMMENT ON TABLE campanhas_consultas IS 'Campanhas de agendamento de consultas (separado da fila cirúrgica)';


-- 3. CRIAR TABELA agendamentos_consultas
-- =====================================================
CREATE TABLE IF NOT EXISTS agendamentos_consultas (
    id SERIAL PRIMARY KEY,
    campanha_id INTEGER REFERENCES campanhas_consultas(id) ON DELETE CASCADE,
    usuario_id INTEGER REFERENCES usuarios(id) ON DELETE SET NULL,

    -- Dados da planilha (TODAS as colunas conforme especificação)
    posicao VARCHAR(50),
    cod_master VARCHAR(50),
    codigo_aghu VARCHAR(50),
    paciente VARCHAR(200) NOT NULL,
    telefone_cadastro VARCHAR(20),
    telefone_registro VARCHAR(20),
    data_registro VARCHAR(50),
    procedencia VARCHAR(200),
    medico_solicitante VARCHAR(200),
    tipo VARCHAR(50) NOT NULL,  -- RETORNO ou INTERCONSULTA
    observacoes TEXT,
    exames TEXT,
    sub_especialidade VARCHAR(200),
    especialidade VARCHAR(200),
    grade_aghu VARCHAR(50),
    prioridade VARCHAR(50),
    indicacao_data VARCHAR(50),
    data_requisicao VARCHAR(50),
    data_exata_ou_dias VARCHAR(50),
    estimativa_agendamento VARCHAR(50),
    data_aghu VARCHAR(50),  -- Data da consulta

    -- Campo específico para INTERCONSULTA
    paciente_voltar_posto_sms VARCHAR(10),  -- SIM ou NÃO

    -- Controle de status do fluxo
    status VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO',
    -- Fluxo: AGUARDANDO_ENVIO → AGUARDANDO_CONFIRMACAO → AGUARDANDO_COMPROVANTE → CONFIRMADO
    --                                                   → AGUARDANDO_MOTIVO_REJEICAO → REJEITADO

    mensagem_enviada BOOLEAN DEFAULT FALSE,
    data_envio_mensagem TIMESTAMP,

    -- Comprovante (PDF/JPG)
    comprovante_path VARCHAR(255),
    comprovante_nome VARCHAR(255),

    -- Rejeição
    motivo_rejeicao TEXT,  -- Armazena o motivo quando paciente rejeita

    -- Timestamps
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    data_confirmacao TIMESTAMP,
    data_rejeicao TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_agendamentos_consultas_campanha ON agendamentos_consultas(campanha_id);
CREATE INDEX IF NOT EXISTS idx_agendamentos_consultas_usuario ON agendamentos_consultas(usuario_id);
CREATE INDEX IF NOT EXISTS idx_agendamentos_consultas_status ON agendamentos_consultas(status);
CREATE INDEX IF NOT EXISTS idx_agendamentos_consultas_tipo ON agendamentos_consultas(tipo);

COMMENT ON TABLE agendamentos_consultas IS 'Agendamentos individuais de consultas com dados completos da planilha';
COMMENT ON COLUMN agendamentos_consultas.tipo IS 'RETORNO (paciente retorna) ou INTERCONSULTA (encaminhado)';
COMMENT ON COLUMN agendamentos_consultas.paciente_voltar_posto_sms IS 'Se SIM, envia MSG 3B quando rejeitado (apenas INTERCONSULTA)';
COMMENT ON COLUMN agendamentos_consultas.motivo_rejeicao IS 'Motivo informado pelo paciente quando rejeita a consulta';


-- 4. CRIAR TABELA telefones_consultas
-- =====================================================
CREATE TABLE IF NOT EXISTS telefones_consultas (
    id SERIAL PRIMARY KEY,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
    numero VARCHAR(20) NOT NULL,
    prioridade INTEGER DEFAULT 1,  -- 1 = telefone_cadastro, 2 = telefone_registro
    enviado BOOLEAN DEFAULT FALSE,
    data_envio TIMESTAMP,
    msg_id VARCHAR(100),  -- ID da mensagem na Evolution API
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_telefones_consultas_consulta ON telefones_consultas(consulta_id);
CREATE INDEX IF NOT EXISTS idx_telefones_consultas_numero ON telefones_consultas(numero);

COMMENT ON TABLE telefones_consultas IS 'Telefones de cada consulta (cadastro e registro)';


-- 5. CRIAR TABELA logs_msgs_consultas
-- =====================================================
CREATE TABLE IF NOT EXISTS logs_msgs_consultas (
    id SERIAL PRIMARY KEY,
    campanha_id INTEGER REFERENCES campanhas_consultas(id) ON DELETE CASCADE,
    consulta_id INTEGER REFERENCES agendamentos_consultas(id) ON DELETE CASCADE,
    direcao VARCHAR(20) NOT NULL,  -- 'enviada' ou 'recebida'
    telefone VARCHAR(20) NOT NULL,
    mensagem TEXT,
    status VARCHAR(20),  -- 'sucesso' ou 'erro'
    erro TEXT,
    msg_id VARCHAR(100),  -- ID da mensagem na Evolution API
    data TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_logs_msgs_consultas_campanha ON logs_msgs_consultas(campanha_id);
CREATE INDEX IF NOT EXISTS idx_logs_msgs_consultas_consulta ON logs_msgs_consultas(consulta_id);
CREATE INDEX IF NOT EXISTS idx_logs_msgs_consultas_telefone ON logs_msgs_consultas(telefone);
CREATE INDEX IF NOT EXISTS idx_logs_msgs_consultas_data ON logs_msgs_consultas(data);

COMMENT ON TABLE logs_msgs_consultas IS 'Log de todas as mensagens enviadas e recebidas nas campanhas de consultas';


-- =====================================================
-- TRIGGERS PARA updated_at
-- =====================================================

-- Trigger para atualizar updated_at automaticamente
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Aplicar trigger na tabela agendamentos_consultas
DROP TRIGGER IF EXISTS update_agendamentos_consultas_updated_at ON agendamentos_consultas;
CREATE TRIGGER update_agendamentos_consultas_updated_at
    BEFORE UPDATE ON agendamentos_consultas
    FOR EACH ROW
    EXECUTE FUNCTION update_updated_at_column();


-- =====================================================
-- VERIFICAÇÃO FINAL
-- =====================================================

-- Listar tabelas criadas
SELECT
    tablename,
    schemaname
FROM pg_tables
WHERE tablename IN (
    'campanhas_consultas',
    'agendamentos_consultas',
    'telefones_consultas',
    'logs_msgs_consultas'
)
ORDER BY tablename;

-- Verificar campo tipo_sistema em usuarios
SELECT column_name, data_type, column_default
FROM information_schema.columns
WHERE table_name = 'usuarios' AND column_name = 'tipo_sistema';

-- =====================================================
-- MIGRAÇÃO CONCLUÍDA
-- =====================================================
-- IMPORTANTE: Este script NÃO altera nada da fila cirúrgica!
-- Todas as tabelas existentes (campanhas, contatos, telefones, logs_msgs, etc.)
-- permanecem INTACTAS.
-- =====================================================
