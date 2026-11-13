"""Non-visual tests of panel metadata and source provenance."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from build_pipeline import source_manifest

SCRATCH=Path(__file__).resolve().parents[1]/"work"/"desktop_tests"
SCRATCH.mkdir(parents=True,exist_ok=True)


class SourceManifestTests(unittest.TestCase):
    def test_runtime_state_does_not_change_source_identity(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root=Path(folder)
            (root/'work').mkdir()
            (root/'desktop_app.pyw').write_text('print("app")')
            before=source_manifest(root)
            (root/'work/build_status.json').write_text('{"running":true}')
            self.assertEqual(before,source_manifest(root))
            self.assertIn('desktop_app.pyw',before)

    def test_copied_chats_are_not_app_source(self):
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root=Path(folder)
            (root/'desktop_app.pyw').write_text('print("app")')
            before=source_manifest(root)
            (root/'conversations'/'abc').mkdir(parents=True)
            (root/'conversations'/'abc'/'custom-title.json').write_text('{"title":"chat"}')
            self.assertEqual(before,source_manifest(root))


class FreshnessDisplayTests(unittest.TestCase):
    def test_saved_old_green_status_is_not_presented_as_current(self):
        from desktop_ui import saved_data_summary
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root=Path(folder);(root/'output').mkdir()
            (root/'output/monitor_status.json').write_text(json.dumps({'as_of':'2026-11-05','structural_and_freshness_ok':True}))
            with patch('validation.freshness',return_value={'ok':False,'reason':'Latest completed session is November 6'}):
                title,detail,current=saved_data_summary(root)
            self.assertFalse(current)
            self.assertIn('Refresh needed',detail)
            self.assertIn('2026-11-05',title)

    def test_missing_report_is_explicit(self):
        from desktop_ui import saved_data_summary
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            title,detail,current=saved_data_summary(Path(folder))
            self.assertFalse(current)
            self.assertIn('No built data',title)

    def test_nonobject_metadata_does_not_crash_startup(self):
        from desktop_ui import saved_data_summary
        with tempfile.TemporaryDirectory(dir=SCRATCH) as folder:
            root=Path(folder);(root/'output').mkdir()
            (root/'output/monitor_status.json').write_text('[]')
            title,detail,current=saved_data_summary(root)
            self.assertFalse(current)
            self.assertIn('No built data',title)


if __name__=='__main__':unittest.main()
