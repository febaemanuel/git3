"""WhatsApp Evolution API client."""

import logging
import time

import requests

from app.models.core import ConfigGlobal, ConfigWhatsApp


logger = logging.getLogger(__name__)


class WhatsApp:
    def __init__(self, usuario_id=None):
        """
        Inicializa conexão WhatsApp para um usuário específico
        API URL e Key vêm do ConfigGlobal (admin)
        Instance name é única por usuário

        Args:
            usuario_id: ID do usuário (obrigatório)
        """
        if not usuario_id:
            # Fallback: pegar do current_user se disponível
            from flask_login import current_user
            if current_user and current_user.is_authenticated:
                usuario_id = current_user.id
            else:
                raise ValueError("usuario_id é obrigatório para WhatsApp")

        # Buscar config global (API URL e Key definidos pelo admin)
        cfg_global = ConfigGlobal.get()

        # Buscar config do usuário (instance name única)
        cfg_user = ConfigWhatsApp.get(usuario_id)

        self.url = (cfg_global.evolution_api_url or '').rstrip('/')
        self.key = cfg_global.evolution_api_key or ''
        self.instance = cfg_user.instance_name or ''
        self.ativo = cfg_global.ativo  # Global ativo
        self.usuario_id = usuario_id
        self.cfg_user = cfg_user  # Guardar referência para atualizar depois

        # Configurações de envio (valores padrão)
        self.tempo_entre_envios = cfg_user.tempo_entre_envios or 15  # 15 segundos padrão
        self.limite_diario = cfg_user.limite_diario or 500  # 500 mensagens/dia padrão

    def ok(self):
        """Verifica se configuração global está ativa"""
        return bool(self.ativo and self.url and self.instance and self.key)

    def _headers(self):
        return {'apikey': self.key, 'Content-Type': 'application/json'}

    def _req(self, method, endpoint, data=None):
        try:
            url = f"{self.url}{endpoint}"
            if method == 'GET':
                r = requests.get(url, headers=self._headers(), timeout=30)
            else:
                r = requests.post(url, headers=self._headers(), json=data, timeout=30)
            return True, r
        except Exception as e:
            return False, str(e)

    def conectado(self):
        if not self.ok():
            return False, "Nao configurado"
        ok, r = self._req('GET', f"/instance/connectionState/{self.instance}")
        if ok and r.status_code == 200:
            data = r.json()
            state = data.get('instance', {}).get('state', '')
            if not state:
                state = data.get('state', '')
            return state == 'open', state
        return False, "Erro ao verificar conexao"

    def listar_instancias(self):
        """Lista todas as instancias"""
        if not self.ok():
            return False, "Nao configurado"
        ok, r = self._req('GET', '/instance/fetchInstances')
        if ok and r.status_code == 200:
            return True, r.json()
        return False, f"Erro: {r.status_code if ok else r}"

    def criar_instancia(self):
        """Cria nova instancia"""
        if not self.ok():
            return False, "Nao configurado"

        ok, r = self._req('POST', '/instance/create', {
            'instanceName': self.instance,
            'token': self.key,
            'qrcode': True,
            'integration': 'WHATSAPP-BAILEYS'
        })

        if ok and r.status_code in [200, 201]:
            logger.info(f"Instancia criada: {self.instance}")

            # Configurar webhook automaticamente
            time.sleep(1)  # Aguardar instância ser criada
            webhook_ok, webhook_msg = self.configurar_webhook()
            if webhook_ok:
                logger.info(f"Webhook configurado automaticamente: {webhook_msg}")
            else:
                logger.warning(f"Falha ao configurar webhook: {webhook_msg}")

            return True, "Instancia criada"
        elif ok and r.status_code == 403:
            # Pode ser que ja existe
            if 'already' in r.text.lower():
                return True, "Instancia ja existe"
        elif ok and r.status_code == 409:
            return True, "Instancia ja existe"

        return False, f"Erro ao criar: {r.status_code if ok else r}"

    def obter_webhook_config(self):
        """Obtém configuração atual do webhook"""
        if not self.ok():
            return False, "Nao configurado"

        ok, r = self._req('GET', f'/webhook/find/{self.instance}')
        if ok and r.status_code == 200:
            try:
                data = r.json()
                logger.info(f"Webhook atual: {data}")
                return True, data
            except:
                return False, "Erro ao parsear resposta"
        return False, f"Erro ao obter webhook: {r.status_code if ok else r}"

    def configurar_webhook(self):
        """Configura webhook para receber mensagens automaticamente"""
        if not self.ok():
            return False, "Nao configurado"

        # Determinar URL do webhook baseado no request atual ou configuração
        try:
            from flask import request
            if request:
                # Usar o domínio da requisição atual, mas sempre com HTTPS
                host = request.host
                webhook_url = f"https://{host}/webhook/whatsapp"
            else:
                raise Exception("Request context not available")
        except:
            # Fallback: tentar obter do ambiente ou usar padrão
            import os
            base_url = os.environ.get('BASE_URL', 'https://chsistemas.cloud')
            webhook_url = f"{base_url}/webhook/whatsapp"

        # Primeiro, tentar obter config atual para ver formato
        logger.info("Verificando webhook atual...")
        ok_get, current = self.obter_webhook_config()
        if ok_get:
            logger.info(f"Config webhook atual: {current}")

        # Lista completa de eventos
        all_events = [
            'APPLICATION_STARTUP',
            'CALL',
            'CHATS_DELETE',
            'CHATS_SET',
            'CHATS_UPDATE',
            'CHATS_UPSERT',
            'CONNECTION_UPDATE',
            'CONTACTS_SET',
            'CONTACTS_UPDATE',
            'CONTACTS_UPSERT',
            'GROUP_PARTICIPANTS_UPDATE',
            'GROUP_UPDATE',
            'GROUPS_UPSERT',
            'LABELS_ASSOCIATION',
            'LABELS_EDIT',
            'MESSAGES_DELETE',
            'MESSAGES_SET',
            'MESSAGES_UPDATE',
            'MESSAGES_UPSERT',
            'PRESENCE_UPDATE',
            'QRCODE_UPDATED',
            'SEND_MESSAGE'
        ]

        # Eventos essenciais para mensagens (fallback)
        essential_events = [
            'MESSAGES_UPSERT',
            'MESSAGES_UPDATE',
            'SEND_MESSAGE',
            'CONNECTION_UPDATE'
        ]

        # Tentar primeiro com configuração simplificada
        # A Evolution API espera o objeto dentro de "webhook"
        webhook_config = {
            'enabled': True,
            'url': webhook_url,
            'webhookByEvents': False,
            'webhookBase64': False,
            'events': essential_events
        }

        payload = {
            'webhook': webhook_config
        }

        logger.info(f"Configurando webhook com eventos essenciais: {essential_events}")
        logger.info(f"Payload: {payload}")
        ok, r = self._req('POST', f'/webhook/set/{self.instance}', payload)

        # Se funcionar com essenciais, tentar adicionar mais eventos
        if ok and r.status_code in [200, 201]:
            logger.info(f"Webhook configurado com eventos essenciais, tentando adicionar mais...")
            webhook_config['events'] = all_events
            payload['webhook'] = webhook_config
            ok2, r2 = self._req('POST', f'/webhook/set/{self.instance}', payload)
            if ok2 and r2.status_code in [200, 201]:
                logger.info(f"Webhook atualizado com todos os eventos")
                r = r2  # Use the successful response
            else:
                logger.warning(f"Não foi possível adicionar todos eventos, mantendo essenciais")
                # Manter a configuração com eventos essenciais que funcionou

        if ok and r.status_code in [200, 201]:
            logger.info(f"Webhook configurado para {self.instance}: {webhook_url}")
            return True, f"Webhook ativado: {webhook_url}"

        # Log detalhado do erro
        error_detail = ""
        if ok:
            try:
                error_detail = r.json() if hasattr(r, 'json') else r.text
                logger.error(f"Erro webhook {r.status_code}: {error_detail}")
            except:
                error_detail = r.text if hasattr(r, 'text') else str(r)
                logger.error(f"Erro webhook {r.status_code}: {error_detail}")
        else:
            logger.error(f"Erro webhook: {r}")
            error_detail = str(r)

        return False, f"Erro ao configurar webhook: {r.status_code if ok else 'conexão falhou'} - {error_detail}"

    def qrcode(self):
        """
        Obtem QR Code para conectar WhatsApp
        Baseado na implementacao funcional da Evolution API v2
        """
        if not self.ok():
            return False, "WhatsApp nao configurado. Preencha URL, Nome da Instancia e API Key."

        try:
            logger.info(f"=== OBTENDO QR CODE ===")
            logger.info(f"Instancia: {self.instance}")
            logger.info(f"URL: {self.url}")

            # Passo 1: Verifica se instancia existe
            sucesso, instances = self.listar_instancias()

            if not sucesso:
                if "403" in str(instances):
                    return False, "API Key invalida. Verifique a configuracao."
                return False, f"Erro ao verificar instancias: {instances}"

            # Verifica se nossa instancia existe
            instance_exists = False
            if isinstance(instances, list):
                for inst in instances:
                    inst_name = inst.get('instance', {}).get('instanceName') or inst.get('instanceName')
                    if inst_name == self.instance:
                        instance_exists = True
                        state = inst.get('instance', {}).get('status') or inst.get('state') or inst.get('instance', {}).get('state')
                        logger.info(f"Instancia encontrada - Estado: {state}")

                        if state == 'open':
                            return False, "WhatsApp ja esta conectado!"
                        break

            # Passo 2: Se nao existe, cria
            if not instance_exists:
                logger.info("Instancia nao existe, criando...")
                sucesso, msg = self.criar_instancia()
                if not sucesso:
                    return False, f"Erro ao criar instancia: {msg}"
                logger.info("Instancia criada, aguardando...")
                time.sleep(2)

            # Passo 3: Conecta e obtem QR Code
            ok, r = self._req('GET', f"/instance/connect/{self.instance}")

            logger.info(f"Response Status: {r.status_code if ok else 'erro'}")

            if ok and r.status_code == 200:
                data = r.json()
                logger.info(f"Response data keys: {list(data.keys()) if isinstance(data, dict) else type(data)}")

                qrcode = None

                # Formato 1: { "base64": "data:image..." }
                if isinstance(data, dict):
                    if 'base64' in data:
                        qrcode = data['base64']
                        logger.info("QR Code encontrado (formato: base64)")

                    # Formato 2: { "qrcode": { "base64": "..." } }
                    elif 'qrcode' in data:
                        qr_obj = data['qrcode']
                        if isinstance(qr_obj, dict):
                            qrcode = qr_obj.get('base64') or qr_obj.get('code')
                        elif isinstance(qr_obj, str):
                            qrcode = qr_obj
                        if qrcode:
                            logger.info("QR Code encontrado (formato: qrcode)")

                    # Formato 3: { "code": "..." }
                    elif 'code' in data:
                        qrcode = data['code']
                        logger.info("QR Code encontrado (formato: code)")

                    # Formato 4: Pairing code
                    elif 'pairingCode' in data:
                        pairing = data['pairingCode']
                        logger.info(f"Pairing code: {pairing}")
                        return False, f"Use o codigo de pareamento: {pairing}"

                    # Formato 5: Ja conectado
                    elif data.get('instance', {}).get('state') == 'open':
                        return False, "WhatsApp ja esta conectado!"

                if qrcode:
                    if not qrcode.startswith('data:image'):
                        qrcode = f"data:image/png;base64,{qrcode}"
                    logger.info(f"QR Code retornado ({len(qrcode)} chars)")
                    return True, qrcode
                else:
                    logger.warning(f"QR nao encontrado. Resposta: {str(data)[:300]}")
                    return False, "QR Code nao disponivel. Tente novamente em alguns segundos."

            elif ok and r.status_code == 404:
                return False, "Instancia nao encontrada. Verifique o nome da instancia."

            elif ok and r.status_code in [401, 403]:
                return False, "API Key invalida."

            else:
                error_msg = f"HTTP {r.status_code}: {r.text[:200]}" if ok else str(r)
                logger.error(f"Erro: {error_msg}")
                return False, error_msg

        except requests.exceptions.ConnectionError as e:
            logger.error(f"Erro de conexao: {e}")
            return False, f"Nao foi possivel conectar em {self.url}. Verifique se a Evolution API esta rodando."

        except Exception as e:
            logger.error(f"Excecao ao obter QR Code: {e}", exc_info=True)
            return False, f"Erro: {str(e)}"

    def verificar_numeros(self, numeros):
        """Verifica lista de numeros no WhatsApp"""
        if not self.ok():
            return {}

        result = {}
        nums = [str(n) for n in numeros if n]
        if not nums:
            return {}

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
            except:
                pass
        return result

    def enviar(self, numero, texto):
        if not self.ok():
            return False, "Nao configurado"

        num = ''.join(filter(str.isdigit, str(numero)))
        ok, r = self._req('POST', f"/message/sendText/{self.instance}", {
            'number': num,
            'text': texto,
            'linkPreview': False  # Desabilita preview de links
        })

        if ok and r.status_code in [200, 201]:
            try:
                mid = r.json().get('key', {}).get('id', '')
                return True, mid
            except:
                return True, ''
        return False, r.text[:100] if ok else r

    def enviar_arquivo(self, numero, caminho_arquivo, caption=None):
        """
        Envia arquivo (PDF, imagem, etc) via WhatsApp

        Args:
            numero: Número do destinatário
            caminho_arquivo: Caminho completo do arquivo no servidor
            caption: Texto opcional para acompanhar o arquivo (legenda)

        Returns:
            (sucesso: bool, mensagem_id ou erro: str)
        """
        if not self.ok():
            return False, "Nao configurado"

        import os
        import base64

        # Verificar se arquivo existe
        if not os.path.exists(caminho_arquivo):
            return False, f"Arquivo nao encontrado: {caminho_arquivo}"

        # Determinar tipo de mídia baseado na extensão
        ext = os.path.splitext(caminho_arquivo)[1].lower()
        tipo_map = {
            '.pdf': 'application/pdf',
            '.jpg': 'image/jpeg',
            '.jpeg': 'image/jpeg',
            '.png': 'image/png',
            '.mp4': 'video/mp4',
            '.mp3': 'audio/mpeg',
        }

        mimetype = tipo_map.get(ext, 'application/octet-stream')

        try:
            # Ler arquivo e converter para base64
            with open(caminho_arquivo, 'rb') as f:
                arquivo_base64 = base64.b64encode(f.read()).decode('utf-8')

            num = ''.join(filter(str.isdigit, str(numero)))
            nome_arquivo = os.path.basename(caminho_arquivo)

            # Montar payload dependendo do tipo
            if ext in ['.jpg', '.jpeg', '.png']:
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'image',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }
                if caption:
                    payload['caption'] = caption
            elif ext == '.pdf':
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'document',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }
                if caption:
                    payload['caption'] = caption
            else:
                endpoint = f"/message/sendMedia/{self.instance}"
                payload = {
                    'number': num,
                    'mediatype': 'document',
                    'mimetype': mimetype,
                    'media': arquivo_base64,
                    'fileName': nome_arquivo
                }
                if caption:
                    payload['caption'] = caption

            ok, r = self._req('POST', endpoint, payload)

            if ok and r.status_code in [200, 201]:
                try:
                    mid = r.json().get('key', {}).get('id', '')
                    return True, mid
                except:
                    return True, ''
            else:
                erro = r.text[:200] if ok else str(r)
                logger.error(f"Erro ao enviar arquivo: {erro}")
                return False, erro

        except Exception as e:
            logger.exception(f"Exceção ao enviar arquivo: {e}")
            return False, str(e)
