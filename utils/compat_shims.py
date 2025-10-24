# utils/compat_shims.py
# -*- coding: utf-8 -*-
from __future__ import annotations

"""
Compat shims to keep the app bootable when optional modules are missing.
- Security shims are permissive (return True / empty headers) to avoid breaking routes
  when signatures are disabled by ENV.
- Trading shims are **NOT** permissive: they raise NotImplementedError to prevent any
  accidental live trading via a stub.
"""

from typing import Any, Dict
import os
import logging

_log = logging.getLogger("algogpt.compat_shims")


def _env_true(name: str, default: str = "0") -> bool:
    return (os.getenv(name, default) or "").strip().lower() in ("1", "true", "yes", "on")


def _warn_once(key: str, msg: str) -> None:
    attr = f"_warned_{key}"
    if not getattr(_log, attr, False):
        _log.warning(msg)
        setattr(_log, attr, True)


# --- anti-replay / security (כאשר חתימות מבוטלות) ---
def verify_hmac(*args, **kwargs) -> bool:
    """
    Shim: return True when signatures are disabled by ENV.
    If STRICT_SIGNATURES=1, fail hard to avoid silent bypass in strict envs.
    """
    if _env_true("STRICT_SIGNATURES", "0"):
        raise NotImplementedError("verify_hmac shim used while STRICT_SIGNATURES=1")
    _warn_once("verify_hmac", "compat_shims.verify_hmac() in use (signatures disabled).")
    return True


def build_signature_headers(*args, **kwargs) -> Dict[str, str]:
    """
    Shim: return empty headers when signatures are disabled.
    """
    _warn_once("build_signature_headers", "compat_shims.build_signature_headers() in use (signatures disabled).")
    return {}


# --- executor ---
def is_executor_running() -> bool:
    """
    Shim: report executor as running unless explicitly overridden.
    Set EXECUTOR_RUNNING_SHIM=0 to report False.
    """
    val = _env_true("EXECUTOR_RUNNING_SHIM", "1")
    if val:
        _warn_once("is_executor_running", "compat_shims.is_executor_running() returning True (shim).")
    return val


# --- binance client shims ---
def place_limit_order(*args, **kwargs) -> Dict[str, Any]:
    """
    Non-permissive shim: trading calls must not be faked.
    Replace with utils.binance_client.place_limit_order.
    """
    raise NotImplementedError("compat shim: implement utils.binance_client.place_limit_order")


def get_order(*args, **kwargs) -> Dict[str, Any]:
    """
    Non-permissive shim: trading queries must be implemented explicitly.
    Replace with utils.binance_client.get_order.
    """
    raise NotImplementedError("compat shim: implement utils.binance_client.get_order")


# --- indicators ext ---
def advanced_indicators(*args, **kwargs) -> Dict[str, Any]:
    """
    Shim: return empty indicators payload.
    """
    _warn_once("advanced_indicators", "compat_shims.advanced_indicators() returning empty dict (shim).")
    return {}


# --- storage shim (news / generic kv-cache) ---
class _DummyStorage:
    def get(self, *a, **k):
        _warn_once("storage_get", "compat_shims.storage.get() -> None (shim).")
        return None

    def put(self, *a, **k):
        _warn_once("storage_put", "compat_shims.storage.put() -> True (shim).")
        return True


storage = _DummyStorage()

