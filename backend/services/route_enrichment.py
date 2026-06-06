"""Compatibility imports for the retired route enrichment service.

The active implementation lives in ``services.enroute_discovery``. Keeping
this module avoids breaking older imports while removing the truncated legacy
implementation that previously lived here.
"""

from models.route import EnroutePOI
from services.enroute_discovery import EnrouteDiscoveryService, get_enroute_discovery

__all__ = ["EnrouteDiscoveryService", "EnroutePOI", "get_enroute_discovery"]
