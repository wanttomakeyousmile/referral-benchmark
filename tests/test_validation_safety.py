"""Ensure validation is read-only and trusted evidence stays outside the working repository."""
import hashlib
import inspect
import tempfile
import unittest
from pathlib import Path
from tasks.validate_recovery_paths import run_all

ROOT = Path(__file__).resolve().parents[1]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ValidationSafetyTests(unittest.TestCase):
    def test_export_requires_explicit_opt_in(self):
        self.assertIs(inspect.signature(run_all).parameters['export'].default, False)

    def test_export_requires_destination(self):
        with self.assertRaises(ValueError):
            run_all(export=True)

    def test_export_refuses_working_repository_target(self):
        with self.assertRaises(ValueError):
            run_all(export=True, export_dir=ROOT / 'docs' / 'generated_evidence')

    def test_external_export_is_isolated(self):
        trusted = ROOT / 'docs/validation_results.json'
        before = sha(trusted)
        with tempfile.TemporaryDirectory(prefix='rr_valid_evidence_') as tmp:
            result = run_all(export=True, export_dir=Path(tmp))
            self.assertEqual(result['reference_paths_passed'], 20)
            self.assertEqual(result['alternative_paths_passed'], 12)
            self.assertEqual(len(list((Path(tmp) / 'validation_traces').glob('*/grade.json'))), 32)
            self.assertTrue((Path(tmp) / 'validation_results.json').is_file())
        self.assertEqual(sha(trusted), before)
        self.assertFalse((ROOT / 'docs/validation_traces').exists())

    def test_default_validation_preserves_saved_trace_and_summary(self):
        evidence = [ROOT / 'docs/validation_results.json',
                    ROOT / 'tasks/eval/RR_017.json']
        before = {str(path): sha(path) for path in evidence}
        result = run_all()
        self.assertEqual(result['reference_paths_passed'], 20)
        self.assertEqual(result['alternative_paths_passed'], 12)
        self.assertEqual(result['project_status'], 'in_development')
        self.assertEqual(before, {str(path): sha(path) for path in evidence})
        self.assertFalse((ROOT / 'docs/validation_traces').exists())

if __name__ == '__main__':
    unittest.main()
