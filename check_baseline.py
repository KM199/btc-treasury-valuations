#!/usr/bin/env python3
"""
Check that the baseline scenario is present in multi-scenario valuation results.

Reads ``output/sata_valuation_results.json`` (see strc_paths / sata_valuation.py defaults).
"""

import json
import sys
from pathlib import Path

from strc_paths import OUTPUT_DIR

_path = OUTPUT_DIR / "sata_valuation_results.json"
if not _path.is_file():
    sys.exit(f"Missing {_path} — run sata_valuation.py first.")

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
