# -*- coding: utf-8 -*-
from __future__ import annotations

import os
import pkgutil
import importlib
import logging
from contextlib import suppress
from types import ModuleType
from typing import Iterable, Optional, Set

from fastapi import FastAPI
from fastapi.routing import APIRouter

log = logging.getLogger("algogpt.routes_autoload")

def _as_set(csv: Optional[str]) -> Optional[Set[str]]:
    if csv is None:
        return None
    s = {x.strip() for x in str(csv).split(",") if x.strip()}
    return s or None

def _should_take(name: str, allow: Optional[Set[str]], deny: Optional[Set[str]]) -> bool:
    if allow and "*" not in allow and name not in allow:
        return False
    if deny and name in deny:
        return False
    return True

def _include_router_if_present(app: FastAPI, module: ModuleType, verbose: bool = False) -> bool:
    router = getattr(module, "router", None)
    if isinstance(router, APIRouter):
        app.include_router(router)
        if verbose:
            log.info("routes_autoload: mounted router from %s", module.__name__)
        return True
    return False

def _call_setup_if_present(app: FastAPI, module: ModuleType, verbose: bool = False) -> bool:
    setup = getattr(module, "setup", None)
    if callable(setup):
        try:
            setup(app)
            if verbose:
                log.info("routes_autoload: called setup(app) on %s", module.__name__)
            return True
        except Exception as e:
            log.warning("routes_autoload: setup(app) failed on %s: %s", module.__name__, e)
    return False

def _iter_route_modules(package: str = "routes"):
    with suppress(Exception):
        pkg = importlib.import_module(package)
        for m in pkgutil.iter_modules(pkg.__path__, prefix=f"{package}."):
            if not m.ispkg:
                yield m.name

def autoload_routes(
    app: FastAPI,
    package: str = "routes",
    *,
    allow: Optional[Iterable[str]] = None,
    deny: Optional[Iterable[str]] = None,
    verbose: Optional[bool] = None,
) -> None:
    """
    Auto-detect and mount all modules under `package` that expose either:
      - `router: fastapi.APIRouter`
      - `setup(app: FastAPI)` function

    Environment knobs:
      ROUTES_ALLOW="*" | "scan,market,status"
      ROUTES_DENY="debug,backtest"
      ROUTES_VERBOSE=1
    """
    if verbose is None:
        verbose = (os.getenv("ROUTES_VERBOSE", "0").lower() in ("1", "true", "yes", "on"))

    allow_set = set(allow) if allow else _as_set(os.getenv("ROUTES_ALLOW", "*"))
    deny_set = set(deny) if deny else _as_set(os.getenv("ROUTES_DENY", ""))

    if verbose:
        log.info("routes_autoload: scanning package=%s allow=%s deny=%s", package, allow_set, deny_set)

    for fqmn in _iter_route_modules(package):
        base = fqmn.split(".")[-1]
        if not _should_take(base, allow_set, deny_set):
            if verbose:
                log.debug("routes_autoload: skip %s (filtered)", fqmn)
            continue
        try:
            mod = importlib.import_module(fqmn)
        except Exception as e:
            log.warning("routes_autoload: import failed for %s: %s", fqmn, e)
            continue

        mounted = _include_router_if_present(app, mod, verbose=verbose)
        called = _call_setup_if_present(app, mod, verbose=verbose)

        if not (mounted or called) and verbose:
            log.debug("routes_autoload: %s has neither router nor setup(app) — no-op", fqmn)

