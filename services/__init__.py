"""
Service package marker.

Intentionally empty to avoid heavy imports at package import time.
Import the concrete modules directly, e.g.:

    from services.metrics import log_http, init_metrics_tables
    from services.storage import init_db, save_event, get_saved_events
    from services.aggregator import search_events, PROVIDERS
"""
__all__: list[str] = []