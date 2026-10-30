import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
sys.path.insert(0, str(ROOT/'examples'))
from start_budget import start_budget
from pod_identity import pod_prefix, resolve
import scratch_stage

NOW = 1_800_000_000.0


def row(name, age, phase='Running', cpu=None, memory=None, outside=None):
    created = dt.datetime.fromtimestamp(NOW - age, dt.timezone.utc).isoformat()
    return {'name': name, 'phase': phase, 'created_at': created, 'cpu_ratio': cpu,
            'memory_ratio': memory, 'outside': outside}


class StartBudgetTests(unittest.TestCase):
    def test_only_young_pods_not_yet_in_band_hold_slots(self):
        rows = [row('in-band', 60, cpu=.9, memory=.6, outside=False),
                row('outside', 60, cpu=.05, memory=.6, outside=True),
                row('no-metrics', 60),
                row('old-outside', 3600, cpu=.05, memory=.6, outside=True),
                row('pending', 0, phase='Pending')]
        result = start_budget(rows, now=NOW, floor=8)
        self.assertEqual(result['holding_pods'], ['no-metrics', 'outside', 'pending'])
        self.assertEqual((result['running'], result['cap'], result['allow']), (4, 8, 5))

    def test_cap_scales_with_running_pods_between_floor_and_ceiling(self):
        mature = [row('m%d' % i, 3600, cpu=.9, memory=.6, outside=False) for i in range(100)]
        self.assertEqual(start_budget(mature, now=NOW)['cap'], 25)
        self.assertEqual(start_budget(mature * 3, now=NOW)['cap'], 40)
        self.assertEqual(start_budget(mature[:10], now=NOW)['cap'], 8)

    def test_pending_count_and_unknown_age_hold_slots_and_allow_is_never_negative(self):
        rows = [row('young%d' % i, 10) for i in range(6)] + [{'name': 'no-age', 'phase': 'Running'}]
        result = start_budget(rows, now=NOW, floor=4, pending=3)
        self.assertEqual((result['holding'], result['allow']), (10, 0))


class PodIdentityTests(unittest.TestCase):
    def test_long_job_name_uses_truncated_generate_name_prefix(self):
        job = 'alice-study-placement-' + 'x' * 40                     # 62 characters
        pod = pod_prefix(job) + 'ab1cd'
        self.assertEqual(len(pod), 63)
        self.assertNotIn(job, pod)
        lines = [json.dumps({'pods': [{'name': pod, 'uid': 'pod-uid'}]})]
        self.assertEqual(resolve([{'name': job, 'uid': 'job-uid'}], snapshot_lines=lines)[job],
                         {'status': 'resolved', 'pod_name': pod, 'pod_uid': 'pod-uid', 'source': 'snapshots'})

    def test_events_are_bound_to_the_job_uid(self):
        events = {'items': [
            {'involvedObject': {'kind': 'Job', 'uid': 'old-job'}, 'message': 'Created pod: alice-a-old11'},
            {'involvedObject': {'kind': 'Job', 'uid': 'job-a'}, 'message': 'Created pod: alice-a-new22'}]}
        result = resolve([{'name': 'alice-a', 'uid': 'job-a'}], events)
        self.assertEqual(result['alice-a']['pod_name'], 'alice-a-new22')

    def test_retries_shared_prefixes_and_other_owners_are_not_guessed(self):
        base = 'alice-' + 'y' * 60
        jobs = [{'name': base + '-one', 'uid': 'j1'}, {'name': base + '-two', 'uid': 'j2'},
                {'name': 'alice-b', 'uid': 'jb'}, {'name': 'alice-c', 'uid': 'jc'}]
        lines = [json.dumps({'pods': [
            {'name': pod_prefix(base) + 'zz9zz', 'uid': 'p0'},
            {'name': 'alice-b-aaaaa', 'uid': 'p1'}, {'name': 'alice-b-bbbbb', 'uid': 'p2'},
            {'name': 'alice-c-ccccc', 'uid': 'p3', 'owners': [{'kind': 'Job', 'uid': 'another-job'}]}]}),
            'not json']
        result = resolve(jobs, snapshot_lines=lines)
        self.assertEqual(result[base + '-one']['status'], 'ambiguous')
        self.assertEqual(result[base + '-two']['status'], 'ambiguous')
        self.assertEqual(result['alice-b']['candidates'], ['alice-b-aaaaa', 'alice-b-bbbbb'])
        self.assertEqual(result['alice-c']['status'], 'missing')


class ScratchStageTests(unittest.TestCase):
    def test_nested_inputs_keep_their_relative_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); pvc = tmp/'pvc'; (pvc/'inputs').mkdir(parents=True)
            (pvc/'inputs'/'design.v').write_text('module design; endmodule\n')
            scratch_stage.stage_in(['inputs/design.v'], pvc, tmp/'scratch')
            self.assertEqual((tmp/'scratch'/'inputs'/'design.v').read_text(),
                             (pvc/'inputs'/'design.v').read_text())

    def test_outputs_are_verified_on_the_pvc_before_the_done_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); pvc = tmp/'pvc'; pvc.mkdir()
            (pvc/'in.txt').write_text('input\n')
            command = [sys.executable, '-c', "open('out.txt', 'w').write(open('in.txt').read().upper())"]
            rc = scratch_stage.run_step(command, ['in.txt'], pvc, tmp/'scratch', pvc/'.tmp', pvc/'done')
            self.assertEqual(rc, 0)
            self.assertEqual((pvc/'out.txt').read_text(), 'INPUT\n')
            self.assertTrue((pvc/'done').exists())
            self.assertEqual(list((pvc/'.tmp').iterdir()), [])

    def test_failed_command_publishes_nothing_and_writes_no_marker(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); pvc = tmp/'pvc'; pvc.mkdir()
            (pvc/'in.txt').write_text('input\n')
            command = [sys.executable, '-c', "open('partial.txt', 'w').write('x'); raise SystemExit(7)"]
            rc = scratch_stage.run_step(command, ['in.txt'], pvc, tmp/'scratch', pvc/'.tmp', pvc/'done')
            self.assertEqual(rc, 7)
            self.assertFalse((pvc/'partial.txt').exists() or (pvc/'done').exists())

    def test_stage_in_rejects_a_copy_that_differs_from_the_expected_hash(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp); pvc = tmp/'pvc'; pvc.mkdir()
            (pvc/'in.txt').write_text('input\n')
            with self.assertRaises(RuntimeError):
                scratch_stage.stage_in(['in.txt'], pvc, tmp/'scratch', expected={'in.txt': '0' * 64})


if __name__ == '__main__':
    unittest.main()
