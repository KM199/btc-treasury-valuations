#!/usr/bin/env python3
"""
Check if baseline scenario is included in scenario results.
"""

import json
from pathlib import Path

from strc_paths import OUTPUT_DIR

_candidates = [Path("scenario_test.json"), OUTPUT_DIR / "sata_valuation_results.json"]
_path = next((p for p in _candidates if p.is_file()), None)
if _path is None:
    raise SystemExit("Need scenario_test.json or output/sata_valuation_results.json")

with open(_path, 'r') as f:
    data = json.load(f)

scenario_results = data['scenario_results']
print('Total scenarios in results:', len(scenario_results))

# Check for baseline scenario (should have starting_price_pct close to 0)
baseline_found = False
for i, scenario in enumerate(scenario_results):
    pct = scenario['starting_price_pct']
    if abs(pct) < 0.001:
        print('Baseline scenario found at index', i, ': starting_price_pct =', pct)
        print('Mean NPV per share: $' + format(scenario['mean_npv_per_share'], ',.2f'))
        baseline_found = True
        break

if not baseline_found:
    print('ERROR: Baseline scenario NOT found in results!')

# Show all starting_price_pct values
print('All starting_price_pct values:')
for i, scenario in enumerate(scenario_results):
    print('  Scenario', i, ':', format(scenario['starting_price_pct'], '.3f'))
