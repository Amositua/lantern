from typing import Callable, Dict

from .gcp_clients import ClientInitError


def run_checks(checks: Dict[str, Callable[[], object]]) -> Dict[str, str]:
    """Attempts each client factory and reports init state without raising.

    Used by every service's /health/deep route so a missing project id or
    a real client-construction bug are visibly different outcomes.
    """
    results: Dict[str, str] = {}
    for name, factory in checks.items():
        try:
            factory()
            results[name] = "initialized"
        except ClientInitError as exc:
            results[name] = f"not configured: {exc}"
        except Exception as exc:  # noqa: BLE001 - surfaced to the caller, not swallowed
            results[name] = f"error: {exc}"
    return results
