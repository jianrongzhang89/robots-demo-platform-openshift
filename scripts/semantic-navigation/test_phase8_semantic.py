"""Phase 8 must inherit the fixed Phase 6 profile and prove RMF completion."""
import ast
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
import uuid
from unittest.mock import Mock, patch

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import phase8_topology as topology
import render_phase6_demo_d2 as phase6


class Phase8SemanticTests(unittest.TestCase):
    def test_stale_source_pod_cannot_override_accepted_navigation(self):
        source = phase6.render_documents(candidate_pods=True)[2]
        next(c for c in source['spec']['containers'] if c['name'] == 'nav2')['image'] = 'obsolete'
        pod = topology.phase8_pod(source, topology.DEMO_START)
        canonical = phase6.render_documents(candidate_pods=True)[2]
        for name in ('nav2', 'odom-tf', 'motion-output-bridge'):
            container = next(c for c in pod['spec']['containers'] if c['name'] == name)
            expected = next(c for c in canonical['spec']['containers'] if c['name'] == name)
            for key in ('image', 'command', 'args', 'env'):
                self.assertEqual(container.get(key), expected.get(key))
        volume = next(v for v in pod['spec']['volumes'] if v['name'] == 'nav2-config')
        self.assertEqual(volume['configMap']['name'], topology.NAV2_CONFIG_MAP)

    def test_phase8_parameters_match_accepted_semantic_profile(self):
        config = topology.accepted_nav2_config()
        expected = phase6.render_documents(candidate_pods=True)[0]
        self.assertEqual(config['data'], expected['data'])
        params = yaml.safe_load(config['data']['phase6-demo-nav2-on.yaml'])
        semantic = params['global_costmap']['global_costmap']['ros__parameters']['semantic_layer']
        self.assertTrue(semantic['enabled'])
        self.assertEqual(semantic['static_obstacle_memory'], 300.0)

    def test_graph_uses_checked_phase6_start_and_goal(self):
        graph = yaml.safe_load(topology.generated_graph(topology.DEMO_START))
        vertices = graph['levels']['L1']['vertices']
        self.assertEqual(vertices[0][:2], [15.402, -31.594])
        self.assertEqual(vertices[1][:2], [19.5, -31.594])

    def test_saved_pod_is_not_modified_by_cleaning(self):
        pod = {'metadata': {'name': 'source', 'uid': 'uid'}, 'status': {'phase': 'Running'}}
        clean = topology.clean_pod(pod)
        self.assertIn('status', pod)
        self.assertNotIn('status', clean)

    def test_bridge_recovery_preserves_pinned_image_and_waits_for_new_container(self):
        before = {'spec': {'containers': [{'name': 'motion-output-bridge',
                   'image': 'eclipse/zenoh-bridge-ros2dds@sha256:abc'}]},
                  'status': {'containerStatuses': [{'name': 'motion-output-bridge',
                   'containerID': 'old', 'ready': True}]}}
        after = json.loads(json.dumps(before))
        after['status']['containerStatuses'][0]['containerID'] = 'new'
        responses = [SimpleNamespace(stdout=json.dumps(before)), SimpleNamespace(stdout=''),
                     SimpleNamespace(stdout=json.dumps(after))]
        with tempfile.TemporaryDirectory() as folder, patch.object(topology, 'oc', side_effect=responses) as oc:
            topology.recover_motion_bridge(Path(folder))
            payload = json.loads(oc.call_args_list[1].args[-1])
            self.assertEqual(payload['spec']['containers'][0]['image'],
                             'eclipse/zenoh-bridge-ros2dds:latest@sha256:abc')
            evidence = json.loads((Path(folder)/'motion-bridge-recovery.json').read_text())
            self.assertEqual(evidence['after']['containerID'], 'new')

    @staticmethod
    def method(name):
        source = topology.SEMANTIC_TRIAL
        tree = ast.parse(source.read_text())
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'RMFTrial')
        fn = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == name)
        import math
        namespace = {'math': math, 'SimpleNamespace': SimpleNamespace, 'uuid': uuid}
        task_tree = ast.parse(topology.TASK_CLIENT.read_text())
        cancel = next(n for n in task_tree.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'cancel_request')
        exec(compile(ast.Module(body=[cancel], type_ignores=[]), str(topology.TASK_CLIENT), 'exec'), namespace)
        exec(compile(ast.Module(body=[fn], type_ignores=[]), str(source), 'exec'), namespace)
        return namespace[name]

    def state(self, statuses, idle=True, at_goal=True):
        return SimpleNamespace(nav2_goals=statuses, rmf_result=Mock(done=lambda: False),
            cancel_id=None, fleet_idle=idle, cancel_rmf=Mock(),
            args=SimpleNamespace(goal_x=19.5, goal_y=-31.594),
            latest_truth=SimpleNamespace(pose=SimpleNamespace(pose=SimpleNamespace(
                position=SimpleNamespace(x=19.5 if at_goal else 15.402, y=-31.594)))))

    def test_completion_needs_nav2_success_rmf_idle_and_actual_destination(self):
        complete = self.method('maybe_complete')
        for statuses, idle, at_goal in [({'goal': 2}, True, True),
                ({'goal': 4}, False, True), ({'start_goal': 4}, True, False),
                ({'old': 4, 'active': 2}, True, True)]:
            state = self.state(statuses, idle, at_goal)
            complete(state)
            state.rmf_result.set_result.assert_not_called()
        state = self.state({'goal': 4})
        complete(state)
        self.assertEqual(state.rmf_result.set_result.call_args.args[0].status, 4)

    def test_failed_nav2_goal_cancels_rmf_instead_of_completing_activity(self):
        state = self.state({'goal': 6})
        self.method('maybe_complete')(state)
        state.cancel_rmf.assert_called_once()
        self.assertEqual(state.rmf_result.set_result.call_args.args[0].status, 6)

    def test_old_statuses_cannot_complete_a_new_rmf_task(self):
        state = self.state({})
        state.dispatching = False
        state.baseline_goals = set()
        state.maybe_complete = Mock()
        status = SimpleNamespace(status=4, goal_info=SimpleNamespace(
            goal_id=SimpleNamespace(uuid=[1]*16)))
        update = self.method('nav_status')
        update(state, SimpleNamespace(status_list=[status]))
        state.dispatching = True
        update(state, SimpleNamespace(status_list=[status]))
        self.assertEqual(state.nav2_goals, {})

    def test_safety_cancel_uses_correlated_rmf_api_once(self):
        state = SimpleNamespace(task_id='compose.dispatch-demo', cancel_id=None,
                                publish_request=Mock(), cancel_future=object())
        cancel = self.method('cancel_rmf')
        self.assertIs(cancel(state), state.cancel_future)
        cancel(state)
        state.publish_request.assert_called_once()
        request_id, body = state.publish_request.call_args.args
        self.assertEqual(request_id, state.cancel_id)
        self.assertEqual(body['type'], 'cancel_task_request')
        self.assertEqual(body['task_id'], state.task_id)

    def test_shared_runner_keeps_native_phase6_dispatch(self):
        source = topology.ROOT/'scripts/semantic-navigation/run_phase6_demo_d2_trial.py'
        cls = next(n for n in ast.parse(source.read_text()).body if isinstance(n, ast.ClassDef))
        method = next(n for n in cls.body if isinstance(n, ast.FunctionDef)
                      and n.name == 'dispatch_navigation')
        namespace = {'rclpy': SimpleNamespace(spin_until_future_complete=Mock())}
        exec(compile(ast.Module(body=[method], type_ignores=[]), str(source), 'exec'), namespace)
        handle = SimpleNamespace(accepted=True)
        future = SimpleNamespace(result=lambda: handle)
        state = SimpleNamespace(node=object(), action=Mock(send_goal_async=Mock(return_value=future)))
        goal = object()
        self.assertIs(namespace['dispatch_navigation'](state, goal), handle)
        state.action.send_goal_async.assert_called_once_with(goal)
        handle.accepted = False
        with self.assertRaises(RuntimeError):
            namespace['dispatch_navigation'](state, goal)


if __name__ == '__main__':
    unittest.main()
