import sys
import pprint
sys.path.insert(0, '/home/esec/docling_test/UI')
try:
    from app.main import load_analysis_detail
except ImportError:
    from main import load_analysis_detail

std = load_analysis_detail('std_ACQUITTED_TSAD000001822024_1_2025-10-08_analysis')
npa = load_analysis_detail('npa_1')

print('--- NPA Audit Subsections ---')
pprint.pprint(npa['audit_subsections'])

print('--- NPA Taxonomy ---')
pprint.pprint(npa['taxonomy'])

print('--- NPA Legal Summary ---')
pprint.pprint(npa['legal_summary'])
