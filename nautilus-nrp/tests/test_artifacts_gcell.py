"""Offline tests: stdout artifact export/collection, the bash part exporter, and GCell congestion statistics."""
import hashlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SKILL = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(SKILL / 'scripts'))
import gcell_stats  # noqa: E402
import stdout_artifacts as sa  # noqa: E402


class EmitCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.a = self.dir / 'a.png'
        self.a.write_bytes(os.urandom(40000))
        self.b = self.dir / 'b.png'
        self.b.write_bytes(os.urandom(90000))

    def tearDown(self):
        self.tmp.cleanup()

    def test_round_trip_budget_and_stored(self):
        buf = io.StringIO()
        out = sa.Emitter(budget_b64=100000, stream=buf)
        self.assertTrue(out.file('r1', 'seed', self.a))
        self.assertFalse(out.file('r1', 'final', self.b))   # 120000 b64 chars would pass the budget
        out.event('RUN_COMPLETE', run_id='r1')
        summary = sa.collect('noise from another writer\n' + buf.getvalue(), self.dir / 'out')
        self.assertEqual([w['name'] for w in summary['written']], ['a.png'])
        self.assertEqual((self.dir / 'out/r1/a.png').read_bytes(), self.a.read_bytes())
        self.assertEqual([s['name'] for s in summary['stored_only']], ['b.png'])
        self.assertEqual(summary['damaged'], [])

    def test_damaged_chunk_is_reported_not_written(self):
        buf = io.StringIO()
        sa.Emitter(stream=buf).file('r2', 'seed', self.a)
        lines = buf.getvalue().splitlines()
        lines[1] = lines[1][:-8] + 'AAAAAAAA'    # corrupt the second chunk
        summary = sa.collect('\n'.join(lines) + '\n', self.dir / 'out2')
        self.assertEqual(len(summary['damaged']), 1)
        self.assertFalse((self.dir / 'out2/r2/a.png').exists())

    def test_assemble_requires_every_part_and_full_hash(self):
        data = os.urandom(1000)
        parts = {0: data[:400], 1: data[400:800], 2: data[800:]}
        full = hashlib.sha256(data).hexdigest()
        self.assertEqual(sa.assemble(parts, full, 1000, 3), data)
        self.assertIsNone(sa.assemble({0: parts[0], 2: parts[2]}, full, 1000, 3))
        self.assertIsNone(sa.assemble(parts, '0' * 64, 1000, 3))

    def artifact_log(self, **fields):
        buf = io.StringIO()
        sa.Emitter(stream=buf).file('r1', 'seed', self.a)
        lines = buf.getvalue().splitlines()
        event = json.loads(lines[-1][4:])
        event.update(fields)
        lines[-1] = 'UCR ' + json.dumps(event)
        return '\n'.join(lines) + '\n'

    def test_unsafe_log_paths_are_reported_without_writes(self):
        cases = [
            {'run_id': '../escape'}, {'run_id': str(self.dir / 'escape')},
            {'name': '../escape'}, {'name': str(self.dir / 'escape')},
            {'run_id': '.'}, {'run_id': ''}, {'run_id': None},
            {'name': 'nested/../../escape'}, {'name': '..\\escape'},
        ]
        out = self.dir / 'unsafe-out'
        for fields in cases:
            for multipart in (False, True):
                with self.subTest(fields=fields, multipart=multipart):
                    metadata = dict(fields)
                    if multipart:
                        metadata.update(part=0, parts=1, full_sha256=hashlib.sha256(self.a.read_bytes()).hexdigest(),
                                        full_bytes=self.a.stat().st_size)
                    result = sa.collect(self.artifact_log(**metadata), out)
                    self.assertEqual(len(result['damaged']), 1)
                    self.assertIn('unsafe artifact', result['damaged'][0]['error'])
                    self.assertEqual(result['written'], [])
                    self.assertEqual(result['parts'], [])
                    self.assertFalse(out.exists())
                    self.assertFalse((self.dir / 'escape').exists())

    def test_existing_symlinks_cannot_escape_output_directory(self):
        outside = self.dir / 'outside'
        outside.mkdir()
        victim = outside / 'victim'
        victim.write_bytes(b'keep existing evidence')
        for location in ('run_id', 'name', 'multipart_name'):
            with self.subTest(location=location):
                out = self.dir / ('symlink-out-' + location)
                out.mkdir()
                if location == 'run_id':
                    (out / 'r1').symlink_to(outside, target_is_directory=True)
                    fields = {'name': 'victim'}
                else:
                    (out / 'r1').mkdir()
                    target_name = 'victim' if location == 'name' else 'victim.part000'
                    (out / 'r1' / target_name).symlink_to(victim)
                    fields = {'name': 'victim'}
                    if location == 'multipart_name':
                        fields.update(part=0, parts=1, full_sha256=hashlib.sha256(self.a.read_bytes()).hexdigest(),
                                      full_bytes=self.a.stat().st_size)
                result = sa.collect(self.artifact_log(**fields), out)
                self.assertEqual(len(result['damaged']), 1)
                self.assertIn('symlink', result['damaged'][0]['error'])
                self.assertEqual(result['written'], [])
                self.assertEqual(result['parts'], [])
                self.assertEqual(victim.read_bytes(), b'keep existing evidence')

    def test_valid_multipart_collection_still_round_trips(self):
        digest = hashlib.sha256(self.a.read_bytes()).hexdigest()
        log = self.artifact_log(part=0, parts=1, full_sha256=digest, full_bytes=self.a.stat().st_size)
        result = sa.collect(log, self.dir / 'multipart-out')
        self.assertEqual(result['damaged'], [])
        self.assertEqual(len(result['parts']), 1)
        part = result['parts'][0]
        self.assertEqual(Path(part['path']).name, 'a.png.part000')
        data = Path(part['path']).read_bytes()
        self.assertEqual(sa.assemble({0: data}, part['full_sha256'], part['full_bytes'], part['parts']),
                         self.a.read_bytes())

    def test_malformed_events_do_not_prevent_valid_collection(self):
        noise = 'UCR []\nUCR null\nUCR 1\nUCR broken-json\n'
        malformed = self.artifact_log(name=None) + self.artifact_log(part='bad', parts=1)
        result = sa.collect(noise + malformed + self.artifact_log(), self.dir / 'mixed-out')
        self.assertEqual(len(result['damaged']), 2)
        self.assertEqual(len(result['written']), 1)
        self.assertEqual(Path(result['written'][0]['path']).read_bytes(), self.a.read_bytes())


@unittest.skipUnless(all(shutil.which(t) for t in ('bash', 'gzip', 'split', 'base64', 'sha256sum')), 'needs bash + coreutils + gzip')
class BashExporter(unittest.TestCase):
    def run_export(self, plan_lines, env):
        plan = self.dir / 'plan.tsv'
        plan.write_text(''.join(plan_lines))
        out = subprocess.run(['bash', str(SKILL / 'examples/stdout_export.sh')], capture_output=True, text=True, timeout=120,
                             env={**os.environ, 'PLAN': str(plan), 'SCRATCH': str(self.dir / 'scratch'), **env})
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout

    def test_parts_deferred_then_sent_by_a_second_pod(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.dir = Path(tmp)
            src = self.dir / 'floorplan.html'
            src.write_bytes(os.urandom(2_500_000))          # incompressible: ~2.5 MB of gzip
            env = {'PART': '1000000', 'BUDGET': '2800000'}  # room for two parts per "Pod"
            first = self.run_export([f'run1\t{src}\tall\n', f'gone\t{self.dir}/missing.html\tall\n'], env)
            chunks, events = sa.parse(first)
            sent = {e['part']: sa.artifact_bytes(chunks, e) for e in events if e.get('event') == 'ARTIFACT'}
            deferred = [e['part'] for e in events if e.get('event') == 'PART_DEFERRED']
            self.assertEqual(sorted(sent), [0, 1])
            self.assertEqual(deferred, [2])
            self.assertIn('MISSING', [e['event'] for e in events])
            second = self.run_export([f'run1\t{src}\t{",".join(map(str, deferred))}\n'], env)
            chunks2, events2 = sa.parse(second)
            sent.update({e['part']: sa.artifact_bytes(chunks2, e) for e in events2 if e.get('event') == 'ARTIFACT'})
            meta = next(e for e in events if e.get('event') == 'ARTIFACT')
            whole = sa.assemble(sent, meta['full_sha256'], meta['full_bytes'], meta['parts'])
            reference = subprocess.run(['gzip', '-9', '-n', '-c', str(src)], capture_output=True).stdout
            self.assertEqual(whole, reference)              # gzip -n is deterministic across Pods


class GcellStats(unittest.TestCase):
    def test_macro_gcells_excluded(self):
        rows = ['R 1.000 1.000 0.500 0.500', 'R 1.000 1.000 0.500 0.950', 'R 0.500 0.500 0.500 0.500', 'R 0.500 0.500 1.200 0.500']
        text = 'GRID 4 4\nGEXT 0 0 40 40\n' + '\n'.join(rows) + '\nMACRO 0 0 20 20\n'
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'grid.cong'
            path.write_text(text)
            s = gcell_stats.summarize(path)
        self.assertEqual(s['grid_shape'], [4, 4])
        self.assertAlmostEqual(s['macro_gcell_fraction'], 4 / 16)
        self.assertEqual(s['outside_macros']['gcells'], 12)
        self.assertAlmostEqual(s['outside_macros']['frac_ge_0_9'], 2 / 12)      # 0.95 and 1.2
        self.assertAlmostEqual(s['all_gcells']['frac_ge_0_99'], 5 / 16)        # the four macro GCells and 1.2
        self.assertAlmostEqual(s['outside_macros']['frac_over_1'], 1 / 12)
        self.assertAlmostEqual(s['outside_macros']['peak'], 1.2, places=5)

    def test_extent_is_first_and_last_gcell_origin(self):
        # OpenROAD's getGridX/getGridY list GCell ORIGINS: GEXT 0..30 over 4 GCells means pitch 10, and the last GCell
        # runs from 30 to the die edge (gcd: 12 origins 0..31.35 um, die 36.725 um).
        mask = gcell_stats.macro_mask(4, 2, [0, 0, 30, 10], [[10, 0, 20, 5]])   # pitch 10 in x and y
        self.assertEqual(list(mask), [0, 1, 0, 0, 0, 0, 0, 0])
        mask = gcell_stats.macro_mask(4, 2, [0, 0, 30, 10], [[31, 12, 35, 14]])  # inside the wider last GCells
        self.assertEqual(list(mask), [0, 0, 0, 0, 0, 0, 0, 1])

    def test_incomplete_dump_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'grid.cong'
            path.write_text('GRID 3 3\nGEXT 0 0 3 3\nR 0.1 0.2 0.3\n')
            with self.assertRaises(ValueError):
                gcell_stats.parse(path)


if __name__ == '__main__':
    unittest.main()
