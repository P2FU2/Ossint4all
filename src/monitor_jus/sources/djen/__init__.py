"""Cliente DJEN / Comunica API."""

from monitor_jus.sources.djen.client import DjenClient
from monitor_jus.sources.djen.criteria import DjenSearchCriteria

__all__ = ["DjenClient", "DjenSearchCriteria"]
