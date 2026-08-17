from pathlib import Path
import yaml
from eval.benchmark.cases_loader import CASES_DIR, load_cases
from eval.benchmark.snapshot import SnapshotSandbox

def test_every_mini_dev_ground_truth_ref_resolves_to_one_scalar():
    manifest = yaml.safe_load(Path('eval/round_b/mini_dev_v1.yaml').read_text(encoding='utf-8'))
    cases = {case.id: case for case in load_cases(CASES_DIR, split='dev')}
    conn = SnapshotSandbox().connect(guard=False)
    try:
        for case_id in manifest['ordered_case_ids']:
            for ref, spec in cases[case_id].ground_truth_refs.items():
                cur = conn.execute(spec['sql']); assert len(cur.fetchall()) == 1 and len(cur.description or []) == 1, f'{case_id}/{ref}'
    finally: conn.close()
