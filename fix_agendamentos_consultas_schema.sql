-- =====================================================
-- FIX COMPLETO: Schema de agendamentos_consultas
-- =====================================================
-- Adiciona TODAS as colunas faltantes conforme modelo Python

-- Dados da planilha
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS posicao VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS cod_master VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS codigo_aghu VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS paciente VARCHAR(200);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS telefone_cadastro VARCHAR(20);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS telefone_registro VARCHAR(20);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_registro VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS procedencia VARCHAR(200);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS medico_solicitante VARCHAR(200);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS tipo VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS observacoes TEXT;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS exames TEXT;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS sub_especialidade VARCHAR(200);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS especialidade VARCHAR(200);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS grade_aghu VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS prioridade VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS indicacao_data VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_requisicao VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_exata_ou_dias VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS estimativa_agendamento VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_aghu VARCHAR(50);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS paciente_voltar_posto_sms VARCHAR(10);

-- Controle de status
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS status VARCHAR(50) DEFAULT 'AGUARDANDO_ENVIO';
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS mensagem_enviada BOOLEAN DEFAULT FALSE;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_envio_mensagem TIMESTAMP;

-- Comprovante
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS comprovante_path VARCHAR(255);
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS comprovante_nome VARCHAR(255);

-- Rejeição
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS motivo_rejeicao TEXT;

-- Timestamps
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_confirmacao TIMESTAMP;
ALTER TABLE agendamentos_consultas ADD COLUMN IF NOT EXISTS data_rejeicao TIMESTAMP;

-- Verificação final
SELECT
    COUNT(*) as total_colunas,
    'agendamentos_consultas' as tabela
FROM information_schema.columns
WHERE table_name = 'agendamentos_consultas';

SELECT '✓ Schema corrigido com sucesso!' as status;
