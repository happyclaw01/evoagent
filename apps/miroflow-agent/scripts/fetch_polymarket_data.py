#!/usr/bin/env python3
# Copyright (c) 2025 MiroMind
# This source code is licensed under the MIT License.

"""
Fetch Polymarket market data from Gamma API and CLOB API,
and convert to MiroThinker benchmark format (JSONL).

Usage:
    python fetch_polymarket_data.py [--output-dir <dir>] [--include-active] [--min-volume <amount>]
"""

import argparse
import ast
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Polymarket API endpoints (update these based on actual API documentation)
GAMMA_API_BASE = os.getenv("POLYMARKET_GAMMA_API_BASE", "https://gamma-api.polymarket.com")
CLOB_API_BASE = os.getenv("POLYMARKET_CLOB_API_BASE", "https://clob.polymarket.com")
GAMMA_API_KEY = os.getenv("POLYMARKET_GAMMA_API_KEY", "")
CLOB_API_KEY = os.getenv("POLYMARKET_CLOB_API_KEY", "")
# Control whether to fetch CLOB data (set to "false" to skip CLOB calls)
USE_CLOB_API = os.getenv("POLYMARKET_USE_CLOB_API", "true").lower() == "true"


def fetch_gamma_markets(
    include_active: bool = True, 
    include_resolved: bool = True, 
    limit: Optional[int] = None,
    only_not_closed: bool = True
) -> List[Dict[str, Any]]:
    """
    Fetch market list from Polymarket Gamma API.

    Args:
        include_active: Include active markets
        include_resolved: Include resolved markets
        limit: Maximum number of markets to fetch per request
        only_not_closed: Only fetch markets that are not closed (default: True)

    Returns:
        List of market data dictionaries
    """
    markets = []
    params = {}

    if include_active and include_resolved:
        # Fetch both types
        params["state"] = "all"
    elif include_active:
        params["state"] = "active"
    elif include_resolved:
        params["state"] = "resolved"
    else:
        return markets

    # Filter by closed status at API level if supported
    if only_not_closed:
        params["closed"] = "false"  # Only fetch markets that are not closed
        # Alternative parameter names that might be used:
        # params["isClosed"] = "false"
        # params["closed"] = False

    # Use pagination to fetch more markets if needed
    if limit:
        params["limit"] = min(limit, 20)  # API might have max limit per request
    else:
        params["limit"] = 20  # Default to fetch more at once

    headers = {}
    if GAMMA_API_KEY:
        headers["Authorization"] = f"Bearer {GAMMA_API_KEY}"

    try:
        # Adjust endpoint based on actual Gamma API structure
        response = requests.get(
            f"{GAMMA_API_BASE}/markets", params=params, headers=headers, timeout=30
        )
        response.raise_for_status()
        data = response.json()

        # Handle different possible response formats
        if isinstance(data, list):
            markets = data
        elif isinstance(data, dict):
            markets = data.get("markets", data.get("data", []))
        else:
            print(f"Warning: Unexpected response format from Gamma API: {type(data)}")
            return markets

    except requests.exceptions.RequestException as e:
        print(f"Error fetching from Gamma API: {e}")
        if hasattr(e, "response") and e.response is not None:
            print(f"Response: {e.response.text}")
        return markets

    return markets


def fetch_gamma_market_details(market_id: str) -> Optional[Dict[str, Any]]:
    """
    Fetch detailed market data from Gamma API (market metadata, outcomes, etc.).

    Args:
        market_id: Polymarket market ID

    Returns:
        Market details dictionary or None if error
    """
    headers = {}
    if GAMMA_API_KEY:
        headers["Authorization"] = f"Bearer {GAMMA_API_KEY}"

    try:
        # Market details should come from Gamma API, not CLOB
        response = requests.get(
            f"{GAMMA_API_BASE}/markets/{market_id}",
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        return response.json()

    except requests.exceptions.HTTPError as e:
        # Silently skip 404s (market may not exist in Gamma API)
        # Note: Some old/archived markets may return 404 from detail endpoint
        if e.response.status_code == 404:
            if os.getenv("POLYMARKET_DEBUG", "false").lower() == "true":
                print(f"Debug: Market {market_id} detail endpoint returned 404 (using list data only)")
            return None
        # Only warn for non-404 errors
        print(f"Warning: HTTP {e.response.status_code} fetching Gamma details for market {market_id}")
        return None
    except requests.exceptions.RequestException as e:
        # Silently skip other request errors
        return None


def fetch_clob_price_data(clob_token_ids: List[str]) -> Optional[Dict[str, Any]]:
    """
    Fetch price/trading data from CLOB API (orderbook, prices, trades, price history, etc.).
    
    CLOB API is for trading-related data, not market metadata.
    Endpoints used:
    - GET /price?token_id=...&side=BUY|SELL
    - GET /midpoint?token_id=...
    - GET /book?token_id=... (orderbook)
    - GET /trades?token_id=... (trade history)
    - GET /prices-history?market=TOKEN_ID&interval=... (price history)

    Args:
        clob_token_ids: List of CLOB token IDs (from Gamma API's clobTokenIds field)

    Returns:
        Dictionary containing:
        - probabilities: List of probabilities for each outcome (from midpoint prices)
        - midpoints: List of midpoint prices for each outcome
        - prices: List of buy/sell prices for each outcome
        - orderbook: Orderbook data (for first token)
        - trades: Recent trades (for first token)
        - price_history: Price history (for first token)
    """
    if not USE_CLOB_API or not clob_token_ids:
        return None

    headers = {}
    if CLOB_API_KEY:
        headers["Authorization"] = f"Bearer {CLOB_API_KEY}"

    verify_ssl = os.getenv("POLYMARKET_VERIFY_SSL", "true").lower() == "true"

    result = {
        "probabilities": [],
        "midpoints": [],
        "prices": [],
        "orderbook": None,
        "trades": None,
        "price_history": None,
    }

    # Fetch data for all outcomes (not just the first one)
    for token_id in clob_token_ids:
        if not token_id:
            continue

        try:
            # 1. Get midpoint price (used to calculate probability)
            midpoint = None
            try:
                midpoint_response = requests.get(
                    f"{CLOB_API_BASE}/midpoint",
                    params={"token_id": token_id},
                    headers=headers,
                    timeout=30,
                    verify=verify_ssl,
                )
                midpoint_response.raise_for_status()
                midpoint_data = midpoint_response.json()
                if isinstance(midpoint_data, dict):
                    midpoint = midpoint_data.get("midpoint") or midpoint_data.get("price")
                else:
                    midpoint = midpoint_data
                if midpoint is not None:
                    midpoint = float(midpoint)
                    result["midpoints"].append(midpoint)
                    # Midpoint is the probability for this outcome
                    result["probabilities"].append(midpoint)
            except Exception:
                result["midpoints"].append(None)
                result["probabilities"].append(None)

            # 2. Get buy/sell prices
            outcome_prices = {}
            for side in ["BUY", "SELL"]:
                try:
                    price_response = requests.get(
                        f"{CLOB_API_BASE}/price",
                        params={"token_id": token_id, "side": side},
                        headers=headers,
                        timeout=30,
                        verify=verify_ssl,
                    )
                    price_response.raise_for_status()
                    price_data = price_response.json()
                    if isinstance(price_data, dict):
                        outcome_prices[side.lower()] = float(price_data.get("price", 0))
                    else:
                        outcome_prices[side.lower()] = float(price_data)
                except Exception:
                    outcome_prices[side.lower()] = None
            result["prices"].append(outcome_prices)

        except Exception:
            # Skip this token if there's an error
            result["midpoints"].append(None)
            result["probabilities"].append(None)
            result["prices"].append({"buy": None, "sell": None})
            continue

    # Fetch orderbook, trades, and price history for the first token (most liquid)
    first_token_id = clob_token_ids[0] if clob_token_ids else None
    if first_token_id:
        # 3. Get orderbook (盘口)
        try:
            orderbook_response = requests.get(
                f"{CLOB_API_BASE}/book",
                params={"token_id": first_token_id},
                headers=headers,
                timeout=30,
                verify=verify_ssl,
            )
            orderbook_response.raise_for_status()
            result["orderbook"] = orderbook_response.json()
        except Exception:
            pass  # Silently skip if orderbook is not available

        # 4. Get recent trades (成交历史)
        try:
            trades_response = requests.get(
                f"{CLOB_API_BASE}/trades",
                params={"token_id": first_token_id},
                headers=headers,
                timeout=30,
                verify=verify_ssl,
            )
            trades_response.raise_for_status()
            result["trades"] = trades_response.json()
        except Exception:
            pass  # Silently skip if trades are not available

        # 5. Get price history (价格历史)
        try:
            # Try different interval options (1h, 4h, 1d, etc.)
            interval = "1h"  # Default interval
            price_history_response = requests.get(
                f"{CLOB_API_BASE}/prices-history",
                params={"market": first_token_id, "interval": interval},
                headers=headers,
                timeout=30,
                verify=verify_ssl,
            )
            price_history_response.raise_for_status()
            price_history_data = price_history_response.json()
            # Store price history with metadata
            result["price_history"] = {
                "token_id": first_token_id,
                "interval": interval,
                "history": price_history_data,
            }
        except Exception:
            pass  # Silently skip if price history is not available

    # Normalize probabilities (ensure they sum to 1.0 for binary markets)
    if result["probabilities"] and all(p is not None for p in result["probabilities"]):
        prob_sum = sum(result["probabilities"])
        if prob_sum > 0:
            # Normalize to sum to 1.0
            result["probabilities"] = [p / prob_sum for p in result["probabilities"]]

    return result if any(result["probabilities"]) or result["orderbook"] or result["trades"] or result["price_history"] else None


def parse_json_string_field(value: Any) -> Any:
    """
    Parse a field that might be a JSON string or already a parsed object.

    Args:
        value: Field value (could be string, list, or None)

    Returns:
        Parsed value (list, dict, or original value)
    """
    if value is None:
        return None
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, ValueError):
            # If it's not valid JSON, return as-is
            return value
    return value


def format_task_question(
    market: Dict[str, Any],
    gamma_details: Optional[Dict[str, Any]],
    clob_price_data: Optional[Dict[str, Any]],
) -> str:
    """
    Format market data into a task question string.

    Args:
        market: Market data from Gamma API (list endpoint)
        gamma_details: Detailed market data from Gamma API (single market endpoint)
        clob_price_data: Price/trading data from CLOB API

    Returns:
        Formatted question string
    """
    # Use detailed Gamma data if available, otherwise fall back to list data
    market_data = gamma_details if gamma_details else market

    question = market_data.get("question", market_data.get("title", "Unknown question"))

    # Extract options - may be JSON string
    outcomes = market_data.get("outcomes", market_data.get("options", []))
    if not outcomes:
        outcomes = market.get("outcomes", market.get("options", []))
    # Parse if it's a JSON string
    outcomes = parse_json_string_field(outcomes)
    if not isinstance(outcomes, list):
        outcomes = [outcomes] if outcomes else []

    # Extract probabilities from outcomePrices (Gamma API uses outcomePrices, not probabilities)
    # outcomePrices is the implied probabilities, 1:1 mapping with outcomes
    probabilities = []
    outcome_prices = market_data.get("outcomePrices", market_data.get("outcome_prices"))
    if not outcome_prices:
        outcome_prices = market.get("outcomePrices", market.get("outcome_prices"))
    
    # Parse if it's a JSON string
    outcome_prices = parse_json_string_field(outcome_prices)
    
    if outcome_prices and isinstance(outcome_prices, list):
        # Convert to float and normalize to 0-1 range
        for price in outcome_prices:
            try:
                prob = float(price)
                # If > 1, assume it's a percentage (e.g., 65 for 65%)
                if prob > 1:
                    prob = prob / 100.0
                probabilities.append(prob)
            except (ValueError, TypeError):
                pass
    
    # CLOB price data as fallback (if available)
    if not probabilities and clob_price_data:
        clob_prices = clob_price_data.get("prices", clob_price_data.get("probabilities", []))
        if clob_prices:
            probabilities = [float(p) if isinstance(p, (int, float)) else float(p) for p in clob_prices]

    # Extract volume (prefer from Gamma API)
    volume = None
    if gamma_details:
        volume = gamma_details.get("volume", gamma_details.get("total_volume"))
    if not volume:
        volume = market_data.get("volume", market_data.get("total_volume"))
    if not volume:
        volume = market.get("volume", market.get("total_volume"))

    # Format question with market context
    question_parts = [question]

    if outcomes and probabilities:
        market_info = "Current market: "
        market_parts = []
        for i, outcome in enumerate(outcomes):
            prob = probabilities[i] if i < len(probabilities) else None
            if prob is not None:
                prob_pct = f"{prob * 100:.1f}%" if prob < 1 else f"{prob:.1f}%"
                market_parts.append(f"{outcome} {prob_pct}")
            else:
                market_parts.append(outcome)
        market_info += ", ".join(market_parts)
        question_parts.append(market_info)

    if volume:
        if isinstance(volume, (int, float)):
            if volume >= 1000000:
                volume_str = f"${volume / 1000000:.2f}M"
            elif volume >= 1000:
                volume_str = f"${volume / 1000:.2f}K"
            else:
                volume_str = f"${volume:.2f}"
        else:
            volume_str = str(volume)
        question_parts.append(f"Volume: {volume_str}")

    return ". ".join(question_parts) + "."


def extract_market_state(market: Dict[str, Any], gamma_details: Optional[Dict[str, Any]]) -> str:
    """
    Extract market state from boolean fields (active, closed, archived).

    Args:
        market: Market data from Gamma API (list endpoint)
        gamma_details: Detailed market data from Gamma API (single market endpoint)

    Returns:
        State string: "active", "closed", "archived", or ""
    """
    # Use detailed Gamma data if available
    market_data = gamma_details if gamma_details else market

    # Gamma API uses boolean fields, not a unified state field
    closed = market_data.get("closed", False)
    active = market_data.get("active", False)
    archived = market_data.get("archived", False)

    if not closed and not active and not archived:
        # Fallback to list data
        closed = market.get("closed", False)
        active = market.get("active", False)
        archived = market.get("archived", False)

    if archived:
        return "archived"
    if closed:
        return "closed"
    if active:
        return "active"
    return ""


def extract_ground_truth(
    market: Dict[str, Any],
    gamma_details: Optional[Dict[str, Any]],
) -> str:
    """
    Extract ground truth from resolved market.

    Note: Gamma API /markets list doesn't guarantee final winning outcome.
    Resolution data is typically on-chain via UMA optimistic oracle.

    Args:
        market: Market data from Gamma API (list endpoint)
        gamma_details: Detailed market data from Gamma API (single market endpoint)

    Returns:
        Ground truth answer or empty string for active/unresolved markets
    """
    # Use detailed Gamma data if available
    market_data = gamma_details if gamma_details else market

    # Check if market is resolved/closed
    state = extract_market_state(market, gamma_details)
    if state not in ["closed", "archived"]:
        return ""

    # Try to get resolution from various possible fields
    # Note: Gamma API may not provide final winning outcome in list endpoint
    resolution = (
        market_data.get("resolution")
        or market_data.get("resolvedOutcome")
        or market_data.get("winningOutcome")
        or market_data.get("resolved_outcome")
        or market_data.get("winning_outcome")
    )
    if not resolution:
        resolution = (
            market.get("resolution")
            or market.get("resolvedOutcome")
            or market.get("winningOutcome")
            or market.get("resolved_outcome")
            or market.get("winning_outcome")
        )

    return resolution if resolution else ""


def convert_to_benchmark_format(
    markets: List[Dict[str, Any]], 
    min_volume: Optional[float] = None,
    target_count: Optional[int] = None,
    verbose: bool = True
) -> List[Dict[str, Any]]:
    """
    Convert Polymarket markets to benchmark format.

    Args:
        markets: List of market data from Gamma API
        min_volume: Minimum volume filter (optional)
        target_count: Target number of markets to find (None = all)
        verbose: Print progress for each market

    Returns:
        Tuple of (List of benchmark task dictionaries, List of price history dictionaries, List of orderbook dictionaries)
    """
    tasks = []
    price_histories = []  # Store price history separately
    orderbooks = []  # Store orderbook separately
    processed = 0

    for market in markets:
        processed += 1
        market_id = market.get("id", market.get("market_id", ""))
        if not market_id:
            if verbose:
                print(f"[{processed}] Warning: Skipping market without ID")
            continue

        if verbose:
            print(f"[{processed}] Processing market {market_id}...", end="")

        # Fetch detailed market data from Gamma API (market metadata)
        gamma_details = fetch_gamma_market_details(market_id)

        # Extract CLOB token IDs (may be JSON string)
        clob_token_ids_raw = market.get("clobTokenIds", [])
        if gamma_details:
            clob_token_ids_raw = gamma_details.get("clobTokenIds", clob_token_ids_raw)
        clob_token_ids = parse_json_string_field(clob_token_ids_raw)
        if not isinstance(clob_token_ids, list):
            clob_token_ids = [clob_token_ids] if clob_token_ids else []

        # Fetch price/trading data from CLOB API (optional, for current prices)
        clob_price_data = fetch_clob_price_data(clob_token_ids)

        # Use detailed Gamma data if available, otherwise fall back to list data
        market_data = gamma_details if gamma_details else market

        # Extract volume (for saving, not filtering)
        volume = None
        if gamma_details:
            volume = gamma_details.get("volume", gamma_details.get("totalVolume"))
        if not volume:
            volume = market_data.get("volume", market_data.get("totalVolume"))
        if not volume:
            volume = market.get("volume", market.get("totalVolume"))

        # Format task question
        task_question = format_task_question(market, gamma_details, clob_price_data)

        # Extract ground truth
        ground_truth = extract_ground_truth(market, gamma_details)

        # Extract metadata - outcomes may be JSON string
        outcomes = market_data.get("outcomes", market_data.get("options", []))
        if not outcomes:
            outcomes = market.get("outcomes", market.get("options", []))
        outcomes = parse_json_string_field(outcomes)
        if not isinstance(outcomes, list):
            outcomes = [outcomes] if outcomes else []

        # Extract probabilities - PRIORITY: CLOB API > Gamma API
        probabilities = []
        
        # 1. First try CLOB API (primary source for probabilities)
        if clob_price_data and clob_price_data.get("probabilities"):
            clob_probs = clob_price_data["probabilities"]
            # Filter out None values and ensure all are valid
            probabilities = [p for p in clob_probs if p is not None]
            if probabilities and len(probabilities) == len(outcomes):
                # Probabilities from CLOB are already normalized
                pass
            elif probabilities:
                # If we have some but not all, pad with None or normalize
                while len(probabilities) < len(outcomes):
                    probabilities.append(None)
        
        # 2. Fallback to Gamma API outcomePrices if CLOB doesn't have probabilities
        if not probabilities or all(p is None for p in probabilities):
            outcome_prices = None
            if gamma_details:
                outcome_prices = gamma_details.get("outcomePrices")
            if not outcome_prices:
                outcome_prices = market_data.get("outcomePrices")
            if not outcome_prices:
                outcome_prices = market.get("outcomePrices")
            
            # Debug: Check if outcomePrices exists (optional, can be enabled via env var)
            if os.getenv("POLYMARKET_DEBUG", "false").lower() == "true":
                print(f"Market {market_id}: Using Gamma API outcomePrices (CLOB not available)")
                print(f"  - outcomePrices from gamma_details: {gamma_details.get('outcomePrices') if gamma_details else 'N/A'}")
                print(f"  - outcomePrices from market_data: {market_data.get('outcomePrices')}")
            
            # Parse if it's a JSON string
            outcome_prices = parse_json_string_field(outcome_prices)
            
            if outcome_prices and isinstance(outcome_prices, list):
                probabilities = []
                for price in outcome_prices:
                    try:
                        prob = float(price)
                        # If > 1, assume it's a percentage (e.g., 65 for 65%)
                        if prob > 1:
                            prob = prob / 100.0
                        probabilities.append(prob)
                    except (ValueError, TypeError):
                        probabilities.append(None)

        # Extract timestamps (Gamma API uses camelCase: createdAt, updatedAt)
        created_at = None
        if gamma_details:
            created_at = gamma_details.get("createdAt", gamma_details.get("created_at", ""))
        if not created_at:
            created_at = market_data.get("createdAt", market_data.get("created_at", ""))
        if not created_at:
            created_at = market.get("createdAt", market.get("created_at", ""))
        # Convert to string if it's a timestamp/number
        if created_at and not isinstance(created_at, str):
            created_at = str(created_at)

        # resolved_at: Gamma may use closedTime, endDate, or umaEndDate
        resolved_at = None
        if gamma_details:
            resolved_at = (
                gamma_details.get("closedTime")
                or gamma_details.get("endDate")
                or gamma_details.get("umaEndDate")
                or gamma_details.get("resolvedAt")
                or gamma_details.get("resolved_at")
            )
        if not resolved_at:
            resolved_at = (
                market_data.get("closedTime")
                or market_data.get("endDate")
                or market_data.get("umaEndDate")
                or market_data.get("resolvedAt")
                or market_data.get("resolved_at")
            )
        if not resolved_at:
            resolved_at = (
                market.get("closedTime")
                or market.get("endDate")
                or market.get("umaEndDate")
                or market.get("resolvedAt")
                or market.get("resolved_at")
            )
        # Convert to string if it's a timestamp/number
        if resolved_at and not isinstance(resolved_at, str):
            resolved_at = str(resolved_at)

        # Extract market state (from boolean fields)
        state = extract_market_state(market, gamma_details)

        # Extract active boolean value (for saving, not filtering)
        active = None
        active = market_data.get("active")
        if active is None:
            active = market_data.get("isActive")
        if active is None:
            active = market.get("active")
        if active is None:
            active = market.get("isActive")
        if active is None:
            active = False

        # Extract slug
        slug = market_data.get("slug", market_data.get("id", ""))
        if not slug:
            slug = market.get("slug", market.get("id", ""))

        # Extract tags (may be JSON string or list)
        tags = market_data.get("tags", [])
        if not tags:
            tags = market.get("tags", [])
        tags = parse_json_string_field(tags)
        if not isinstance(tags, list):
            tags = [tags] if tags else []

        # Extract market midpoint from CLOB data (use first outcome's midpoint)
        market_mid = None
        if clob_price_data and clob_price_data.get("midpoints"):
            midpoints = clob_price_data["midpoints"]
            if midpoints and midpoints[0] is not None:
                try:
                    market_mid = float(midpoints[0])
                except (ValueError, TypeError):
                    pass

        # Get snapshot time (current timestamp)
        snapshot_time = datetime.now().isoformat()

        task = {
            "task_id": f"polymarket_{market_id}",
            "task_question": task_question,
            "ground_truth": ground_truth,
            "metadata": {
                "market_id": market_id,
                "slug": slug,
                "options": outcomes,  # Now guaranteed to be a list
                "probabilities": probabilities,
                "volume": str(volume) if volume else "",
                "created_at": created_at or "",
                "resolved_at": resolved_at or "",
                "resolution": ground_truth if ground_truth else None,
                "state": state,
                "active": active,
                "tags": tags,
                "clobTokenIds": clob_token_ids,
                "snapshot_time": snapshot_time,
                "market_mid": market_mid,
                # CLOB API data (orderbook and price_history stored separately)
                "clob_trades": clob_price_data.get("trades") if clob_price_data else None,
            },
        }
        
        tasks.append(task)
        
        # Store orderbook separately (will be written to a different file)
        if clob_price_data and clob_price_data.get("orderbook"):
            orderbook_data = clob_price_data.get("orderbook")
            if isinstance(orderbook_data, dict):
                # Extract token_id from orderbook (asset_id or from clob_token_ids)
                orderbook_token_id = orderbook_data.get("asset_id")
                if not orderbook_token_id and clob_token_ids:
                    orderbook_token_id = clob_token_ids[0]  # Use first token ID
                
                # Extract and limit bids/asks to top N (default 20)
                top_n = 20
                bids = orderbook_data.get("bids", [])
                asks = orderbook_data.get("asks", [])
                
                # Bids are sorted descending (highest first), take top N
                bids_top = bids[:top_n] if isinstance(bids, list) else []
                # Asks are sorted ascending (lowest first), take top N
                asks_top = asks[:top_n] if isinstance(asks, list) else []
                
                orderbook_record = {
                    "market_id": market_id,
                    "slug": slug,
                    "token_id": orderbook_token_id,
                    "fetch_time": snapshot_time,
                    "bids": bids_top,
                    "asks": asks_top,
                }
                orderbooks.append(orderbook_record)
        
        # Store price history separately (will be written to a different file)
        if clob_price_data and clob_price_data.get("price_history"):
            ph_data = clob_price_data.get("price_history")
            # ph_data is a dict with: token_id, interval, history
            if isinstance(ph_data, dict) and "history" in ph_data:
                price_history_data = {
                    "market_id": market_id,
                    "slug": slug,
                    "token_id": ph_data.get("token_id"),
                    "fetch_time": snapshot_time,
                    "interval": ph_data.get("interval"),
                    "history": ph_data.get("history"),  # Original CLOB response
                }
                price_histories.append(price_history_data)
        
        if verbose:
            print(f" ✓ Added! Total: {len(tasks)}/{target_count if target_count else 'all'}")
        
        # Stop if we've reached the target count
        if target_count and len(tasks) >= target_count:
            if verbose:
                print(f"\n✓ Reached target count of {target_count} markets!")
                print(f"  - Processed: {processed}")
                print(f"  - Added: {len(tasks)}")
            break

    if verbose and (not target_count or len(tasks) < target_count):
        print(f"\nFinished processing {processed} markets:")
        print(f"  - Added: {len(tasks)}")

    return tasks, price_histories, orderbooks


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Polymarket data and convert to benchmark format"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="../../data/polymarket-daily",
        help="Output directory for benchmark data",
    )
    parser.add_argument(
        "--include-active",
        action="store_true",
        default=True,
        help="Include active markets (default: True)",
    )
    parser.add_argument(
        "--include-resolved",
        action="store_true",
        default=False,
        help="Include resolved/closed markets (default: False - only active markets)",
    )
    parser.add_argument(
        "--min-volume",
        type=float,
        help="Minimum volume filter (e.g., 1000 for $1000)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Target number of active markets to find (default: 20)",
    )
    parser.add_argument(
        "--incremental",
        action="store_true",
        help="Only fetch new markets (check existing metadata.jsonl)",
    )

    args = parser.parse_args()

    # Create output directory
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    metadata_file = output_dir / "metadata.jsonl"

    # Load existing task IDs if incremental update
    existing_task_ids = set()
    if args.incremental and metadata_file.exists():
        print(f"Loading existing tasks from {metadata_file}...")
        with open(metadata_file, "r", encoding="utf-8") as f:
            for line in f:
                try:
                    data = json.loads(line.strip())
                    existing_task_ids.add(data["task_id"])
                except Exception:
                    pass
        print(f"Found {len(existing_task_ids)} existing tasks")

    # Fetch markets from Gamma API
    print("Fetching markets from Polymarket Gamma API...")
    print(f"  - Target: {args.limit} markets")
    print(f"  - include_active: {args.include_active}")
    print(f"  - include_resolved: {args.include_resolved}")
    
    # Fetch a larger batch to increase chances of finding enough markets
    fetch_limit = max(args.limit * 5, 100)  # Fetch 5x target or at least 100
    markets = fetch_gamma_markets(
        include_active=args.include_active,
        include_resolved=args.include_resolved,
        limit=fetch_limit,
    )

    if not markets:
        print("Warning: No markets fetched. Check API endpoints and credentials.")
        return 1

    print(f"Fetched {len(markets)} markets from Gamma API")
    print(f"\nProcessing {len(markets)} markets (using all fetched markets)...")
    print("=" * 60)

    # Convert to benchmark format with target count
    tasks, price_histories, orderbooks = convert_to_benchmark_format(
        markets, 
        min_volume=args.min_volume,
        target_count=args.limit,
        verbose=True
    )
    
    if len(tasks) == 0:
        print(f"\n❌ Warning: No markets processed after fetching {len(markets)} markets!")
        print(f"  - Try running with POLYMARKET_DEBUG=true to see details")
    elif len(tasks) < args.limit:
        print(f"\n⚠️  Warning: Only processed {len(tasks)} markets (target: {args.limit})")
        print(f"  - Fetched {len(markets)} markets from API")
        print(f"  - You may need to fetch more markets")

    # Filter out existing tasks if incremental
    if args.incremental:
        tasks = [t for t in tasks if t["task_id"] not in existing_task_ids]
        print(f"After filtering, {len(tasks)} new tasks to add")

    if not tasks:
        print("No new tasks to add.")
        return 0

    # Write to JSONL file
    print(f"Writing {len(tasks)} tasks to {metadata_file}...")
    mode = "a" if args.incremental and metadata_file.exists() else "w"
    with open(metadata_file, mode, encoding="utf-8") as f:
        for task in tasks:
            f.write(json.dumps(task, ensure_ascii=False) + "\n")

    print(f"Successfully wrote {len(tasks)} tasks to {metadata_file}")
    print(f"Total tasks in benchmark: {len(existing_task_ids) + len(tasks)}")
    
    # Write orderbook to separate file
    if orderbooks:
        orderbook_file = output_dir / "orderbook.jsonl"
        print(f"Writing {len(orderbooks)} orderbook records to {orderbook_file}...")
        orderbook_mode = "a" if args.incremental and orderbook_file.exists() else "w"
        with open(orderbook_file, orderbook_mode, encoding="utf-8") as f:
            for ob in orderbooks:
                f.write(json.dumps(ob, ensure_ascii=False) + "\n")
        print(f"Successfully wrote {len(orderbooks)} orderbook records to {orderbook_file}")
    else:
        print("No orderbook data to write")
    
    # Write price history to separate file
    if price_histories:
        price_history_file = output_dir / "price_history.jsonl"
        print(f"Writing {len(price_histories)} price history records to {price_history_file}...")
        price_history_mode = "a" if args.incremental and price_history_file.exists() else "w"
        with open(price_history_file, price_history_mode, encoding="utf-8") as f:
            for ph in price_histories:
                f.write(json.dumps(ph, ensure_ascii=False) + "\n")
        print(f"Successfully wrote {len(price_histories)} price history records to {price_history_file}")
    else:
        print("No price history data to write")

    return 0


if __name__ == "__main__":
    sys.exit(main())
