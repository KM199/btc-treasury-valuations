import json

# Read the notebook
with open('sata_valuation.ipynb', 'r') as f:
    nb = json.load(f)

# Remove the Yahoo Finance code from cell 3
cell_source = nb['cells'][3]['source']
new_source = []

skip_section = False
for line in cell_source:
    # Start skipping when we hit the Bitcoin Price Configuration
    if '# Bitcoin Price Configuration' in line:
        skip_section = True
        continue

    # Stop skipping when we hit the Strive Treasury Parameters
    if skip_section and '# Strive Treasury Parameters' in line:
        skip_section = False

    # Skip the lines in between
    if skip_section:
        continue

    # Also skip the print statement that shows btc_price_source
    if 'btc_price_source' in line and 'print' in line:
        continue

    new_source.append(line)

nb['cells'][3]['source'] = new_source

# Write back the modified notebook
with open('sata_valuation.ipynb', 'w') as f:
    json.dump(nb, f, indent=1)

print('Successfully removed redundant Bitcoin price fetching code!')
