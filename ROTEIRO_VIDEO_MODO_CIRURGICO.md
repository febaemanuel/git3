# Roteiro para Vídeo Explicativo - Modo Cirúrgico (Fila Cirúrgica)
## Sistema Busca Ativa - HUWC

---

## O QUE É O SISTEMA

O Busca Ativa é um sistema do Hospital Universitário Walter Cantídio (HUWC) que automatiza o contato com pacientes da fila cirúrgica via WhatsApp. O objetivo é confirmar se o paciente ainda tem interesse em realizar a cirurgia, liberando vagas para quem realmente precisa.

---

## COMO FUNCIONA - PASSO A PASSO

### 1. Configuração Inicial (feita uma vez)

- O usuário acessa o sistema pelo navegador e faz login
- Na aba **Configurações > WhatsApp**, o sistema cria automaticamente uma instância do WhatsApp
- O usuário escaneia o QR Code com o celular para conectar o WhatsApp
- Um indicador verde na tela mostra que o WhatsApp está online e pronto para uso

### 2. Criando uma Campanha

- No **Dashboard**, o usuário clica em "Nova Campanha"
- Ele preenche:
  - **Nome da campanha** (exemplo: "Fila Ortopedia Março 2026")
  - **Mensagem personalizada** — ou usa a mensagem padrão do sistema
  - **Planilha Excel** com os dados dos pacientes: nome, telefone, procedimento e data de nascimento
  - **Meta diária** — quantas mensagens enviar por dia (padrão: 100)
  - **Horário de funcionamento** — horário de início e fim dos envios (ex: 8h às 18h)
  - **Intervalo entre envios** — tempo entre cada mensagem (padrão: 15 segundos)
  - **Duração** — quantidade de dias que a campanha ficará ativa

### 3. Validação dos Números

- Antes de enviar, o sistema **valida automaticamente** se os telefones da planilha possuem WhatsApp
- O sistema testa cada número e marca como válido ou inválido
- Pacientes com número inválido não recebem mensagem, evitando desperdício

### 4. Envio das Mensagens

- Ao clicar em "Iniciar Campanha", o sistema começa a enviar as mensagens automaticamente
- A mensagem padrão enviada é:

> 📋 Olá, [nome do paciente]!
>
> Aqui é da Central de Agendamentos do Hospital Universitário Walter Cantídio.
>
> Consta em nossos registros que você está na lista de espera para o procedimento: [nome do procedimento].
>
> Você ainda tem interesse em realizar esta cirurgia?
>
> 1️⃣ SIM - Tenho interesse
> 2️⃣ NÃO - Não tenho mais interesse
> 3️⃣ DESCONHEÇO - Não sou essa pessoa

- O sistema respeita a meta diária e os horários configurados
- Uma barra de progresso mostra quantos contatos já foram processados

### 5. Recebendo as Respostas

- Quando o paciente responde pelo WhatsApp, o sistema processa automaticamente:
  - **"SIM" ou "1"** → Paciente marcado como **Confirmado** (quer a cirurgia)
  - **"NÃO" ou "2"** → Paciente marcado como **Rejeitado** (não quer mais)
  - **"DESCONHEÇO" ou "3"** → Número não pertence ao paciente
- As respostas aparecem em tempo real no painel da campanha

### 6. Follow-up Automático (Tentativas para quem não respondeu)

O sistema faz até 3 tentativas automáticas para pacientes que não responderam:

- **Tentativa 1** (após 24 horas): Lembrete gentil pedindo confirmação, avisando que tem 2 dias para responder
- **Tentativa 2** (após 72 horas): Último aviso, informando que a vaga poderá ser liberada
- **Sem resposta** (após 96 horas): Mensagem informando que a vaga foi liberada e o paciente deve entrar em contato se ainda tiver interesse

Essa configuração pode ser ajustada em **Configurações > Follow-up**.

### 7. FAQ - Respostas Automáticas

- O sistema possui um módulo de FAQ para responder dúvidas frequentes dos pacientes
- Cada FAQ tem **palavras-gatilho** — quando o paciente envia uma mensagem contendo essas palavras, a resposta é enviada automaticamente
- Exemplos: se o paciente perguntar "qual endereço", o sistema pode responder automaticamente com o endereço do hospital

---

## ACOMPANHAMENTO E RELATÓRIOS

### Dashboard Principal
- Cards com estatísticas: total de campanhas, contatos confirmados, rejeitados
- Status do WhatsApp (online/offline)
- Lista de todas as campanhas com progresso

### Relatórios
- Visualização detalhada por campanha
- Exportação dos dados para Excel
- Estatísticas de confirmados, rejeitados, sem resposta e erros

### Análise de Sentimentos
- O sistema analisa automaticamente o tom das mensagens recebidas
- Categorias: Positivo, Negativo, Urgente, Insatisfação
- Ajuda a identificar pacientes que precisam de atenção especial

### Logs de Mensagens
- Histórico completo de todas as mensagens enviadas e recebidas
- Filtros por campanha e tipo (enviada/recebida)
- Registro de erros de envio

---

## AÇÕES MANUAIS DISPONÍVEIS

Para cada contato individualmente, o operador pode:
- **Confirmar manualmente** — quando o paciente ligou por telefone, por exemplo
- **Rejeitar manualmente** — quando informado por outro canal
- **Reenviar mensagem** — tentar novamente para um contato específico
- **Revalidar número** — verificar novamente se o número tem WhatsApp
- **Enviar mensagem personalizada** — escrever e enviar mensagem livre

---

## SEGURANÇA E CONTROLES

- Cada usuário tem seu próprio WhatsApp conectado (instância separada)
- O sistema respeita os horários configurados (não envia de madrugada)
- Existe limite diário de envios para não sobrecarregar
- Painel de Administrador para gerenciar usuários e permissões
- Todas as mensagens são registradas em log para auditoria

---

## RESUMO DO FLUXO

```
Planilha Excel → Upload no Sistema → Validação dos Números →
Envio Automático via WhatsApp → Paciente Responde (SIM/NÃO/DESCONHEÇO) →
Sistema Registra Resposta → Follow-up Automático (se não respondeu) →
Relatórios e Exportação
```

---

## BENEFÍCIOS DO SISTEMA

1. **Agilidade**: Centenas de pacientes contatados por dia automaticamente
2. **Economia**: Reduz ligações telefônicas manuais
3. **Rastreabilidade**: Todo contato é registrado e pode ser auditado
4. **Inteligência**: Análise de sentimentos identifica casos urgentes
5. **Follow-up automático**: Não perde pacientes que esqueceram de responder
6. **Liberação de vagas**: Identifica rapidamente quem não quer mais a cirurgia, liberando vagas para outros pacientes
