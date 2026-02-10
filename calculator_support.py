"""calculator_support.py

Shared helpers for the Acquisitions feasibility calculator.

This module contains *pure-ish* helpers (no Streamlit UI), so logic/UI can be
changed independently with lower regression risk.
"""

from __future__ import annotations

import math
from collections import deque
from typing import Any

import pandas as pd


# Tunables (kept here so logic + UI share one source of truth)
MIN_SUPPORT_N = 15
MAX_HOPS = 2


def dollars(x: Any) -> str:
    """Format number as whole-dollar currency, or em dash if missing."""
    if x is None or (isinstance(x, float) and math.isnan(x)):
        return "—"
    try:
        return f"${float(x):,.0f}"
    except Exception:
        return "—"


def confidence_label(total_n: int) -> str:
    if total_n >= 30:
        return "✅ High"
    if total_n >= 15:
        return "⚠️ Medium"
    return "🚧 Low"


def auto_params_for_n(total_n: int) -> tuple[int, int, int]:
    """(step, tail_min_n, min_bin_n) tuned by sample size."""
    if total_n >= 40:
        return (5000, 12, 6)
    if total_n >= 20:
        return (5000, 8, 5)
    if total_n >= 10:
        return (10000, 6, 4)
    return (20000, 5, 3)


def build_bins(df: pd.DataFrame, *, bin_size: int, min_bin_n: int) -> pd.DataFrame:
    """
    Returns dataframe with:
      bin_low, bin_high, n, cut_rate
    """
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "cut_rate"])

    d["bin_low"] = (d["effective_price"].astype(float) // float(bin_size)).astype(int) * int(bin_size)
    d["bin_high"] = d["bin_low"] + int(bin_size)

    rows: list[dict[str, Any]] = []
    for (lo, hi), g in d.groupby(["bin_low", "bin_high"]):
        n = int(len(g))
        if n < int(min_bin_n):
            continue
        cut_rate = float(g["is_cut"].mean()) if n else float("nan")
        rows.append({"bin_low": int(lo), "bin_high": int(hi), "n": n, "cut_rate": cut_rate})

    out = pd.DataFrame(rows)
    if out.empty:
        return pd.DataFrame(columns=["bin_low", "bin_high", "n", "cut_rate"])
    return out.sort_values(["bin_low"])


def tail_cut_rate_at_price(df: pd.DataFrame, price: float) -> tuple[float | None, int]:
    """Diagnostic tail cut-rate at `price` (not inherently monotonic)."""
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return (None, 0)

    tail = d[d["effective_price"] >= float(price)]
    n = int(len(tail))
    if n == 0:
        return (None, 0)
    return (float(tail["is_cut"].mean()), n)


def find_tail_threshold(
    df: pd.DataFrame,
    target_cut_rate: float,
    *,
    tail_min_n: int,
    step: int,
) -> float | None:
    """
    Finds the *crossing* threshold: the lowest P (grid) where
      prev_cut_rate < target AND current_cut_rate >= target

    If the dataset is already >= target at the earliest eligible tail window,
    returns None (no meaningful "cliff" to cross into).
    """
    d = df.copy()
    d["effective_price"] = pd.to_numeric(d["effective_price"], errors="coerce")
    d = d.dropna(subset=["effective_price", "is_cut"])
    if d.empty:
        return None

    prices = d["effective_price"].astype(float)
    pmin, pmax = float(prices.min()), float(prices.max())

    start = int((pmin // step) * step)
    end = int(((pmax + step - 1) // step) * step)

    prev_rate: float | None = None
    for P in range(start, end + step, step):
        tail = d[d["effective_price"] >= float(P)]
        n = len(tail)
        if n < int(tail_min_n):
            continue

        cut_rate = float(tail["is_cut"].mean())
        if prev_rate is not None and prev_rate < float(target_cut_rate) and cut_rate >= float(target_cut_rate):
            return float(P)
        prev_rate = cut_rate

    return None


def neighbors_within_hops(county_key: str, adjacency: dict[str, list[str]], max_hops: int) -> list[str]:
    """BFS out to max_hops; returns unique counties excluding the start."""
    start = county_key.strip().upper()
    if not start or not adjacency:
        return []

    seen = {start}
    q: deque[tuple[str, int]] = deque([(start, 0)])
    out: list[str] = []

    while q:
        node, depth = q.popleft()
        if depth >= max_hops:
            continue
        for nxt in adjacency.get(node, []):
            nxt_u = str(nxt).strip().upper()
            if not nxt_u or nxt_u in seen:
                continue
            seen.add(nxt_u)
            out.append(nxt_u)
            q.append((nxt_u, depth + 1))

    return out


def build_support_df(
    df_all: pd.DataFrame,
    county_key: str,
    *,
    adjacency: dict[str, list[str]] | None,
    min_support_n: int,
    max_hops: int,
) -> tuple[pd.DataFrame, str, list[str], bool]:
    """
    Returns:
      (df_support, scope_label, counties_used, used_fallback)
    """
    ck = county_key.strip().upper()
    d = df_all.copy()

    county_only = d[d["County_clean_up"].astype(str).str.strip().str.upper() == ck].copy()
    if len(county_only) >= int(min_support_n):
        return (county_only, "County only", [ck], False)

    adjacency = adjacency or {}

    for hops in range(1, int(max_hops) + 1):
        neigh = neighbors_within_hops(ck, adjacency, max_hops=hops)
        pool = [ck] + neigh
        support = d[d["County_clean_up"].astype(str).str.strip().str.upper().isin(pool)].copy()
        if len(support) >= int(min_support_n):
            label = "Nearby counties"
            return (support, label, pool, True)

    return (d, "Statewide", ["ALL TN"], True)
