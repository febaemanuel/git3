"""
Testes funcionais da Evolution API (WhatsApp)
=============================================
Arquivo standalone para testar a integração com a Evolution API v2.x
sem dependências do Flask, banco de dados ou Celery.

Este arquivo serve também como especificação completa da integração:
contém todos os endpoints utilizados, os payloads enviados, os formatos
de resposta esperados e os casos de erro tratados. Uma IA pode ler este
arquivo e reimplementar a integração em qualquer linguagem ou framework.

--------------------------------------------------------------------
VISÃO GERAL DA EVOLUTION API v2
--------------------------------------------------------------------
A Evolution API é uma API REST self-hosted que atua como gateway para
o WhatsApp Web (usando a biblioteca Baileys). Cada "instância" representa
um número WhatsApp pareado via QR Code.

Autenticação: todas as requisições exigem o header:
    apikey: <EVOLUTION_API_KEY>

Base URL: configurável (ex: https://api.meusite.com)

--------------------------------------------------------------------
ENDPOINTS UTILIZADOS
--------------------------------------------------------------------

1. LISTAR INSTÂNCIAS
   GET /instance/fetchInstances
   Headers: { apikey, Content-Type }
   Response 200: lista de instâncias
     [
       {
         "instance": {
           "instanceName": "minha-instancia",
           "status": "open" | "close" | "connecting",
           "state":  "open" | "close" | "connecting"
         }
       },
       ...
     ]

2. CRIAR INSTÂNCIA
   POST /instance/create
   Headers: { apikey, Content-Type }
   Body:
     {
       "instanceName": "minha-instancia",
       "token":        "<api_key>",
       "qrcode":       true,
       "integration":  "WHATSAPP-BAILEYS"
     }
   Response 200/201: instância criada
   Response 403/409: instância já existe

3. ESTADO DA CONEXÃO
   GET /instance/connectionState/{instanceName}
   Headers: { apikey }
   Response 200:
     { "instance": { "state": "open" | "close" | "connecting" } }
     OU
     { "state": "open" | "close" | "connecting" }   <- formato alternativo

4. CONECTAR / OBTER QR CODE
   GET /instance/connect/{instanceName}
   Headers: { apikey }
   Response 200 (instância desconectada):
     Formato A: { "base64": "data:image/png;base64,..." }
     Formato B: { "qrcode": { "base64": "...", "code": "..." } }
     Formato C: { "code": "..." }
     Formato D: { "pairingCode": "ABC-123" }     <- alternativa ao QR
     Formato E: { "instance": { "state": "open" } }  <- já conectado
   Response 404: instância não encontrada
   Response 401/403: API Key inválida

5. CONFIGURAR WEBHOOK
   POST /webhook/set/{instanceName}
   Headers: { apikey, Content-Type }
   Body:
     {
       "webhook": {
         "enabled":         true,
         "url":             "https://meusite.com/webhook/whatsapp",
         "webhookByEvents": false,
         "webhookBase64":   false,
         "events": ["MESSAGES_UPSERT", "CONNECTION_UPDATE", ...]
       }
     }
   Response 200/201: webhook configurado

6. OBTER CONFIGURAÇÃO DO WEBHOOK
   GET /webhook/find/{instanceName}
   Headers: { apikey }
   Response 200: configuração atual (mesmo schema do POST acima)

7. VERIFICAR NÚMEROS NO WHATSAPP
   POST /chat/whatsappNumbers/{instanceName}
   Headers: { apikey, Content-Type }
   Body: { "numbers": ["5511999999999", "5521888888888"] }
   Response 200:
     Formato lista:
       [
         { "number": "5511999999999", "exists": true,  "jid": "5511999999999@s.whatsapp.net" },
         { "number": "5521888888888", "exists": false, "jid": "" }
       ]
     Formato dict (versões antigas):
       {
         "5511999999999": { "exists": true,  "jid": "..." },
         "5521888888888": { "exists": false, "jid": "" }
       }

8. ENVIAR MENSAGEM DE TEXTO
   POST /message/sendText/{instanceName}
   Headers: { apikey, Content-Type }
   Body:
     {
       "number":      "5511999999999",
       "text":        "Olá, tudo bem?",
       "linkPreview": false
     }
   Response 200/201:
     { "key": { "id": "MESSAGE_ID_AQUI", ... }, ... }

9. ENVIAR ARQUIVO (PDF, imagem, vídeo, áudio)
   POST /message/sendMedia/{instanceName}
   Headers: { apikey, Content-Type }
   Body (imagem):
     {
       "number":    "5511999999999",
       "mediatype": "image",
       "mimetype":  "image/jpeg",
       "media":     "<base64 do arquivo>",
       "fileName":  "foto.jpg",
       "caption":   "Legenda opcional"
     }
   Body (PDF/documento):
     {
       "number":    "5511999999999",
       "mediatype": "document",
       "mimetype":  "application/pdf",
       "media":     "<base64 do arquivo>",
       "fileName":  "documento.pdf",
       "caption":   "Legenda opcional"
     }
   Response 200/201: { "key": { "id": "..." }, ... }

--------------------------------------------------------------------
EVENTOS DO WEBHOOK (recebidos via POST na URL configurada)
--------------------------------------------------------------------
A Evolution API envia POSTs para o webhook configurado com este schema:
  {
    "event":    "MESSAGES_UPSERT",
    "instance": "minha-instancia",
    "data": {
      "key": {
        "remoteJid": "5511999999999@s.whatsapp.net",
        "fromMe":    false,
        "id":        "MESSAGE_ID"
      },
      "message": {
        "conversation": "Texto da mensagem"
        // ou "extendedTextMessage": { "text": "..." }
        // ou "imageMessage": { ... }
      },
      "messageTimestamp": 1700000000,
      "pushName": "Nome do contato"
    }
  }

Principais eventos:
  MESSAGES_UPSERT    -> nova mensagem recebida ou enviada
  MESSAGES_UPDATE    -> status de leitura/entrega atualizado
  CONNECTION_UPDATE  -> estado da conexão mudou
  QRCODE_UPDATED     -> novo QR Code gerado
  SEND_MESSAGE       -> confirmação de envio

--------------------------------------------------------------------
Uso:
    export EVOLUTION_API_URL=https://sua-evolution-api.com
    export EVOLUTION_API_KEY=sua_api_key
    export EVOLUTION_INSTANCE=nome_da_instancia
    export NUMERO_TESTE=5511999999999   # opcional

    python test_evolution_api.py
--------------------------------------------------------------------
"""

import os
import time
import base64
import json
import requests


# =============================================================================
# CONFIGURAÇÃO
# Lidas de variáveis de ambiente para não expor credenciais no código.
# =============================================================================

EVOLUTION_API_URL  = os.environ.get('EVOLUTION_API_URL', '').rstrip('/')
EVOLUTION_API_KEY  = os.environ.get('EVOLUTION_API_KEY', '')
EVOLUTION_INSTANCE = os.environ.get('EVOLUTION_INSTANCE', '')

# Número para testes de envio e validação (formato internacional sem +: 5511999999999)
NUMERO_TESTE = os.environ.get('NUMERO_TESTE', '')


# =============================================================================
# CLIENTE DA EVOLUTION API
# Extraído da classe WhatsApp em app.py, sem dependências de Flask ou ORM.
# Todos os métodos retornam (sucesso: bool, resultado_ou_erro).
# =============================================================================

class EvolutionAPIClient:
    """
    Cliente HTTP direto para a Evolution API v2.x (WhatsApp).

    Cada instância representa uma conexão com um número WhatsApp específico.
    A Evolution API pode hospedar múltiplas instâncias no mesmo servidor.
    """

    def __init__(self, url: str, api_key: str, instance: str):
        """
        Args:
            url:      URL base da Evolution API (ex: https://api.meusite.com)
            api_key:  Chave de autenticação global da Evolution API
            instance: Nome da instância WhatsApp a ser gerenciada
        """
        self.url      = url.rstrip('/')   # remove barra final para montar endpoints corretamente
        self.key      = api_key
        self.instance = instance

    # ------------------------------------------------------------------
    # Métodos internos (helpers privados)
    # ------------------------------------------------------------------

    def ok(self) -> bool:
        """Retorna True se URL, API Key e instância estão preenchidos."""
        return bool(self.url and self.key and self.instance)

    def _headers(self) -> dict:
        """Cabeçalhos obrigatórios em todas as requisições à Evolution API."""
        return {
            'apikey': self.key,           # autenticação
            'Content-Type': 'application/json'
        }

    def _req(self, method: str, endpoint: str, data: dict = None):
        """
        Realiza uma requisição HTTP à Evolution API.

        Args:
            method:   'GET' ou 'POST'
            endpoint: caminho relativo (ex: '/instance/fetchInstances')
            data:     corpo JSON para requisições POST

        Returns:
            (True, Response) em caso de sucesso de rede
            (False, str)     em caso de exceção de conexão
        """
        try:
            full_url = f"{self.url}{endpoint}"
            if method == 'GET':
                r = requests.get(full_url, headers=self._headers(), timeout=30)
            else:
                r = requests.post(full_url, headers=self._headers(), json=data, timeout=30)
            return True, r
        except Exception as e:
            # Captura erros de rede (timeout, DNS, recusa de conexão, etc.)
            return False, str(e)

    # ------------------------------------------------------------------
    # Gerenciamento de instâncias
    # ------------------------------------------------------------------

    def listar_instancias(self):
        """
        Retorna todas as instâncias registradas na Evolution API.
        Útil para verificar se uma instância já existe antes de criá-la.

        Returns:
            (True, list[dict])  lista de instâncias
            (False, str)        mensagem de erro
        """
        if not self.ok():
            return False, "Não configurado"

        ok, r = self._req('GET', '/instance/fetchInstances')
        if ok and r.status_code == 200:
            return True, r.json()
        return False, f"Erro: {r.status_code if ok else r}"

    def criar_instancia(self):
        """
        Cria uma nova instância WhatsApp na Evolution API.
        Usa integração WHATSAPP-BAILEYS (padrão open-source).

        Returns:
            (True, str)   mensagem de sucesso
            (False, str)  mensagem de erro
        """
        if not self.ok():
            return False, "Não configurado"

        ok, r = self._req('POST', '/instance/create', {
            'instanceName': self.instance,
            'token':        self.key,
            'qrcode':       True,                       # gera QR Code automaticamente
            'integration':  'WHATSAPP-BAILEYS'          # motor de conexão
        })

        if ok and r.status_code in [200, 201]:
            return True, "Instância criada"
        elif ok and r.status_code == 409:               # Conflict: já existe
            return True, "Instância já existe"
        elif ok and r.status_code == 403 and 'already' in r.text.lower():
            return True, "Instância já existe"

        return False, f"Erro ao criar: {r.status_code if ok else r}"

    # ------------------------------------------------------------------
    # Estado da conexão
    # ------------------------------------------------------------------

    def conectado(self):
        """
        Verifica se a instância está com o WhatsApp conectado.
        O estado 'open' significa conexão ativa.

        Returns:
            (True, 'open')   conectado
            (False, estado)  desconectado ou erro
        """
        if not self.ok():
            return False, "Não configurado"

        ok, r = self._req('GET', f"/instance/connectionState/{self.instance}")
        if ok and r.status_code == 200:
            data = r.json()
            # A Evolution API pode retornar o estado em dois formatos diferentes
            state = data.get('instance', {}).get('state', '')
            if not state:
                state = data.get('state', '')           # formato alternativo
            return state == 'open', state

        return False, "Erro ao verificar conexão"

    # ------------------------------------------------------------------
    # QR Code (para autenticação do WhatsApp)
    # ------------------------------------------------------------------

    def qrcode(self):
        """
        Obtém o QR Code para parear o WhatsApp com a instância.
        Fluxo: verifica instância → cria se não existir → conecta → extrai QR.

        A Evolution API pode retornar o QR em vários formatos dependendo
        da versão; este método trata todos os casos conhecidos.

        Returns:
            (True, str)   string base64 com prefixo 'data:image/png;base64,...'
            (False, str)  mensagem de erro ou instrução
        """
        if not self.ok():
            return False, "Não configurado"

        # --- Passo 1: Verificar se a instância já existe ---
        sucesso, instances = self.listar_instancias()
        if not sucesso:
            if "403" in str(instances):
                return False, "API Key inválida"
            return False, f"Erro ao verificar instâncias: {instances}"

        instance_exists = False
        if isinstance(instances, list):
            for inst in instances:
                # O nome pode estar em dois lugares dependendo da versão da API
                inst_name = inst.get('instance', {}).get('instanceName') or inst.get('instanceName')
                if inst_name == self.instance:
                    instance_exists = True
                    state = (inst.get('instance', {}).get('status')
                             or inst.get('state')
                             or inst.get('instance', {}).get('state'))
                    if state == 'open':
                        return False, "WhatsApp já está conectado!"
                    break

        # --- Passo 2: Criar instância se não existir ---
        if not instance_exists:
            sucesso, msg = self.criar_instancia()
            if not sucesso:
                return False, f"Erro ao criar instância: {msg}"
            time.sleep(2)   # aguarda a instância inicializar antes de conectar

        # --- Passo 3: Solicitar conexão e obter QR Code ---
        ok, r = self._req('GET', f"/instance/connect/{self.instance}")

        if ok and r.status_code == 200:
            data = r.json()
            qr = None

            if isinstance(data, dict):
                # Formato 1: { "base64": "data:image..." }
                if 'base64' in data:
                    qr = data['base64']

                # Formato 2: { "qrcode": { "base64": "..." } } ou { "qrcode": "..." }
                elif 'qrcode' in data:
                    qr_obj = data['qrcode']
                    qr = qr_obj.get('base64') or qr_obj.get('code') if isinstance(qr_obj, dict) else qr_obj

                # Formato 3: { "code": "..." }
                elif 'code' in data:
                    qr = data['code']

                # Formato 4: código de pareamento (alternativa ao QR)
                elif 'pairingCode' in data:
                    return False, f"Use o código de pareamento: {data['pairingCode']}"

                # Formato 5: instância já conectada
                elif data.get('instance', {}).get('state') == 'open':
                    return False, "WhatsApp já está conectado!"

            if qr:
                # Garantir prefixo para uso direto em <img src="...">
                if not qr.startswith('data:image'):
                    qr = f"data:image/png;base64,{qr}"
                return True, qr

            return False, "QR Code não disponível. Tente novamente em alguns segundos."

        elif ok and r.status_code == 404:
            return False, "Instância não encontrada"
        elif ok and r.status_code in [401, 403]:
            return False, "API Key inválida"
        else:
            return False, f"HTTP {r.status_code}: {r.text[:200]}" if ok else str(r)

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------

    def obter_webhook_config(self):
        """
        Retorna a configuração atual do webhook da instância.
        Útil para verificar se o webhook já está configurado corretamente.

        Returns:
            (True, dict)  configuração atual
            (False, str)  mensagem de erro
        """
        if not self.ok():
            return False, "Não configurado"

        ok, r = self._req('GET', f'/webhook/find/{self.instance}')
        if ok and r.status_code == 200:
            try:
                return True, r.json()
            except Exception:
                return False, "Erro ao parsear resposta"

        return False, f"Erro ao obter webhook: {r.status_code if ok else r}"

    def configurar_webhook(self, webhook_url: str):
        """
        Configura o endpoint que receberá eventos da Evolution API.

        Estratégia em dois passos:
          1. Configura com eventos essenciais (mensagens e conexão)
          2. Tenta expandir para todos os eventos disponíveis

        Args:
            webhook_url: URL pública que receberá os POSTs da API
                         (ex: https://meusite.com/webhook/whatsapp)

        Returns:
            (True, str)   URL do webhook configurado
            (False, str)  mensagem de erro
        """
        if not self.ok():
            return False, "Não configurado"

        # Eventos mínimos necessários para o funcionamento do sistema
        essential_events = [
            'MESSAGES_UPSERT',      # novas mensagens recebidas
            'MESSAGES_UPDATE',      # status de leitura/entrega
            'SEND_MESSAGE',         # confirmação de envio
            'CONNECTION_UPDATE'     # mudanças no estado da conexão
        ]

        # Todos os eventos disponíveis na Evolution API v2
        all_events = [
            'APPLICATION_STARTUP', 'CALL', 'CHATS_DELETE', 'CHATS_SET',
            'CHATS_UPDATE', 'CHATS_UPSERT', 'CONNECTION_UPDATE', 'CONTACTS_SET',
            'CONTACTS_UPDATE', 'CONTACTS_UPSERT', 'GROUP_PARTICIPANTS_UPDATE',
            'GROUP_UPDATE', 'GROUPS_UPSERT', 'LABELS_ASSOCIATION', 'LABELS_EDIT',
            'MESSAGES_DELETE', 'MESSAGES_SET', 'MESSAGES_UPDATE', 'MESSAGES_UPSERT',
            'PRESENCE_UPDATE', 'QRCODE_UPDATED', 'SEND_MESSAGE'
        ]

        # Payload com estrutura esperada pela Evolution API v2
        payload = {
            'webhook': {
                'enabled':        True,
                'url':            webhook_url,
                'webhookByEvents': False,   # False = todos os eventos no mesmo endpoint
                'webhookBase64':  False,    # False = mídia como URL, não base64
                'events':         essential_events
            }
        }

        # Passo 1: configurar com eventos essenciais
        ok, r = self._req('POST', f'/webhook/set/{self.instance}', payload)

        if ok and r.status_code in [200, 201]:
            # Passo 2: tentar expandir para todos os eventos
            payload['webhook']['events'] = all_events
            ok2, r2 = self._req('POST', f'/webhook/set/{self.instance}', payload)
            if ok2 and r2.status_code in [200, 201]:
                return True, f"Webhook configurado com todos os eventos: {webhook_url}"
            # Fallback: manter apenas os essenciais (que já funcionaram)
            return True, f"Webhook configurado com eventos essenciais: {webhook_url}"

        error_detail = r.json() if ok else str(r)
        return False, f"Erro ao configurar webhook: {r.status_code if ok else 'conexão falhou'} - {error_detail}"

    # ------------------------------------------------------------------
    # Mensagens
    # ------------------------------------------------------------------

    def verificar_numeros(self, numeros: list) -> dict:
        """
        Verifica em lote quais números possuem WhatsApp ativo.
        A Evolution API aceita vários números por requisição.

        Args:
            numeros: lista de strings com números no formato internacional
                     (ex: ['5511999999999', '5521888888888'])

        Returns:
            dict mapeando número → { 'exists': bool, 'jid': str }
            JID (Jabber ID) é o identificador interno do WhatsApp.
        """
        if not self.ok():
            return {}

        # Filtrar vazios e garantir tipo string
        nums = [str(n) for n in numeros if n]
        if not nums:
            return {}

        result = {}
        ok, r = self._req('POST', f"/chat/whatsappNumbers/{self.instance}", {'numbers': nums})

        if ok and r.status_code == 200:
            try:
                data = r.json()
                # A API pode retornar lista ou dicionário dependendo da versão
                if isinstance(data, list):
                    for item in data:
                        # Manter apenas dígitos para normalizar o número
                        num = ''.join(filter(str.isdigit, str(item.get('number', ''))))
                        exists = item.get('exists', False) or item.get('numberExists', False)
                        jid    = item.get('jid', '')
                        if num:
                            result[num] = {'exists': exists, 'jid': jid}
                elif isinstance(data, dict):
                    for num, info in data.items():
                        num_clean = ''.join(filter(str.isdigit, num))
                        if isinstance(info, dict):
                            result[num_clean] = {
                                'exists': info.get('exists', False),
                                'jid':    info.get('jid', '')
                            }
                        else:
                            result[num_clean] = {'exists': bool(info), 'jid': ''}
            except Exception:
                pass    # retorna dict vazio em caso de resposta inesperada

        return result

    def enviar(self, numero: str, texto: str):
        """
        Envia mensagem de texto simples via WhatsApp.

        Args:
            numero: destinatário no formato internacional (ex: '5511999999999')
            texto:  conteúdo da mensagem

        Returns:
            (True, message_id)  enviado com sucesso
            (False, str)        mensagem de erro da API
        """
        if not self.ok():
            return False, "Não configurado"

        # Remover qualquer formatação (espaços, traços, parênteses, +)
        num = ''.join(filter(str.isdigit, str(numero)))

        ok, r = self._req('POST', f"/message/sendText/{self.instance}", {
            'number':      num,
            'text':        texto,
            'linkPreview': False    # desabilita preview de URLs para mensagens programáticas
        })

        if ok and r.status_code in [200, 201]:
            try:
                mid = r.json().get('key', {}).get('id', '')
                return True, mid
            except Exception:
                return True, ''     # enviado mas sem ID retornado

        return False, r.text[:100] if ok else r

    def enviar_arquivo(self, numero: str, caminho_arquivo: str, caption: str = None):
        """
        Envia arquivo (PDF, imagem, áudio ou vídeo) via WhatsApp.
        O arquivo é lido do disco e enviado como base64 no corpo da requisição.

        Args:
            numero:          destinatário no formato internacional
            caminho_arquivo: caminho absoluto do arquivo no servidor
            caption:         texto opcional exibido abaixo do arquivo

        Returns:
            (True, message_id)  enviado com sucesso
            (False, str)        mensagem de erro
        """
        if not self.ok():
            return False, "Não configurado"

        if not os.path.exists(caminho_arquivo):
            return False, f"Arquivo não encontrado: {caminho_arquivo}"

        # Mapear extensão → MIME type para o campo obrigatório da API
        ext = os.path.splitext(caminho_arquivo)[1].lower()
        tipo_map = {
            '.pdf':  'application/pdf',
            '.jpg':  'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png':  'image/png',
            '.mp4':  'video/mp4',
            '.mp3':  'audio/mpeg',
        }
        mimetype = tipo_map.get(ext, 'application/octet-stream')   # fallback genérico

        try:
            # Ler arquivo e codificar em base64
            with open(caminho_arquivo, 'rb') as f:
                arquivo_b64 = base64.b64encode(f.read()).decode('utf-8')

            num           = ''.join(filter(str.isdigit, str(numero)))
            nome_arquivo  = os.path.basename(caminho_arquivo)

            # Imagens usam mediatype 'image'; demais arquivos usam 'document'
            mediatype = 'image' if ext in ['.jpg', '.jpeg', '.png'] else 'document'

            payload = {
                'number':    num,
                'mediatype': mediatype,
                'mimetype':  mimetype,
                'media':     arquivo_b64,
                'fileName':  nome_arquivo
            }
            if caption:
                payload['caption'] = caption

            ok, r = self._req('POST', f"/message/sendMedia/{self.instance}", payload)

            if ok and r.status_code in [200, 201]:
                try:
                    mid = r.json().get('key', {}).get('id', '')
                    return True, mid
                except Exception:
                    return True, ''

            return False, r.text[:200] if ok else str(r)

        except Exception as e:
            return False, str(e)


# =============================================================================
# FUNÇÕES DE TESTE
# Cada função testa uma funcionalidade específica e imprime o resultado.
# =============================================================================

def _print_resultado(titulo: str, ok: bool, detalhe):
    """Exibe o resultado de um teste de forma padronizada."""
    status = "OK" if ok else "FALHOU"
    print(f"  [{status}] {titulo}")
    if detalhe:
        # Formatar dicts/listas como JSON indentado para melhor leitura
        detalhe_str = (
            json.dumps(detalhe, ensure_ascii=False, indent=4)
            if isinstance(detalhe, (dict, list))
            else str(detalhe)
        )
        for linha in detalhe_str.splitlines():
            print(f"          {linha}")


def testar_configuracao(client: EvolutionAPIClient):
    """Verifica se as três variáveis obrigatórias estão preenchidas."""
    print("\n--- Configuração ---")
    ok = client.ok()
    _print_resultado(
        "URL, API Key e instância preenchidos",
        ok,
        None if ok else "Defina EVOLUTION_API_URL, EVOLUTION_API_KEY e EVOLUTION_INSTANCE"
    )


def testar_listar_instancias(client: EvolutionAPIClient):
    """
    Lista todas as instâncias do servidor.
    Valida conectividade de rede e autenticação via API Key.
    """
    print("\n--- Listar Instâncias ---")
    ok, resultado = client.listar_instancias()
    if ok and isinstance(resultado, list):
        # Extrair só os nomes para exibição resumida
        nomes = [
            i.get('instance', {}).get('instanceName') or i.get('instanceName', '?')
            for i in resultado
        ]
        _print_resultado(f"Instâncias encontradas ({len(resultado)})", True, nomes)
    else:
        _print_resultado("Listar instâncias", ok, resultado)
    return ok, resultado


def testar_status_conexao(client: EvolutionAPIClient) -> bool:
    """Verifica se a instância está conectada ao WhatsApp."""
    print("\n--- Status da Conexão ---")
    conectado, estado = client.conectado()
    _print_resultado(f"Estado: {estado}", conectado, None)
    return conectado


def testar_webhook(client: EvolutionAPIClient):
    """Exibe a configuração atual do webhook (URL e eventos registrados)."""
    print("\n--- Webhook ---")
    ok, config = client.obter_webhook_config()
    _print_resultado("Obter configuração atual do webhook", ok, config)


def testar_verificar_numeros(client: EvolutionAPIClient, numeros: list):
    """
    Valida se os números da lista têm WhatsApp ativo.
    Requer NUMERO_TESTE definido e instância conectada.
    """
    print("\n--- Verificar Números no WhatsApp ---")
    if not numeros:
        print("  [PULADO] Defina NUMERO_TESTE para executar este teste")
        return

    resultado = client.verificar_numeros(numeros)
    for num, info in resultado.items():
        _print_resultado(
            f"Número {num}",
            info.get('exists', False),
            f"JID: {info.get('jid', '-')}"
        )
    if not resultado:
        _print_resultado("Verificar números", False, "Sem resultado da API")


def testar_enviar_mensagem(client: EvolutionAPIClient, numero: str,
                           texto: str = "Teste de integração Evolution API - pode ignorar."):
    """
    Envia uma mensagem de texto real para o número informado.
    ATENÇÃO: esta função envia uma mensagem WhatsApp de verdade.
    """
    print("\n--- Enviar Mensagem de Texto ---")
    if not numero:
        print("  [PULADO] Defina NUMERO_TESTE para executar este teste")
        return

    ok, resultado = client.enviar(numero, texto)
    _print_resultado(f"Enviar para {numero}", ok, resultado)


def testar_qrcode(client: EvolutionAPIClient):
    """
    Tenta obter o QR Code para parear o WhatsApp.
    Só faz sentido quando a instância NÃO está conectada.
    """
    print("\n--- QR Code ---")
    ok, resultado = client.qrcode()
    if ok:
        # Não exibir o base64 completo; mostrar apenas o tamanho
        _print_resultado("QR Code obtido", True, f"{len(resultado)} caracteres (base64)")
    else:
        _print_resultado("QR Code", False, resultado)


# =============================================================================
# EXECUÇÃO PRINCIPAL
# Sequência de testes ordenada por pré-requisito:
#   1. Configuração → 2. Conectividade → 3. Estado → 4. Webhook
#   → 5. Validar número → 6. QR Code (se desconectado) → 7. Envio
# =============================================================================

def main():
    print("=" * 60)
    print("  Testes Funcionais - Evolution API (WhatsApp)")
    print("=" * 60)
    print(f"  URL:       {EVOLUTION_API_URL or '(não definido)'}")
    print(f"  Instância: {EVOLUTION_INSTANCE or '(não definido)'}")
    # Mascarar a chave para não expor em logs
    api_key_display = ('***' + EVOLUTION_API_KEY[-4:]) if len(EVOLUTION_API_KEY) > 4 else '(não definido)'
    print(f"  API Key:   {api_key_display}")

    client = EvolutionAPIClient(EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE)

    # 1. Verificar se as variáveis obrigatórias estão preenchidas
    testar_configuracao(client)

    if not client.ok():
        print("\nABORTANDO: configure as variáveis de ambiente e tente novamente.")
        print("  export EVOLUTION_API_URL=https://sua-api.com")
        print("  export EVOLUTION_API_KEY=sua_chave")
        print("  export EVOLUTION_INSTANCE=nome_instancia")
        return

    # 2. Listar instâncias — valida conectividade de rede e API Key ao mesmo tempo
    testar_listar_instancias(client)

    # 3. Verificar estado da conexão — determina se os próximos testes são pulados
    conectado = testar_status_conexao(client)

    # 4. Exibir configuração do webhook
    testar_webhook(client)

    # 5. Validar número no WhatsApp (opcional — requer NUMERO_TESTE)
    if NUMERO_TESTE:
        testar_verificar_numeros(client, [NUMERO_TESTE])

    # 6. QR Code — executado apenas se a instância não estiver conectada
    if not conectado:
        testar_qrcode(client)
    else:
        print("\n--- QR Code ---")
        print("  [PULADO] Instância já conectada")

    # 7. Enviar mensagem — requer instância conectada E NUMERO_TESTE definido
    if conectado and NUMERO_TESTE:
        testar_enviar_mensagem(client, NUMERO_TESTE)
    elif not conectado:
        print("\n--- Enviar Mensagem ---")
        print("  [PULADO] Instância não está conectada")
    else:
        print("\n--- Enviar Mensagem ---")
        print("  [PULADO] Defina NUMERO_TESTE para executar este teste")

    print("\n" + "=" * 60)
    print("  Testes concluídos.")
    print("=" * 60)


if __name__ == '__main__':
    main()
