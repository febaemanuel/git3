"""
Testes funcionais da Evolution API (WhatsApp)
=============================================
Arquivo standalone para testar a integração com a Evolution API v2.x
sem dependências do Flask, banco de dados ou Celery.

Uso:
    # Configurar variáveis de ambiente antes de executar:
    export EVOLUTION_API_URL=https://sua-evolution-api.com
    export EVOLUTION_API_KEY=sua_api_key
    export EVOLUTION_INSTANCE=nome_da_instancia

    python test_evolution_api.py
"""

import os
import time
import base64
import json
import requests


# =============================================================================
# CONFIGURAÇÃO
# =============================================================================

EVOLUTION_API_URL = os.environ.get('EVOLUTION_API_URL', '').rstrip('/')
EVOLUTION_API_KEY = os.environ.get('EVOLUTION_API_KEY', '')
EVOLUTION_INSTANCE = os.environ.get('EVOLUTION_INSTANCE', '')

# Número para testes de envio (formato: 5511999999999)
NUMERO_TESTE = os.environ.get('NUMERO_TESTE', '')


# =============================================================================
# CLIENTE DA EVOLUTION API
# =============================================================================

class EvolutionAPIClient:
    """
    Cliente standalone para a Evolution API v2.x
    Extraído da classe WhatsApp em app.py para uso em testes.
    """

    def __init__(self, url, api_key, instance):
        self.url = url.rstrip('/')
        self.key = api_key
        self.instance = instance

    def ok(self):
        """Verifica se a configuração está preenchida"""
        return bool(self.url and self.key and self.instance)

    def _headers(self):
        return {'apikey': self.key, 'Content-Type': 'application/json'}

    def _req(self, method, endpoint, data=None):
        try:
            full_url = f"{self.url}{endpoint}"
            if method == 'GET':
                r = requests.get(full_url, headers=self._headers(), timeout=30)
            else:
                r = requests.post(full_url, headers=self._headers(), json=data, timeout=30)
            return True, r
        except Exception as e:
            return False, str(e)

    def conectado(self):
        """Verifica se a instância está conectada ao WhatsApp"""
        if not self.ok():
            return False, "Não configurado"
        ok, r = self._req('GET', f"/instance/connectionState/{self.instance}")
        if ok and r.status_code == 200:
            data = r.json()
            state = data.get('instance', {}).get('state', '')
            if not state:
                state = data.get('state', '')
            return state == 'open', state
        return False, "Erro ao verificar conexão"

    def listar_instancias(self):
        """Lista todas as instâncias disponíveis"""
        if not self.ok():
            return False, "Não configurado"
        ok, r = self._req('GET', '/instance/fetchInstances')
        if ok and r.status_code == 200:
            return True, r.json()
        return False, f"Erro: {r.status_code if ok else r}"

    def criar_instancia(self):
        """Cria uma nova instância"""
        if not self.ok():
            return False, "Não configurado"
        ok, r = self._req('POST', '/instance/create', {
            'instanceName': self.instance,
            'token': self.key,
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        })
        if ok and r.status_code in [200, 201]:
            return True, "Instância criada"
        elif ok and r.status_code == 409:
            return True, "Instância já existe"
        elif ok and r.status_code == 403 and 'already' in r.text.lower():
            return True, "Instância já existe"
        return False, f"Erro ao criar: {r.status_code if ok else r}"

    def obter_webhook_config(self):
        """Obtém a configuração atual do webhook"""
        if not self.ok():
            return False, "Não configurado"
        ok, r = self._req('GET', f'/webhook/find/{self.instance}')
        if ok and r.status_code == 200:
            try:
                return True, r.json()
            except Exception:
                return False, "Erro ao parsear resposta"
        return False, f"Erro ao obter webhook: {r.status_code if ok else r}"

    def configurar_webhook(self, webhook_url):
        """
        Configura o webhook para receber mensagens

        Args:
            webhook_url: URL completa do webhook (ex: https://meusite.com/webhook/whatsapp)
        """
        if not self.ok():
            return False, "Não configurado"

        essential_events = [
            'MESSAGES_UPSERT',
            'MESSAGES_UPDATE',
            'SEND_MESSAGE',
            'CONNECTION_UPDATE'
        ]
        all_events = [
            'APPLICATION_STARTUP', 'CALL', 'CHATS_DELETE', 'CHATS_SET',
            'CHATS_UPDATE', 'CHATS_UPSERT', 'CONNECTION_UPDATE', 'CONTACTS_SET',
            'CONTACTS_UPDATE', 'CONTACTS_UPSERT', 'GROUP_PARTICIPANTS_UPDATE',
            'GROUP_UPDATE', 'GROUPS_UPSERT', 'LABELS_ASSOCIATION', 'LABELS_EDIT',
            'MESSAGES_DELETE', 'MESSAGES_SET', 'MESSAGES_UPDATE', 'MESSAGES_UPSERT',
            'PRESENCE_UPDATE', 'QRCODE_UPDATED', 'SEND_MESSAGE'
        ]

        payload = {
            'webhook': {
                'enabled': True,
                'url': webhook_url,
                'webhookByEvents': False,
                'webhookBase64': False,
                'events': essential_events
            }
        }

        ok, r = self._req('POST', f'/webhook/set/{self.instance}', payload)

        if ok and r.status_code in [200, 201]:
            # Tentar adicionar todos os eventos
            payload['webhook']['events'] = all_events
            ok2, r2 = self._req('POST', f'/webhook/set/{self.instance}', payload)
            if ok2 and r2.status_code in [200, 201]:
                return True, f"Webhook configurado com todos os eventos: {webhook_url}"
            return True, f"Webhook configurado com eventos essenciais: {webhook_url}"

        error_detail = r.json() if ok else str(r)
        return False, f"Erro ao configurar webhook: {r.status_code if ok else 'conexão falhou'} - {error_detail}"

    def qrcode(self):
        """
        Obtém o QR Code para conectar o WhatsApp.
        Retorna (True, base64_string) ou (False, mensagem_erro).
        """
        if not self.ok():
            return False, "Não configurado"

        # Verificar se instância existe
        sucesso, instances = self.listar_instancias()
        if not sucesso:
            if "403" in str(instances):
                return False, "API Key inválida"
            return False, f"Erro ao verificar instâncias: {instances}"

        instance_exists = False
        if isinstance(instances, list):
            for inst in instances:
                inst_name = inst.get('instance', {}).get('instanceName') or inst.get('instanceName')
                if inst_name == self.instance:
                    instance_exists = True
                    state = (inst.get('instance', {}).get('status')
                             or inst.get('state')
                             or inst.get('instance', {}).get('state'))
                    if state == 'open':
                        return False, "WhatsApp já está conectado!"
                    break

        if not instance_exists:
            sucesso, msg = self.criar_instancia()
            if not sucesso:
                return False, f"Erro ao criar instância: {msg}"
            time.sleep(2)

        ok, r = self._req('GET', f"/instance/connect/{self.instance}")

        if ok and r.status_code == 200:
            data = r.json()
            qr = None

            if isinstance(data, dict):
                if 'base64' in data:
                    qr = data['base64']
                elif 'qrcode' in data:
                    qr_obj = data['qrcode']
                    qr = qr_obj.get('base64') or qr_obj.get('code') if isinstance(qr_obj, dict) else qr_obj
                elif 'code' in data:
                    qr = data['code']
                elif 'pairingCode' in data:
                    return False, f"Use o código de pareamento: {data['pairingCode']}"
                elif data.get('instance', {}).get('state') == 'open':
                    return False, "WhatsApp já está conectado!"

            if qr:
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

    def verificar_numeros(self, numeros):
        """
        Verifica quais números têm WhatsApp ativo.

        Args:
            numeros: lista de strings com números (ex: ['5511999999999'])

        Returns:
            dict: { 'numero': {'exists': bool, 'jid': str} }
        """
        if not self.ok():
            return {}

        nums = [str(n) for n in numeros if n]
        if not nums:
            return {}

        result = {}
        ok, r = self._req('POST', f"/chat/whatsappNumbers/{self.instance}", {'numbers': nums})

        if ok and r.status_code == 200:
            try:
                data = r.json()
                if isinstance(data, list):
                    for item in data:
                        num = ''.join(filter(str.isdigit, str(item.get('number', ''))))
                        exists = item.get('exists', False) or item.get('numberExists', False)
                        jid = item.get('jid', '')
                        if num:
                            result[num] = {'exists': exists, 'jid': jid}
                elif isinstance(data, dict):
                    for num, info in data.items():
                        num_clean = ''.join(filter(str.isdigit, num))
                        if isinstance(info, dict):
                            result[num_clean] = {'exists': info.get('exists', False), 'jid': info.get('jid', '')}
                        else:
                            result[num_clean] = {'exists': bool(info), 'jid': ''}
            except Exception:
                pass

        return result

    def enviar(self, numero, texto):
        """
        Envia mensagem de texto via WhatsApp.

        Returns:
            (True, message_id) ou (False, erro)
        """
        if not self.ok():
            return False, "Não configurado"

        num = ''.join(filter(str.isdigit, str(numero)))
        ok, r = self._req('POST', f"/message/sendText/{self.instance}", {
            'number': num,
            'text': texto,
            'linkPreview': False
        })

        if ok and r.status_code in [200, 201]:
            try:
                mid = r.json().get('key', {}).get('id', '')
                return True, mid
            except Exception:
                return True, ''
        return False, r.text[:100] if ok else r

    def enviar_arquivo(self, numero, caminho_arquivo, caption=None):
        """
        Envia arquivo (PDF, imagem, etc.) via WhatsApp.

        Args:
            numero: Número do destinatário
            caminho_arquivo: Caminho completo do arquivo no servidor
            caption: Legenda opcional

        Returns:
            (True, message_id) ou (False, erro)
        """
        if not self.ok():
            return False, "Não configurado"

        if not os.path.exists(caminho_arquivo):
            return False, f"Arquivo não encontrado: {caminho_arquivo}"

        ext = os.path.splitext(caminho_arquivo)[1].lower()
        tipo_map = {
            '.pdf':  'application/pdf',
            '.jpg':  'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png':  'image/png',
            '.mp4':  'video/mp4',
            '.mp3':  'audio/mpeg',
        }
        mimetype = tipo_map.get(ext, 'application/octet-stream')

        try:
            with open(caminho_arquivo, 'rb') as f:
                arquivo_b64 = base64.b64encode(f.read()).decode('utf-8')

            num = ''.join(filter(str.isdigit, str(numero)))
            nome_arquivo = os.path.basename(caminho_arquivo)

            mediatype = 'image' if ext in ['.jpg', '.jpeg', '.png'] else 'document'

            payload = {
                'number': num,
                'mediatype': mediatype,
                'mimetype': mimetype,
                'media': arquivo_b64,
                'fileName': nome_arquivo
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
# =============================================================================

def _print_resultado(titulo, ok, detalhe):
    status = "OK" if ok else "FALHOU"
    print(f"  [{status}] {titulo}")
    if detalhe:
        detalhe_str = json.dumps(detalhe, ensure_ascii=False, indent=4) if isinstance(detalhe, (dict, list)) else str(detalhe)
        for linha in detalhe_str.splitlines():
            print(f"          {linha}")


def testar_configuracao(client):
    print("\n--- Configuração ---")
    ok = client.ok()
    _print_resultado("URL, API Key e instância preenchidos", ok,
                     None if ok else "Defina EVOLUTION_API_URL, EVOLUTION_API_KEY e EVOLUTION_INSTANCE")


def testar_listar_instancias(client):
    print("\n--- Listar Instâncias ---")
    ok, resultado = client.listar_instancias()
    if ok and isinstance(resultado, list):
        nomes = [
            (i.get('instance', {}).get('instanceName') or i.get('instanceName', '?'))
            for i in resultado
        ]
        _print_resultado(f"Instâncias encontradas ({len(resultado)})", True, nomes)
    else:
        _print_resultado("Listar instâncias", ok, resultado)
    return ok, resultado


def testar_status_conexao(client):
    print("\n--- Status da Conexão ---")
    conectado, estado = client.conectado()
    _print_resultado(f"Estado: {estado}", conectado, None)
    return conectado


def testar_webhook(client):
    print("\n--- Webhook ---")
    ok, config = client.obter_webhook_config()
    _print_resultado("Obter configuração atual do webhook", ok, config if ok else config)


def testar_verificar_numeros(client, numeros):
    print("\n--- Verificar Números no WhatsApp ---")
    if not numeros:
        print("  [PULADO] Defina NUMERO_TESTE para executar este teste")
        return
    resultado = client.verificar_numeros(numeros)
    for num, info in resultado.items():
        _print_resultado(f"Número {num}", info.get('exists', False),
                         f"JID: {info.get('jid', '-')}")
    if not resultado:
        _print_resultado("Verificar números", False, "Sem resultado da API")


def testar_enviar_mensagem(client, numero, texto="Teste de integração Evolution API - pode ignorar."):
    print("\n--- Enviar Mensagem de Texto ---")
    if not numero:
        print("  [PULADO] Defina NUMERO_TESTE para executar este teste")
        return
    ok, resultado = client.enviar(numero, texto)
    _print_resultado(f"Enviar para {numero}", ok, resultado)


def testar_qrcode(client):
    print("\n--- QR Code ---")
    ok, resultado = client.qrcode()
    if ok:
        _print_resultado("QR Code obtido", True, f"{len(resultado)} caracteres (base64)")
    else:
        _print_resultado("QR Code", False, resultado)


# =============================================================================
# EXECUÇÃO PRINCIPAL
# =============================================================================

def main():
    print("=" * 60)
    print("  Testes Funcionais - Evolution API (WhatsApp)")
    print("=" * 60)
    print(f"  URL:       {EVOLUTION_API_URL or '(não definido)'}")
    print(f"  Instância: {EVOLUTION_INSTANCE or '(não definido)'}")
    print(f"  API Key:   {'***' + EVOLUTION_API_KEY[-4:] if len(EVOLUTION_API_KEY) > 4 else '(não definido)'}")

    client = EvolutionAPIClient(EVOLUTION_API_URL, EVOLUTION_API_KEY, EVOLUTION_INSTANCE)

    # 1. Verificar configuração básica
    testar_configuracao(client)

    if not client.ok():
        print("\nABORTANDO: configure as variáveis de ambiente e tente novamente.")
        print("  export EVOLUTION_API_URL=https://sua-api.com")
        print("  export EVOLUTION_API_KEY=sua_chave")
        print("  export EVOLUTION_INSTANCE=nome_instancia")
        return

    # 2. Listar instâncias (valida conectividade + API key)
    testar_listar_instancias(client)

    # 3. Status da conexão
    conectado = testar_status_conexao(client)

    # 4. Webhook
    testar_webhook(client)

    # 5. Verificar número (opcional)
    if NUMERO_TESTE:
        testar_verificar_numeros(client, [NUMERO_TESTE])

    # 6. QR Code (só se desconectado)
    if not conectado:
        testar_qrcode(client)
    else:
        print("\n--- QR Code ---")
        print("  [PULADO] Instância já conectada")

    # 7. Enviar mensagem (opcional, requer instância conectada)
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
