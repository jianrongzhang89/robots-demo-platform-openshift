#!/usr/bin/env python3
"""G2 live ROS replay. Frozen RGB + synthetic aligned depth, private DDS only.

Run inside the CPU adapter pod after copying the G1 frozen directory to /tmp.
All assertions are gate failures; results always retain a failure reason.
"""
import argparse
import base64
import glob
import hashlib
import importlib.util
from io import BytesIO
import json
from pathlib import Path
import time
import traceback

import numpy as np
from PIL import Image as PILImage
import rclpy
from rclpy.node import Node
from sensor_msgs.msg import CompressedImage, CameraInfo, Image, PointCloud2
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
from inference_contract import decode_response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--frozen', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = {'status': 'FAIL', 'scope': 'frozen RGB, synthetic one-metre depth; no scene geometry or navigation claim', 'frames': []}
    rclpy.init(); node = Node('g2_live_replay'); masks = []; clouds = []; statuses = []
    node.create_subscription(Image, '/g2/robot_1/semantic/mask', masks.append, 10)
    node.create_subscription(PointCloud2, '/g2/robot_1/semantic/points', clouds.append, 10)
    node.create_subscription(String, '/g2/robot_1/semantic/status', lambda m: statuses.append(json.loads(m.data)), 10)
    pubs = {name: node.create_publisher(typ, '/g2/robot_1/camera/' + topic, 10) for name, typ, topic in (
        ('rgb', CompressedImage, 'color/image_compressed'), ('depth', CompressedImage, 'depth/image_compressed'),
        ('info', CameraInfo, 'color/camera_info'), ('trace', String, 'capture_trace'), ('compression', String, 'compression_trace'))}
    clock = node.create_publisher(Clock, '/clock', 10)
    def spin(seconds):
        end = time.monotonic() + seconds
        while time.monotonic() < end: rclpy.spin_once(node, timeout_sec=.005)
    def until(predicate, seconds=3):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            rclpy.spin_once(node, timeout_sec=.005)
            if predicate(): return
        raise AssertionError('Timed out waiting for ROS condition; latest status: ' + str(statuses[-1:]))
    try:
        until(lambda: all(p.get_subscription_count() for p in pubs.values()) and statuses, 10)
        assert not statuses[-1]['ready'] and statuses[-1]['deployment_identity']
        assert not masks and not clouds
        result['initial_status'] = statuses[-1]
        result['cpu_only'] = {'torch_installed': importlib.util.find_spec('torch') is not None,
                              'nvidia_devices': glob.glob('/dev/nvidia*'), 'models_mounted': Path('/models').exists()}
        assert not any(result['cpu_only'].values())
        manifest = json.loads((args.frozen / 'manifest.json').read_text())
        for seq, item in enumerate(manifest['frames'], 1):
            request_bytes = (args.frozen / item['request']).read_bytes()
            response_bytes = (args.frozen / item['local_response']).read_bytes()
            assert hashlib.sha256(request_bytes).hexdigest() == item['request_sha256']
            assert hashlib.sha256(response_bytes).hexdigest() == item['local_response_sha256']
            request, response = json.loads(request_bytes), json.loads(response_bytes)
            expected, _ = decode_response(request, response)
            w, h = request['width'], request['height']
            rgb = CompressedImage(); rgb.format = 'png'
            b = BytesIO(); PILImage.frombytes('RGB', (w, h), base64.b64decode(request['image'])).save(b, format='PNG'); rgb.data = b.getvalue()
            depth = CompressedImage(); depth.format = 'png'; b = BytesIO()
            PILImage.fromarray(np.full((h, w), 1000, dtype=np.uint16)).save(b, format='PNG'); depth.data = b.getvalue()
            ns = seq * 1_000_000_000; tick = Clock(); tick.clock.sec = seq
            rgb.header.stamp = tick.clock; rgb.header.frame_id = request['capture']['frame_id']; depth.header = rgb.header
            info = CameraInfo(); info.header = rgb.header; info.width = w; info.height = h; info.k = [400., 0., w/2, 0., 400., h/2, 0., 0., 1.]
            # Settle a clock rollback before capturing the next fresh frame.
            # This also permits a later replay run without reusing pre-reset data.
            clock.publish(tick); spin(.05)
            before = len(masks); wall = time.time_ns()
            trace = {'schema': 'semantic-capture/v1', 'source_epoch': 'g2-live-frozen-rgb', 'sequence': seq,
                     'stamp_ns': ns, 'capture_wall_ns': wall, 'rendered_wall_ns': wall, 'source_publish_wall_ns': wall,
                     'render_duration_ns': 0, 'source_duration_ns': 0}
            pubs['trace'].publish(String(data=json.dumps(trace)))
            pubs['compression'].publish(String(data=json.dumps({'schema': 'semantic-compression/v1', 'stamp_ns': ns})))
            for key, msg in [('info', info), ('depth', depth), ('rgb', rgb)]: pubs[key].publish(msg)
            until(lambda: len(masks) == before + 1 and len(clouds) == before + 1)
            received_ms = (time.time_ns() - wall) / 1e6
            m, c = masks[-1], clouds[-1]
            assert m.header == rgb.header and c.header == rgb.header
            assert (m.width, m.height, c.width, c.height) == (w, h, w, h)
            observed = np.frombuffer(bytes(m.data), dtype=np.uint8).reshape(h, w)
            assert np.array_equal(observed, expected), 'union mask differs from G1 frozen result'
            points = np.frombuffer(bytes(c.data), dtype='<f4').reshape(h, w, 3)
            assert np.all(points[:, :, 2] == 1.)
            rows, cols = np.indices((h, w))
            assert np.allclose(points[:, :, 0], (cols-w/2)/400.)
            assert np.allclose(points[:, :, 1], (rows-h/2)/400.)
            until(lambda: statuses[-1]['ready'] and statuses[-1]['last_result']['capture']['stamp_ns'] == ns, .5)
            result['frames'].append({'case': item['case'], 'mask_sha256': hashlib.sha256(bytes(m.data)).hexdigest(),
                                     'mask_pixels': int(np.count_nonzero(observed)), 'exact_parity': True,
                                     'original_headers': True, 'organized_depth_alignment': True,
                                     'observer_latency_ms': received_ms, 'status': statuses[-1]})
            spin(.6); assert not statuses[-1]['ready']; assert len(masks) == before + 1
        result['final_status'] = statuses[-1]
        result['ros_nodes'] = sorted(node.get_node_names())
        result['ros_topics'] = sorted(name for name, types in node.get_topic_names_and_types())
        assert set(result['ros_nodes']) == {'sam3_semantic_inference', 'g2_live_replay'}
        assert all(t in ('/clock', '/parameter_events', '/rosout') or t.startswith('/g2/robot_1/') for t in result['ros_topics'])
        result['status'] = 'PASS'
    except Exception:
        result['error'] = traceback.format_exc()
        raise
    finally:
        args.output.write_text(json.dumps(result, indent=2) + '\n')
        node.destroy_node(); rclpy.shutdown()

if __name__ == '__main__': main()
