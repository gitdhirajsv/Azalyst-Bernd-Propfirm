import json
with open(r"D:\Azalyst Bernd Skorupinski\Propfirm Trading Dashboard\goldtest\gold_results.json", encoding="utf-8") as f:
    data = json.load(f)

results = data if isinstance(data, list) else data.get("results", [])
total = len(results)
errors = sum(1 for r in results if r.get("error"))
valid = total - errors

bias_match = sum(1 for r in results if (r.get("verdict") or {}).get("bias_match") == True)
bias_only  = sum(1 for r in results if (r.get("verdict") or {}).get("bias_only_match") == True)

# Count opposite direction: system fired directional but WRONG direction
opposite = 0
for r in results:
    b_bias = (r.get("bernd") or {}).get("bias", "neutral")
    s_dir  = (r.get("system") or {}).get("direction", "neutral")
    if b_bias in ("long","short") and s_dir in ("long","short") and b_bias != s_dir:
        opposite += 1

# bias_only opposites
opp_bias_only = 0
for r in results:
    b_bias    = (r.get("bernd") or {}).get("bias", "neutral")
    s_bias_only = (r.get("system") or {}).get("bias_only", "neutral")
    if b_bias in ("long","short") and s_bias_only in ("long","short") and b_bias != s_bias_only:
        opp_bias_only += 1

print(f"Total cases:           {total}")
print(f"Errors:                {errors}")
print(f"Valid:                 {valid}")
print(f"Stage-2 full signal:   {bias_match}/{valid} = {bias_match/valid*100:.1f}%")
print(f"Stage-1 bias-only:     {bias_only}/{valid} = {bias_only/valid*100:.1f}%")
print(f"Opposite (Stage-2):    {opposite}")
print(f"Opposite (Stage-1):    {opp_bias_only}")

# Asset-class breakdown of Stage-1
from collections import defaultdict
ac_counts = defaultdict(lambda: {"pass": 0, "total": 0})
for r in results:
    if r.get("error"):
        continue
    ac = r.get("asset_class", "unknown")
    ac_counts[ac]["total"] += 1
    if (r.get("verdict") or {}).get("bias_only_match") == True:
        ac_counts[ac]["pass"] += 1

print("\nStage-1 by asset class:")
for ac, cnt in sorted(ac_counts.items()):
    p, t = cnt["pass"], cnt["total"]
    pct = p/t*100 if t else 0
    print(f"  {ac:<22} {p}/{t} = {pct:.0f}%")
