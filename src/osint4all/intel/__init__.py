"""Inteligência de rede do dossiê: indexa evidência já conhecida. Sem scan."""

from osint4all.intel.google import classify_google_url, public_google_hints
from osint4all.intel.hosts import (
    HostCard,
    HostObservation,
    correlate_hosts,
    extract_same_domain_links,
    observation_from_payload,
    parse_banner_record,
    parse_http_snapshot,
    parse_imported_host_rows,
    parse_robots,
    parse_security_txt,
)

__all__ = [
    "HostCard",
    "HostObservation",
    "classify_google_url",
    "correlate_hosts",
    "extract_same_domain_links",
    "observation_from_payload",
    "parse_banner_record",
    "parse_http_snapshot",
    "parse_imported_host_rows",
    "parse_robots",
    "parse_security_txt",
    "public_google_hints",
]
