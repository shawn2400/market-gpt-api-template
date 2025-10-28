# -*- coding: utf-8 -*-
from __future__ import annotations

# Placeholder scanner_universe (real code will be added in a follow-up commit through the PR discussion).
# It returns an empty list to avoid breaking imports; the PR will replace with dynamic USDT-PERP universe logic.

from typing import List, Dict, Any


def get_futures_universe(force_refresh: bool = False) -> List[str]:
    return []


async def scan_all_futures(analyze_symbol_fn, concurrency: int = 8) -> List[Dict[str, Any]]:
    return []
