"""Release payload contract: staged bytes, version and native-cache exclusions."""
import hashlib,json,unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];PUB=ROOT/'public'
class ReleaseTests(unittest.TestCase):
 def test_inventory_matches_served_bytes_without_native_caches(self):
  manifest=json.loads((PUB/'release-manifest.json').read_text())
  self.assertEqual(manifest['version'],'0.12.0')
  for path,entry in manifest['files'].items():
   self.assertNotIn('__pycache__',path);self.assertFalse(path.endswith('.pyc'))
   data=(PUB/path).read_bytes();self.assertEqual(len(data),entry['bytes'],path)
   self.assertEqual(hashlib.sha256(data).hexdigest(),entry['sha256'],path)
 def test_worker_sources_match_canonical_python(self):
  for path in (ROOT/'NeCosmos-Simulation/src').rglob('*.py'):
   staged=PUB/'engine/NeCosmos-Simulation'/path.relative_to(ROOT/'NeCosmos-Simulation')
   self.assertEqual(path.read_bytes(),staged.read_bytes(),str(path))
  engine=json.loads((PUB/'engine/manifest.json').read_text())
  self.assertEqual(engine['version'],'0.12.0')
  for path in engine['files']:self.assertTrue((PUB/'engine'/path).is_file(),path)
