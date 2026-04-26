"""Models package: aggregates all model modules and re-exports their public
names so callers can keep doing ``from app.models import Campanha`` (or, via
the legacy ``from app.main import *`` shim in ``app/__init__.py``, the older
``from app import Campanha``)."""

from app.models.usuario import Usuario
from app.models.core import (
    ConfigGlobal,
    ConfigWhatsApp,
    RespostaAutomatica,
    Tutorial,
    ProcedimentoNormalizado,
)
from app.models.fila import (
    Campanha,
    Contato,
    Telefone,
    LogMsg,
    TicketAtendimento,
    TentativaContato,
    ConfigTentativas,
)
from app.models.consulta import (
    CampanhaConsulta,
    AgendamentoConsulta,
    TelefoneConsulta,
    LogMsgConsulta,
    PesquisaSatisfacao,
    Paciente,
    ComprovanteAntecipado,
    HistoricoConsulta,
    normalizar_nome_paciente,
    buscar_comprovante_antecipado,
)
from app.models.geral import (
    ConfigUsuarioGeral,
    TIPOS_PERGUNTA,
    Pesquisa,
    PerguntaPesquisa,
    RespostaPesquisa,
    RespostaItem,
    STATUS_ENVIO_PESQUISA,
    STATUS_ENVIO_TELEFONE,
    TEMPLATES_PESQUISA,
    EnvioPesquisa,
    EnvioPesquisaTelefone,
)


__all__ = [
    'Usuario',
    'ConfigGlobal', 'ConfigWhatsApp', 'RespostaAutomatica', 'Tutorial',
    'ProcedimentoNormalizado',
    'Campanha', 'Contato', 'Telefone', 'LogMsg', 'TicketAtendimento',
    'TentativaContato', 'ConfigTentativas',
    'CampanhaConsulta', 'AgendamentoConsulta', 'TelefoneConsulta',
    'LogMsgConsulta', 'PesquisaSatisfacao', 'Paciente',
    'ComprovanteAntecipado', 'HistoricoConsulta',
    'normalizar_nome_paciente', 'buscar_comprovante_antecipado',
    'ConfigUsuarioGeral', 'TIPOS_PERGUNTA', 'Pesquisa', 'PerguntaPesquisa',
    'RespostaPesquisa', 'RespostaItem', 'STATUS_ENVIO_PESQUISA',
    'STATUS_ENVIO_TELEFONE', 'TEMPLATES_PESQUISA', 'EnvioPesquisa',
    'EnvioPesquisaTelefone',
]
