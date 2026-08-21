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
from osint4all.connectors.diario_oficial import DiarioOficialConnector
from osint4all.connectors.geo_public import GeoPublicConnector
from osint4all.connectors.plate_public import PlatePublicConnector
from osint4all.connectors.rdap_public import RdapPublicConnector
from osint4all.connectors.shodan_public import ShodanPublicConnector
from osint4all.connectors.host_public import HostPublicConnector
from osint4all.connectors.email_public import EmailPublicConnector
from osint4all.connectors.phone_public import PhonePublicConnector
from osint4all.connectors.aleph_public import AlephPublicConnector
from osint4all.connectors.censys_public import CensysPublicConnector
from osint4all.connectors.host_observe import HostObserveConnector
from osint4all.connectors.google_public import GooglePublicConnector
from osint4all.connectors.pncp_public import PncpPublicConnector
from osint4all.connectors.congresso_public import CongressoPublicConnector
from osint4all.connectors.opensanctions_public import OpensanctionsPublicConnector
from osint4all.connectors.gleif_public import GleifPublicConnector
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
    "diario_oficial": DiarioOficialConnector,
    "geo_public": GeoPublicConnector,
    "rdap_public": RdapPublicConnector,
    "shodan_public": ShodanPublicConnector,
    "host_public": HostPublicConnector,
    "email_public": EmailPublicConnector,
    "phone_public": PhonePublicConnector,
    "aleph_public": AlephPublicConnector,
    "censys_public": CensysPublicConnector,
    "host_observe": HostObserveConnector,
    "google_public": GooglePublicConnector,
    "pncp_public": PncpPublicConnector,
    "congresso_public": CongressoPublicConnector,
    "opensanctions_public": OpensanctionsPublicConnector,
    "gleif_public": GleifPublicConnector,
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
        "diario_oficial": settings.diario_oficial_enable,
        "geo_public": settings.geo_public_enable,
        "rdap_public": settings.rdap_public_enable,
        "shodan_public": settings.shodan_enable,
        "host_public": settings.host_public_enable,
        "email_public": settings.email_public_enable,
        "phone_public": settings.phone_public_enable,
        "aleph_public": settings.aleph_public_enable,
        "censys_public": settings.censys_enable,
        "host_observe": settings.host_observe_enable,
        "google_public": settings.google_public_enable,
        "pncp_public": settings.pncp_public_enable,
        "congresso_public": settings.congresso_public_enable,
        "opensanctions_public": settings.opensanctions_public_enable,
        "gleif_public": settings.gleif_public_enable,
    }
    return [name for name in ALL_CONNECTORS if flags.get(name)]


def connector_health(settings: Settings | None = None) -> list[dict]:
    return [c.health() for c in build_connectors(settings)]
