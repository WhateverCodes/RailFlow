"""Write the reproducible simulated planning data as a reviewable local artifact."""
import json
import pathlib
import sys
ROOT=pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'planner'))
from scenario import build_scenario
data=build_scenario()
target=ROOT/'data/synthetic-scenario.json'
target.write_text(json.dumps(data,separators=(',',':'))+'\n')
print('Saved synthetic-scenario.json:',len(data['assets']),'assets,',len(data['tasks']),'tasks,',len(data['services']),'services.')
