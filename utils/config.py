# utils/config.py
# -*- coding: utf-8 -*-
from __future__ import annotations
import os
import json
import logging
from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, Union, Any

log = logging.getLogger("algogpt.config")

def _env_bool(name: str, default: bool = False) -> bool:
    v = str(os.getenv(name, "")).strip().lower()
    if v in ("1", "true", "yes", "y", "on", "enable", "enabled"):
        return True
    if v in ("0", "false", "no", "n", "off", "disable", "disabled"):
        return False
    return bool(default)

def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default

def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, str(default))))
    except Exception:
        return default

def _split_csv(s: Optional[str]) -> List[str]:
    if not s:
        return []
    return [x.strip() for x in s.split(",") if x.strip()]

def _load_json_env(name: str, fallback: Union[Dict[str, Any], str] = "{}") -> Dict[str, Any]:
    raw = os.getenv(name)
    src = raw if (raw and raw.strip()) else (fallback if isinstance(fallback, str) else json.dumps(fallback))
    try:
        obj = json.loads(src)
        return obj if isinstance(obj, dict) else {}
    except Exception:
        return {}

@dataclass
class Settings:
    APP_NAME: str = os.getenv("APP_NAME", "AlgoGPT")
    ENV: str = os.getenv("ENV", "dev")
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO")

    BINANCE_FUTURES_HTTP_BASE: str = os.getenv("BINANCE_FUTURES_HTTP_BASE", "https://fapi.binance.com")

    # allow both names
    AUTH_ALLOW_ALL: bool = _env_bool("ALLOW_ALL", _env_bool("AUTH_ALLOW_ALL", False))
    API_TOKENS: Set[str] = field(default_factory=set)

    AUTH_HEADER_CANDIDATES: List[str] = field(default_factory=lambda: [
        "Authorization", "X-API-Key", "X-Auth-Token", "X-Token", "X-Algogpt-Token", "X-Authorization",
    ])
    AUTH_QUERY_KEYS: List[str] = field(default_factory=lambda: ["api_key", "apikey", "token", "key", "auth"])
    AUTH_BEARER_PREFIXES: List[str] = field(default_factory=lambda: ["Bearer", "Token", "JWT"])
    AUTH_PUBLIC_PATHS: Set[str] = field(default_factory=lambda: {
        "/", "/ping", "/status", "/healthz", "/docs", "/redoc", "/openapi.json",
    })

    ALLOW_MARKET_ENTRY: bool = _env_bool("ALLOW_MARKET_ENTRY", True)
    ENTRY_BAND_BPS: float = _env_float("ENTRY_BAND_BPS", 8.5)
    STOP_BAND_BPS: float = _env_float("STOP_BAND_BPS", 10.0)
    ESCALATE_AFTER_SEC: float = _env_float("ESCALATE_AFTER_SEC", 10.0)
    ESCALATE_SLIPPAGE_BPS: float = _env_float("ESCALATE_SLIPPAGE_BPS", 15.0)

    PERCENT_PRICE_GUARD_BPS: float = _env_float("PERCENT_PRICE_GUARD_BPS", 45.0)
    SLIPPAGE_GUARD_BPS: float = _env_float("SLIPPAGE_GUARD_BPS", 35.0)
    POST_FILL_SANITY_BPS: float = _env_float("POST_FILL_SANITY_BPS", 40.0)

    MIN_QUALITY_SCORE: float = _env_float("MIN_QUALITY_SCORE", 7.0)
    MAX_ATR_PCT: float = _env_float("MAX_ATR_PCT", 2.5)
    MIN_VOLUME: float = _env_float("MIN_VOLUME", 0.0)

    LADDER_TP_ENABLE: bool = _env_bool("LADDER_TP_ENABLE", True)
    LADDER_TP_KIND: str = os.getenv("LADDER_TP_KIND", "TAKE_PROFIT_MARKET").upper()
    LADDER_TP_DEFAULT_PCTS: List[float] = field(default_factory=lambda: [1.8, 3.2, 5.5])
    LADDER_TP_DEFAULT_SPLITS: List[float] = field(default_factory=lambda: [0.4, 0.35, 0.25])
    LADDER_SL_ENABLE: bool = _env_bool("LADDER_SL_ENABLE", True)
    LADDER_SL_DEFAULT_PCTS: List[float] = field(default_factory=lambda: _split_csv(os.getenv("LADDER_SL_DEFAULT_PCTS", "0.8")) or [0.8])

    SL_DYNAMIC_ENABLE: bool = _env_bool("SL_DYNAMIC_ENABLE", True)
    SL_ATR_MULT: float = _env_float("SL_ATR_MULT", 0.6)
    SL_TRAIL_ENABLE: bool = _env_bool("SL_TRAIL_ENABLE", True)

    LEVERAGE_SYMBOL_CAPS: Dict[str, int] = field(default_factory=lambda: _load_json_env("LEVERAGE_SYMBOL_CAPS", '{"BTCUSDT":15,"1000PEPEUSDT":8}'))

    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    TELEGRAM_CHAT_ID_DEFAULT: int = _env_int("TELEGRAM_CHAT_ID", 0)
    TELEGRAM_PARSE_MODE: str = os.getenv("TELEGRAM_PARSE_MODE", "").strip()
    CONFIRM_TTL_SEC: int = _env_int("CONFIRM_TTL_SEC", 180)

    REDIS_URL: str = os.getenv("REDIS_URL", "").strip()

    DEFAULT_QTY_STEP: float = _env_float("DEFAULT_QTY_STEP", 0.001)
    DEFAULT_PRICE_TICK: float = _env_float("DEFAULT_PRICE_TICK", 0.01)
    MIN_NOTIONAL_USDT: float = _env_float("MIN_NOTIONAL_USDT", 5.0)

    IDEMPOTENCY_TTL_SEC: int = _env_int("IDEMPOTENCY_TTL_SEC", 15)

    ORDER_ID_PREFIX: str = os.getenv("ORDER_ID_PREFIX", "").strip()
    CANCEL_ONLY_PREFIXED_ORDERS: bool = _env_bool("CANCEL_ONLY_PREFIXED_ORDERS", False)

    def as_dict(self) -> Dict[str, object]:
        return {
            "APP_NAME": self.APP_NAME,
            "ENV": self.ENV,
            "BINANCE_FUTURES_HTTP_BASE": self.BINANCE_FUTURES_HTTP_BASE,
            "AUTH_ALLOW_ALL": self.AUTH_ALLOW_ALL,
            "TOKENS_COUNT": len(self.API_TOKENS),
            "AUTH_HEADER_CANDIDATES": self.AUTH_HEADER_CANDIDATES,
            "AUTH_QUERY_KEYS": self.AUTH_QUERY_KEYS,
            "AUTH_PUBLIC_PATHS": sorted(self.AUTH_PUBLIC_PATHS),
            "ALLOW_MARKET_ENTRY": self.ALLOW_MARKET_ENTRY,
            "ENTRY_BAND_BPS": self.ENTRY_BAND_BPS,
            "STOP_BAND_BPS": self.STOP_BAND_BPS,
            "ESCALATE_AFTER_SEC": self.ESCALATE_AFTER_SEC,
            "ESCALATE_SLIPPAGE_BPS": self.ESCALATE_SLIPPAGE_BPS,
            "PERCENT_PRICE_GUARD_BPS": self.PERCENT_PRICE_GUARD_BPS,
            "SLIPPAGE_GUARD_BPS": self.SLIPPAGE_GUARD_BPS,
            "POST_FILL_SANITY_BPS": self.POST_FILL_SANITY_BPS,
            "MIN_QUALITY_SCORE": self.MIN_QUALITY_SCORE,
            "MAX_ATR_PCT": self.MAX_ATR_PCT,
            "MIN_VOLUME": self.MIN_VOLUME,
            "LADDER_TP_ENABLE": self.LADDER_TP_ENABLE,
            "LADDER_TP_KIND": self.LADDER_TP_KIND,
            "LADDER_TP_DEFAULT_PCTS": self.LADDER_TP_DEFAULT_PCTS,
            "LADDER_TP_DEFAULT_SPLITS": self.LADDER_TP_DEFAULT_SPLITS,
            "LADDER_SL_ENABLE": self.LADDER_SL_ENABLE,
            "LADDER_SL_DEFAULT_PCTS": self.LADDER_SL_DEFAULT_PCTS,
            "SL_DYNAMIC_ENABLE": self.SL_DYNAMIC_ENABLE,
            "SL_ATR_MULT": self.SL_ATR_MULT,
            "SL_TRAIL_ENABLE": self.SL_TRAIL_ENABLE,
            "LEVERAGE_SYMBOL_CAPS": self.LEVERAGE_SYMBOL_CAPS,
            "TELEGRAM_BOT_TOKEN_SET": bool(self.TELEGRAM_BOT_TOKEN),
            "TELEGRAM_CHAT_ID_DEFAULT": self.TELEGRAM_CHAT_ID_DEFAULT,
            "TELEGRAM_PARSE_MODE": self.TELEGRAM_PARSE_MODE,
            "CONFIRM_TTL_SEC": self.CONFIRM_TTL_SEC,
            "REDIS_URL_SET": bool(self.REDIS_URL),
            "DEFAULT_QTY_STEP": self.DEFAULT_QTY_STEP,
            "DEFAULT_PRICE_TICK": self.DEFAULT_PRICE_TICK,
            "MIN_NOTIONAL_USDT": self.MIN_NOTIONAL_USDT,
            "IDEMPOTENCY_TTL_SEC": self.IDEMPOTENCY_TTL_SEC,
            "ORDER_ID_PREFIX": self.ORDER_ID_PREFIX,
            "CANCEL_ONLY_PREFIXED_ORDERS": self.CANCEL_ONLY_PREFIXED_ORDERS,
        }

_SENTINELS = {"PUT_REAL_API_TOKEN", "CHANGE_ME", "REPLACE_ME", "YOUR_TOKEN_HERE", "TOKEN"}

def _load_tokens_from_env() -> Set[str]:
    candidates: List[str] = []
    for k in ("AUTH_TOKENS", "ALGOGPT_API_TOKENS", "API_TOKENS", "ALGOGPT_TOKENS"):
        v = os.getenv(k, "")
        if v.strip():
            candidates.extend(_split_csv(v))
    for k in ("PRIMARY_API_TOKEN", "API_BEARER_TOKEN", "ALGOGPT_API_TOKEN",
              "ALGOGPT_TOKEN", "API_TOKEN", "TOKEN"):
        v = os.getenv(k, "")
        if v.strip():
            candidates.append(v.strip())
    for file_env in ("API_TOKENS_FILE", "AUTH_TOKENS_FILE"):
        path = os.getenv(file_env, "").strip()
        if path:
            try:
                with open(path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            candidates.append(line)
            except Exception as e:
                log.warning("Could not read %s %s: %s", file_env, path, e)
    cleaned: Set[str] = set()
    for t in candidates:
        tt = t.strip()
        if not tt or tt in _SENTINELS:
            continue
        cleaned.add(tt)
    return cleaned

def _load_tp_defaults(env_name: str, fallback: List[float]) -> List[float]:
    raw = os.getenv(env_name, "")
    if not raw.strip():
        return fallback
    out: List[float] = []
    for x in _split_csv(raw):
        try:
            out.append(float(x))
        except Exception:
            pass
    return out or fallback

_settings: Optional[Settings] = None

def load_settings() -> Settings:
    global _settings
    s = Settings()
    s.API_TOKENS = _load_tokens_from_env()
    s.LADDER_TP_DEFAULT_PCTS = _load_tp_defaults("LADDER_TP_DEFAULT_PCTS", s.LADDER_TP_DEFAULT_PCTS)
    s.LADDER_TP_DEFAULT_SPLITS = _load_tp_defaults("LADDER_TP_DEFAULT_SPLITS", s.LADDER_TP_DEFAULT_SPLITS)
    log.info("[Config] %s env=%s | tokens=%d | allow_all=%s",
             s.APP_NAME, s.ENV, len(s.API_TOKENS), s.AUTH_ALLOW_ALL)
    _settings = s
    return s

def get_settings() -> Settings:
    return _settings or load_settings()

def reload_settings() -> Settings:
    return load_settings()

def is_public_path(path: str) -> bool:
    s = get_settings()
    if path in s.AUTH_PUBLIC_PATHS:
        return True
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    return False

def valid_token(token: Optional[str]) -> bool:
    s = get_settings()
    if s.AUTH_ALLOW_ALL:
        return True
    if not token or not token.strip():
        return False
    return token.strip() in s.API_TOKENS

def strip_bearer_prefix(value: str) -> str:
    v = (value or "").strip()
    if not v:
        return v
    s = get_settings()
    for p in s.AUTH_BEARER_PREFIXES:
        pref = f"{p} "
        if v.lower().startswith(pref.lower()):
            return v[len(pref):].strip()
    return v

def debug_dump() -> Dict[str, object]:
    return get_settings().as_dict()

def dump_config_sanitized() -> Dict[str, object]:
    """Minimal API used by routes.admin: returns env/config with secrets masked."""
    data = debug_dump()
    # also expose some direct envs (masked)
    extras = {
        "PUBLIC_HOST": os.getenv("PUBLIC_HOST", ""),
        "PRIMARY_PUBLIC_HOST": os.getenv("PRIMARY_PUBLIC_HOST", ""),
        "ENV": os.getenv("ENV", ""),
    }
    data.update(extras)

    def _mask(val: str) -> str:
        if not val:
            return val
        if len(val) <= 6:
            return "***"
        return val[:3] + "…" + val[-3:]

    secret_keys = [
        "TOKEN", "TOKENS", "KEY", "SECRET", "PASSWORD", "WEBHOOK", "AUTH", "API_KEY",
        "TELEGRAM_BOT_TOKEN", "OPENAI_API_KEY", "BINANCE_API_KEY", "BINANCE_API_SECRET",
        "REDIS_URL",
    ]
    redacted = {}
    for k, v in data.items():
        if any(s in k.upper() for s in secret_keys):
            redacted[k] = bool(v) if isinstance(v, bool) else _mask(str(v))
        else:
            redacted[k] = v
    return redacted

load_settings()


































