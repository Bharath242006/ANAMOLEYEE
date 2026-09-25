"""
utils/json_sanitizer.py - JSON Sanitization Helper for FastAPI & Data Pipelines.

Recursively cleans Python objects, dictionaries, lists, floats, and NumPy types
so they can be safely encoded into standard JSON format without crashing FastAPI
with 'Out of range float values are not JSON compliant'.

- NaN -> None (renders as null in JSON)
- +Infinity -> None (renders as null in JSON)
- -Infinity -> None (renders as null in JSON)
- NumPy types -> standard Python int/float/bool/list primitives
"""

import math
from collections import deque
import numpy as np
import pandas as pd


def sanitize_for_json(obj):
    """
    Recursively converts data structures into JSON-compliant Python primitives.

    Rules:
    - None / NaN / +Inf / -Inf -> None
    - bool / str / int -> unchanged
    - float -> float (if finite) else None
    - NumPy scalar types -> Python int / float / bool / list
    - dict / list / tuple / set / deque / Series / DataFrame -> recursively sanitized
    """
    if obj is None:
        return None

    # Collections & Containers first (avoids pd.isna ambiguous truth value on empty containers)
    if isinstance(obj, dict):
        return {str(k): sanitize_for_json(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set, deque)):
        return [sanitize_for_json(x) for x in obj]
    if isinstance(obj, np.ndarray):
        return [sanitize_for_json(x) for x in obj.tolist()]
    if isinstance(obj, pd.Series):
        return [sanitize_for_json(x) for x in obj.tolist()]
    if isinstance(obj, pd.DataFrame):
        return sanitize_for_json(obj.to_dict(orient="records"))

    # Basic Python Primitives
    if isinstance(obj, bool):
        return bool(obj)
    if isinstance(obj, int):
        return int(obj)
    if isinstance(obj, str):
        return str(obj)
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return float(obj)

    # NumPy Scalars
    if isinstance(obj, (np.bool_,)):
        return bool(obj)
    if isinstance(obj, (np.integer, np.signedinteger, np.unsignedinteger)):
        return int(obj)
    if isinstance(obj, (np.floating, np.complexfloating)):
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val

    # Check for pandas NaN / NaT / scalar null
    try:
        if pd.isna(obj):
            return None
    except Exception:
        pass

    # Fallback attempt for numeric or object wrapper
    try:
        val = float(obj)
        if math.isnan(val) or math.isinf(val):
            return None
        return val
    except (TypeError, ValueError):
        return str(obj)

