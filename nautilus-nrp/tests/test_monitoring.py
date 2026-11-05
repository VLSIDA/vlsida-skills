import copy
import datetime as dt
import json
from pathlib import Path
import re
import os
import subprocess
import sys
import tempfile
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
from nrp_common import ApiError, Kube, compact_pod, job_status, pod_request, pod_slots, quantity, utcnow
from live_status import build_view, collect, load_runs, render, safe_link
from check_admission import pod_probe, probe
from watch_job import observe
from band_check import exit_code
from demo_status import make_demo


def pod():
    return {'metadata': {'name': 'alice-job-pod', 'uid': 'pod-one',
            'creationTimestamp': (dt.datetime.now(dt.timezone.utc)-dt.timedelta(hours=1)).isoformat(),
            'ownerReferences': [{'kind': 'Job', 'uid': 'job-one'}]},
            'spec': {'containers': [{'name': 'worker', 'resources': {'requests': {'cpu': '4', 'memory': '4Gi'}}}]},
            'status': {'phase': 'Running', 'containerStatuses': [{'name': 'worker', 'state': {'running': {}}}]}}


def metric(cpu='1', memory='1Gi'):
    return {'metadata': {'name': 'alice-job-pod'}, 'timestamp': utcnow(),
            'containers': [{'name': 'worker', 'usage': {'cpu': cpu, 'memory': memory}}]}


def job(state=None):
    return {'kind': 'Job', 'metadata': {'name': 'alice-job', 'uid': 'job-one', 'namespace': 'test'},
            'spec': {'suspend': state == 'Suspended', 'template': {'metadata': {'labels': {'app': 'test'}},
                     'spec': copy.deepcopy(pod()['spec'])}},
            'status': {'active': 0 if state else 1,
                       'conditions': [] if not state else [{'type': state, 'status': 'True'}]}}


class UsageTests(unittest.TestCase):
    def test_quantities_and_unknown_are_not_zero(self):
        for value, expected in [('800000000n', .8), ('250000u', .25), ('925m', .925),
                                 ('4', 4), ('1.5Gi', 1.5*2**30), ('1e6', 1e6), ('2M', 2e6)]:
            self.assertEqual(quantity(value), expected)
        with self.assertRaises(ValueError): quantity('unavailable')
        row = compact_pod(pod()); self.assertIsNone(row['outside']); self.assertEqual(exit_code([row]), 104)

    def test_cpu_request_transition_changes_observed_floor(self):
        p = pod(); p['spec']['containers'][0]['resources']['requests']['cpu'] = '4800m'
        self.assertTrue(compact_pod(p, metric('925m'))['outside'])
        p['spec']['containers'][0]['resources']['requests']['cpu'] = '4'
        self.assertFalse(compact_pod(p, metric('925m'))['outside'])

    def test_stale_or_reused_identity_metrics_are_unknown(self):
        for timestamp in ['2020-01-01T00:00:00Z', (dt.datetime.now(dt.timezone.utc)+dt.timedelta(hours=1)).isoformat()]:
            m = metric(); m['timestamp'] = timestamp
            self.assertIsNone(compact_pod(pod(), m)['outside'])
        m = metric(); m['metadata']['uid'] = 'old-pod-uid'
        self.assertIsNone(compact_pod(pod(), m)['outside'])

    def test_missing_running_container_is_not_healthy(self):
        p = pod(); p['status']['containerStatuses'].append({'name': 'sidecar', 'state': {'running': {}}})
        self.assertIsNone(compact_pod(p, metric())['outside'])

    def test_init_sidecar_peak_and_overhead(self):
        p = pod(); p['spec']['initContainers'] = [
            {'name': 'sidecar', 'restartPolicy': 'Always', 'resources': {'requests': {'cpu': '1'}}},
            {'name': 'prepare', 'resources': {'requests': {'cpu': '8'}}}]
        p['spec']['overhead'] = {'cpu': '100m'}
        self.assertAlmostEqual(pod_request(p, 'cpu'), 9.1)
        p['spec']['resources'] = {'requests': {'cpu': '10'}}
        self.assertAlmostEqual(pod_request(p, 'cpu'), 10.1)

    def test_scoped_zero_quota_and_all_namespace_nonterminal_pods(self):
        quotas = [{'spec': {'scopes': ['PriorityClass']}, 'status': {'hard': {'pods': '0'}}},
                  {'spec': {}, 'status': {'hard': {'pods': '200'}, 'used': {'pods': '2'}}}]
        pods = [{'status': {'phase': s}} for s in ['Running', 'Pending', 'Unknown', 'Succeeded', 'Failed']]
        pods[0]['metadata'] = {'deletionTimestamp': utcnow()}
        self.assertEqual(pod_slots(quotas, pods), {'ceiling': 200, 'used': 3, 'free': 197})


class NativeWatchTests(unittest.TestCase):
    def client(self, state):
        class Fake:
            def json(self, args):
                return job(state) if args[1] == 'job' else {'items': [pod()]}
            def logs(self, *args): return 'epoch 3\nERROR application case failed\n'
        return Fake()

    def test_only_complete_failed_are_terminal(self):
        for state in ['Suspended', 'FailureTarget']:
            result = observe(self.client(state), 'alice-job', pattern=re.compile('epoch'))
            self.assertIsNone(result['exit_code'])
        self.assertEqual(observe(self.client('Complete'), 'alice-job')['exit_code'], 0)
        self.assertEqual(observe(self.client('Failed'), 'alice-job')['exit_code'], 1)

    def test_changed_job_uid_holds_instead_of_following_new_job(self):
        with self.assertRaises(ApiError): observe(self.client('Complete'), 'alice-job', 'previous-job')

    def test_terminal_missing_stdout_or_owned_pod_is_collection_held(self):
        client = self.client('Complete')
        client.logs = lambda *args: (_ for _ in ()).throw(ApiError('Pod disappeared'))
        self.assertEqual(observe(client, 'alice-job')['exit_code'], 2)

    def test_stdout_is_rejected_if_uid_changes_during_read(self):
        class Fake(Kube):
            def __init__(self): self.reads = 0
            def json(self, args, document=None):
                self.reads += 1; p = pod()
                if self.reads > 1: p['metadata']['uid'] = 'replacement'
                return p
            def run(self, *args): return 'old-looking success'
        with self.assertRaises(ApiError): Fake().logs(pod(), 'worker')


class DashboardTests(unittest.TestCase):
    def test_native_complete_does_not_become_application_success(self):
        s, runs, a = make_demo(); view = build_view(s)
        self.assertTrue(any(r['native_status'] == 'Job complete' for r in view['rows']))
        self.assertTrue(all(r['application_status'] == 'not supplied' for r in view['rows']))
        view = build_view(s, runs, a)
        sim = next(r for r in view['rows'] if r['group'] == 'simulation' and r['status'] == 'flow_failed')
        self.assertEqual(sim['native_status'], 'Job complete'); self.assertEqual(sim['application_status'], 'flow_failed')
        self.assertEqual(view['namespace_active_pods'], 3); self.assertEqual(view['scoped_active_pods'], 2)

    def test_reported_terminal_result_requires_evidence_and_matching_uid(self):
        s, runs, _ = make_demo(); runs['runs'][0].pop('evidence')
        self.assertIn('unverified', build_view(s, runs)['rows'][0]['application_status'])
        runs['runs'][0]['job_uid'] = 'wrong-current-job'
        self.assertIn('UID mismatch', build_view(s, runs)['rows'][0]['native_status'])

    def test_api_failure_retains_data_without_refreshing_its_timestamp(self):
        s, _, _ = make_demo(); before = s['sections']['pods']['observed_at']
        class Fake:
            context = 'synthetic-demo'; namespace = 'demo'; selector = 'app=demo,user=alice'
            def json(self, args): raise ApiError('OIDC unavailable')
        after = collect(Fake(), s); view = build_view(after)
        self.assertEqual(after['sections']['pods']['observed_at'], before)
        self.assertEqual(view['scoped_active_pods'], 2)
        self.assertTrue(view['sections']['pods']['stale']); self.assertTrue(view['warnings'])

    def test_duplicate_run_ids_and_unsafe_artifact_urls_fail(self):
        _, runs, _ = make_demo(); runs['runs'].append(copy.deepcopy(runs['runs'][0]))
        with tempfile.TemporaryDirectory() as d:
            p = Path(d)/'runs.json'; p.write_text(json.dumps(runs))
            with self.assertRaises(ValueError): load_runs(p)
        for value in ['javascript:alert(1)', 'file:///etc/passwd', '//outside.example/x', 'data:text/html,test', '\\evil']:
            self.assertIsNone(safe_link(value))
        self.assertEqual(safe_link('images/result.png'), 'images/result.png')

    def test_embedded_json_does_not_escape_script_element(self):
        s, runs, _ = make_demo(); attack = '</script><img src=x onerror=alert(1)>'
        runs['title'] = attack; text = render(build_view(s, runs))
        self.assertNotIn(attack, text); self.assertIn('\\u003c/script', text)

    def test_admission_proof_for_another_namespace_is_unknown(self):
        s, runs, a = make_demo(); a['namespace'] = 'another'
        self.assertIsNone(build_view(s, runs, a)['admission']['allowed'])


class AdmissionTests(unittest.TestCase):
    def test_exact_shape_is_dry_run_only_and_input_is_unchanged(self):
        original = job(); saved = copy.deepcopy(original); calls = []
        class Fake:
            namespace = 'test'; context = 'nautilus'
            def json(self, args, document=None): calls.append((args, document)); return document
        result = probe(Fake(), original)
        self.assertTrue(result['allowed']); self.assertEqual(original, saved)
        self.assertEqual(calls[0][0], ['create', '--dry-run=server', '-f', '-', '-o', 'json'])
        self.assertEqual(calls[0][1]['kind'], 'Pod')
        self.assertEqual(calls[0][1]['spec'], original['spec']['template']['spec'])

    def test_native_refusal_differs_from_transport_timeout(self):
        class Fake:
            namespace = 'test'; context = 'nautilus'
            def __init__(self, error): self.error = error
            def json(self, *args): raise ApiError(self.error)
        self.assertIs(probe(Fake('admission webhook denied the request: utilization is too low'), job())['allowed'], False)
        self.assertIsNone(probe(Fake('kubectl timed out'), job())['allowed'])

    def test_scope_mismatch_rejected_before_network(self):
        with self.assertRaises(ValueError): pod_probe(job(), 'other')

    def test_owner_bound_pod_keeps_owner_reference(self):
        p = pod(); p['kind'] = 'Pod'
        probe_pod, _ = pod_probe(p, 'test')
        self.assertEqual(probe_pod['metadata']['ownerReferences'], p['metadata']['ownerReferences'])


class CommandTests(unittest.TestCase):
    def fake_environment(self, directory, body):
        fake = Path(directory)/'kubectl'
        fake.write_text('#!' + sys.executable + '\n' + body); fake.chmod(0o755)
        return dict(os.environ, PATH=str(directory) + os.pathsep + os.environ.get('PATH', ''))

    def test_whole_auth_subprocess_group_has_a_wall_clock_timeout(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as d:
            env = self.fake_environment(d, 'import time, subprocess, sys\nsubprocess.Popen([sys.executable,"-c","import time; time.sleep(30)"])\ntime.sleep(30)\n')
            started = time.monotonic()
            with patch.dict(os.environ, env):
                with self.assertRaises(ApiError): Kube('test', 'test', timeout=.15).run(['get', 'pods'])
            self.assertLess(time.monotonic() - started, 3)

    def test_one_shot_api_failure_is_not_an_empty_success(self):
        script = Path(__file__).resolve().parents[1]/'scripts/live_status.py'
        with tempfile.TemporaryDirectory() as d:
            env = self.fake_environment(d, 'import sys\nprint("authentication unavailable",file=sys.stderr)\nsys.exit(1)\n')
            output = Path(d)/'output'
            result = subprocess.run([sys.executable, str(script), '--context', 'test', '--namespace', 'test',
                                     '--selector', 'app=test', '--output', str(output), '--once'],
                                    env=env, text=True, capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2, result.stderr)
            view = json.loads((output/'snapshot.json').read_text())
            self.assertTrue(view['warnings']); self.assertTrue(view['sections']['pods']['stale'])

    def test_legacy_failed_create_preserves_job_without_retry(self):
        script = Path(__file__).resolve().parents[1]/'examples/run.sh'
        with tempfile.TemporaryDirectory() as d:
            root = Path(d); build = root/'designs/nangate45/example/BUILD.bazel'
            build.parent.mkdir(parents=True); build.write_text('hightide_design(\n name = "example",\n)\n')
            calls = root/'calls.jsonl'
            env = self.fake_environment(d, 'import sys,json,pathlib\nwith pathlib.Path(' + repr(str(calls)) + ').open("a") as f: f.write(json.dumps(sys.argv[1:])+"\\n")\nprint("AlreadyExists",file=sys.stderr)\nsys.exit(1)\n')
            env.update(HIGHTIDE_REPO=d, USER_CRUZID='alice', NRP_NAMESPACE='test', NRP_CONTEXT='test')
            result = subprocess.run(['bash', str(script), '--cpu', '4', '--mem', '6Gi'], env=env,
                                    capture_output=True, text=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            commands = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertEqual(len(commands), 1); self.assertIn('create', commands[0]); self.assertNotIn('delete', commands[0])


if __name__ == '__main__':
    unittest.main()
