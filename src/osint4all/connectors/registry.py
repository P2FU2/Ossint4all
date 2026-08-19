"""Registro de conectores habilitados."""

from __future__ import annotations

from osint4all.config import ALL_CONNECTORS, Settings, get_settings
from osint4all.connectors.base import Connector
from osint4all.connectors.cnpj_receita import CnpjReceitaConnector
from osint4all.connectors.datajud import DatajudConnector
from osint4all.connectors.djen import DjenConnector
from osint4all.connectors.opencorporates import OpenCorporatesConnector
from osint4all.connectors.tse import TseConnector
from osint4all.connectors.transparencia import TransparenciaConnector
from osint4all.connectors.crtsh import CrtshConnector
from osint4all.connectors.plate_public import PlatePublicConnector
from osint4all.connectors.socio_search import SocioSearchConnector
from osint4all.connectors.username_public import UsernamePublicConnector
from osint4all.connectors.web_search import WebSearchConnector
from osint4all.connectors.wikidata import WikidataConnector

_BUILDERS = {
    "cnpj_receita": CnpjReceitaConnector,
    "datajud": DatajudConnector,
    "djen": DjenConnector,
    "tse": TseConnector,
    "transparencia": TransparenciaConnector,
    "opencorporates": OpenCorporatesConnector,
    "wikidata": WikidataConnector,
    "web_search": WebSearchConnector,
    "username_public": UsernamePublicConnector,
    "crtsh": CrtshConnector,
    "plate_public": PlatePublicConnector,
    "socio_search": SocioSearchConnector,
}


def build_connectors(settings: Settings | None = None) -> list[Connector]:
    settings = settings or get_settings()
    return [cls(settings) for cls in _BUILDERS.values()]


def enabled_connector_names(settings: Settings | None = None) -> list[str]:
    settings = settings or get_settings()
    flags = {
        "cnpj_receita": settings.cnpj_enable,
        "datajud": settings.datajud_enable,
        "djen": settings.djen_enable,
        "tse": settings.tse_enable,
        "transparencia": settings.transparencia_enable,
        "opencorporates": settings.opencorporates_enable,
        "wikidata": settings.wikidata_enable,
        "web_search": settings.web_search_enable,
        "username_public": settings.username_public_enable,
        "crtsh": settings.crtsh_enable,
        "plate_public": settings.plate_public_enable,
        "socio_search": settings.socio_search_enable,
    }
    return [name for name in ALL_CONNECTORS if flags.get(name)]


def connector_health(settings: Settings | None = None) -> list[dict]:
    return [c.health() for c in build_connectors(settings)]
