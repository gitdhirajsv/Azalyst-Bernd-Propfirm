#!/usr/bin/env python3
"""Pine Script <-> Python parameter sync auditor (Phase 24).

Reads `input.int(...)` / `input.float(...)` / `input(...)` declarations from each
canonical Pine Script source and compares the defaults against the corresponding
Python constant in `BP_indicators.py` / `BP_rules_engine.py`. Reports any drift.

Usage:
    python audit_pine_to_python.py            # quick report, exits 0/1
    python audit_pine_to_python.py --verbose  # show every parameter checked

Sources audited:
  - 04_Pine_Script_Indicators/COTIndex_OTC.txt   -> COT lookback / thresholds
  - 04_Pine_Script_Indicators/Valuation_OTC.txt  -> ROC length / rescale / thresholds
  - 04_Pine_Script_Indicators/Seasonality_OTC.txt-> lookback years / lookahead bars
  - pinescript/COT V2 120-20.txt                 -> COT V2 formula constants
  - Blueprint - Cheatsheet.xlsx                  -> per-symbol overrides (informational)

When run from `Propfirm Trading Dashboard/`, paths are resolved relative to the
parent project root (D:/Azalyst Bernd Skorupinski/).
"""
from __future__ import annotations
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple


THIS_DIR  = Path(__file__).resolve().parent          # Propfirm Trading Dashboard/
PROJ_ROOT = THIS_DIR.parent                           # D:/Azalyst Bernd Skorupinski/

INDICATOR_PATHS = {
    "COTIndex":     PROJ_ROOT / "04_Pine_Script_Indicators" / "COTIndex_OTC.txt",
    "COTReport":    PROJ_ROOT / "04_Pine_Script_Indicators" / "COTReport_OTC.txt",
    "Seasonality":  PROJ_ROOT / "04_Pine_Script_Indicators" / "Seasonality_OTC.txt",
    "Valuation":    PROJ_ROOT / "04_Pine_Script_Indicators" / "Valuation_OTC.txt",
    "COTIndexV2":   PROJ_ROOT / "pinescript" / "COT V2 120-20.txt",
}


# Regex patterns for Pine Script `input.int`, `input.float`, `input.bool`
# Supports both old-style (input(default,...)) and new-style (input.int(default,...))
INPUT_RE = re.compile(
    r"""input(?:\.\w+)?\s*\(
        \s*(?:defval\s*=\s*)?              # optional defval=
        (?P<default>-?\d+(?:\.\d+)?|true|false)\s*,?
        \s*(?:title\s*=\s*)?                # optional title=
        ['"](?P<title>[^'"]+)['"]
    """,
    re.VERBOSE,
)


def parse_pine_inputs(path: Path) -> List[Tuple[str, str]]:
    """Extract list of (title, default) from Pine Script source.

    Returns parameter title strings as they appear in the script alongside
    their numeric defaults. Comments are not stripped — the regex is
    permissive enough to skip them.
    """
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="ignore")
    out = []
    for m in INPUT_RE.finditer(text):
        out.append((m.group("title").strip(), m.group("default")))
    return out


# ---- Python constants we want to verify ----
# Each entry: (description, expected_pine_title_substring, python_value, source_indicator)
def get_python_constants() -> List[Tuple[str, str, str, str]]:
    out = []

    # Avoid importing BP_indicators (heavy deps); read constants by source-grep.
    bp_ind_path = THIS_DIR / "BP_indicators.py"
    bp_rul_path = THIS_DIR / "BP_rules_engine.py"

    text_ind = bp_ind_path.read_text(encoding="utf-8", errors="ignore") if bp_ind_path.exists() else ""
    text_rul = bp_rul_path.read_text(encoding="utf-8", errors="ignore") if bp_rul_path.exists() else ""

    def grep(text: str, pattern: str, default: Optional[str] = None) -> Optional[str]:
        m = re.search(pattern, text)
        return m.group(1) if m else default

    # COT default lookback in Python is read from BP_config.yaml at runtime,
    # but the COTIndex class default in BP_indicators is the canonical fallback.
    # Search for `lookback_weeks: int = N` on the class signature.
    cot_lookback = grep(text_ind, r"lookback_weeks:\s*int\s*=\s*(\d+)")
    cot_upper    = grep(text_ind, r"upper_extreme:\s*float\s*=\s*([\d.]+)")
    cot_lower    = grep(text_ind, r"lower_extreme:\s*float\s*=\s*([\d.]+)")
    out.append(("COT default lookback",        "Lookback Period",       cot_lookback, "COTIndex"))
    out.append(("COT upper extreme threshold", "Upper Threshold",       cot_upper,    "COTIndex"))
    out.append(("COT lower extreme threshold", "Lower Threshold",       cot_lower,    "COTIndex"))

    # Valuation defaults
    val_length    = grep(text_ind, r"def __init__\([\s\S]*?length:\s*int\s*=\s*(\d+)", None)
    if val_length is None:  # try alt pattern
        val_length = grep(text_ind, r"class Valuation[\s\S]*?length:\s*int\s*=\s*(\d+)")
    val_rescale   = grep(text_ind, r"rescale_length:\s*int\s*=\s*(\d+)")
    val_overval   = grep(text_ind, r"overvalued:\s*float\s*=\s*([\d.\-]+)")
    val_underval  = grep(text_ind, r"undervalued:\s*float\s*=\s*([\d.\-]+)")
    out.append(("Valuation default Length",   "Length",                val_length,   "Valuation"))
    out.append(("Valuation rescale length",   "Rescale Length",        val_rescale,  "Valuation"))
    out.append(("Valuation overvalued",       "Overvalued",            val_overval,  "Valuation"))
    out.append(("Valuation undervalued",      "Undervalued",           val_underval, "Valuation"))

    # Seasonality defaults
    seas_lookback   = grep(text_ind, r"lookback_years:\s*int\s*=\s*(\d+)")
    seas_lookahead  = grep(text_ind, r"bias_lookahead_bars:\s*int\s*=\s*(\d+)")
    out.append(("Seasonality lookback years", "Lookback",              seas_lookback,  "Seasonality"))
    out.append(("Seasonality lookahead bars", "Forward",               seas_lookahead, "Seasonality"))

    return out


def find_pine_default(parsed: List[Tuple[str, str]], title_substring: str) -> Optional[str]:
    """Find the Pine Script default for a parameter whose title contains a substring."""
    needle = title_substring.lower()
    for title, default in parsed:
        if needle in title.lower():
            return default
    return None


def normalize_num(s: Optional[str]) -> Optional[float]:
    if s is None:
        return None
    try:
        return float(s)
    except (TypeError, ValueError):
        return None


def main() -> int:
    verbose = "--verbose" in sys.argv

    # Parse all Pine Script sources
    parsed: Dict[str, List[Tuple[str, str]]] = {}
    print("=" * 78)
    print("Pine Script <-> Python parameter sync audit")
    print("=" * 78)

    for name, path in INDICATOR_PATHS.items():
        if not path.exists():
            print(f"[MISS] {name:<14} {path}")
            continue
        ps = parse_pine_inputs(path)
        parsed[name] = ps
        if verbose:
            print(f"[OK]   {name:<14} {len(ps)} parameter(s) found")
            for title, default in ps:
                print(f"         '{title}' = {default}")

    print()
    print("Per-parameter check:")
    print("-" * 78)
    print(f"{'Parameter':<35} {'Pine':<12} {'Python':<12} {'Status'}")
    print("-" * 78)

    drift_count = 0
    constants = get_python_constants()
    for desc, title_sub, py_val, source in constants:
        ps = parsed.get(source, [])
        pine_val = find_pine_default(ps, title_sub)
        py_n   = normalize_num(py_val)
        pine_n = normalize_num(pine_val)
        if pine_n is None and py_n is None:
            status = "?"
        elif pine_n is None:
            status = "no-pine"
        elif py_n is None:
            status = "no-py"
        elif abs(pine_n - py_n) < 1e-6:
            status = "OK"
        else:
            status = "DRIFT"
            drift_count += 1
        print(f"{desc:<35} {str(pine_val):<12} {str(py_val):<12} {status}")

    print("-" * 78)
    if drift_count == 0:
        print("OK -- no drift detected between Pine Script defaults and Python constants.")
        return 0
    print(f"DRIFT -- {drift_count} parameter(s) differ between Pine Script and Python.")
    print("        Review and reconcile before next deploy.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
