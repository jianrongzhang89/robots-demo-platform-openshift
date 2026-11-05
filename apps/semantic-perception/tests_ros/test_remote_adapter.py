"""Actual ROS callbacks/publications with real mTLS and injected remote replies.

Private synthetic RGB-D fixtures. No simulator, navigation or recognition claim.
"""
import copy
from io import BytesIO
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest

import numpy as np
from PIL import Image as PILImage
import rclpy
from rclpy.executors import SingleThreadedExecutor
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import CompressedImage, CameraInfo, Image, PointCloud2
from std_msgs.msg import String
from rosgraph_msgs.msg import Clock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tests'))
from http_fixture import Fixture
from sam3_ros_node import Sam3Runtime


class RemoteAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        os.environ['SEMANTIC_REQUIRE_CAPTURE_TRACE']='1';os.environ.pop('SEMANTIC_STATUS_FILE',None)
        cls.fixture=Fixture();f=cls.fixture
        args=['--ros-args']
        for key,value in {'backend':'http','checkpoint':'/no-checkpoint-allowed','input_prefix':'/g2/test/camera',
            'output_prefix':'/g2/test/semantic','endpoint':f.endpoint,'tls_ca':str(f.root/'ca.crt'),
            'tls_cert':str(f.root/'client.crt'),'tls_key':str(f.root/'client.key'),
            'deployment_identity':str(f.root/'identity.json')}.items():args+=['-p',f'{key}:={value}']
        rclpy.init(args=args)
    @classmethod
    def tearDownClass(cls):rclpy.shutdown();cls.fixture.close()
    def setUp(self):
        f=self.fixture;f.mode='ok';f.entered.clear();f.last=None;f.delay=.15
        self.adapter=Sam3Runtime();self.probe=Node('g2_test_probe');self.executor=SingleThreadedExecutor()
        self.executor.add_node(self.adapter);self.executor.add_node(self.probe)
        self.masks=[];self.clouds=[];self.statuses=[]
        self.probe.create_subscription(Image,'/g2/test/semantic/mask',self.masks.append,10)
        self.probe.create_subscription(PointCloud2,'/g2/test/semantic/points',self.clouds.append,10)
        self.probe.create_subscription(String,'/g2/test/semantic/status',lambda m:self.statuses.append(json.loads(m.data)),10)
        self.pubs={name:self.probe.create_publisher(typ,'/g2/test/camera/'+topic,10) for name,typ,topic in (
            ('rgb',CompressedImage,'color/image_compressed'),('depth',CompressedImage,'depth/image_compressed'),
            ('info',CameraInfo,'color/camera_info'),('trace',String,'capture_trace'),('compression',String,'compression_trace'))}
        self.clock=self.probe.create_publisher(Clock,'/clock',10)
        self.until(lambda:self.adapter.model_loaded,3);self.spin(.1);self.sequence=0
    def tearDown(self):
        self.executor.remove_node(self.adapter);self.executor.remove_node(self.probe)
        self.adapter.destroy_node();self.probe.destroy_node();self.executor.shutdown()
    def spin(self,seconds):
        end=time.monotonic()+seconds
        while time.monotonic()<end:self.executor.spin_once(timeout_sec=.005)
    def until(self,predicate,timeout=2):
        end=time.monotonic()+timeout
        while time.monotonic()<end:
            self.executor.spin_once(timeout_sec=.005)
            if predicate():return
        self.fail('condition did not become true')
    def send(self,seq=None):
        self.sequence=self.sequence+1 if seq is None else seq;ns=self.sequence*100_000_000
        clock=Clock();clock.clock.sec=ns//10**9;clock.clock.nanosec=ns%10**9;self.clock.publish(clock)
        wall=time.time_ns();trace={'schema':'semantic-capture/v1','source_epoch':'g2-source','sequence':self.sequence,
            'stamp_ns':ns,'capture_wall_ns':wall,'rendered_wall_ns':wall,'source_publish_wall_ns':wall,
            'render_duration_ns':0,'source_duration_ns':0}
        self.pubs['trace'].publish(String(data=json.dumps(trace)))
        self.pubs['compression'].publish(String(data=json.dumps({'schema':'semantic-compression/v1','stamp_ns':ns})))
        rgb=CompressedImage();rgb.header.stamp=clock.clock;rgb.header.frame_id='optical';rgb.format='png'
        b=BytesIO();PILImage.new('RGB',(16,12),(200,0,0)).save(b,format='PNG');rgb.data=b.getvalue()
        depth=CompressedImage();depth.header=rgb.header;depth.format='png';b=BytesIO();PILImage.fromarray(np.full((12,16),1000,dtype=np.uint16)).save(b,format='PNG');depth.data=b.getvalue()
        info=CameraInfo();info.header=rgb.header;info.width=16;info.height=12;info.k=[10.,0.,8.,0.,10.,6.,0.,0.,1.]
        for key,msg in [('info',info),('depth',depth),('rgb',rgb)]:self.pubs[key].publish(msg)
        return ns
    def test_metadata_never_grants_readiness_and_real_pair_keeps_header(self):
        self.assertTrue(self.adapter.model_loaded);self.assertFalse(self.adapter.ready);self.assertFalse(self.masks)
        ns=self.send();self.until(lambda:len(self.masks)==1 and len(self.clouds)==1)
        self.assertTrue(self.adapter.ready);m=self.masks[0];c=self.clouds[0]
        self.assertEqual(m.header.stamp.sec*10**9+m.header.stamp.nanosec,ns);self.assertEqual(m.header,c.header)
        self.assertEqual((m.width,m.height,c.width,c.height),(16,12,16,12));self.assertEqual(set(m.data),{2})
        xyz=np.frombuffer(bytes(c.data),dtype='<f4').reshape(12,16,3);self.assertAlmostEqual(float(xyz[6,8,2]),1.)
        self.spin(.55);self.assertFalse(self.adapter.ready)
    def test_remote_mode_has_no_cuda_initialization(self):
        self.assertNotIn('torch',sys.modules);self.assertFalse(Path('/no-checkpoint-allowed').exists())
        self.assertEqual(self.adapter.backend_kind,'http')
    def test_errors_hangs_and_network_loss_publish_nothing(self):
        for mode in (401,403,429,503,'drop','hang','wrong_robot','wrong_sequence'):
            with self.subTest(mode=mode):
                self.fixture.mode=mode;before=len(self.masks);self.send();self.spin(.7)
                self.assertEqual(len(self.masks),before);self.assertFalse(self.adapter.ready)
                self.assertEqual(len(self.adapter.guard.pending),0)
    def test_reset_during_delayed_reply_never_publishes(self):
        self.fixture.mode='delay';self.fixture.delay=.2;self.send()
        self.until(lambda:self.fixture.entered.is_set());old=self.adapter.epoch
        reset=Clock();self.adapter.on_clock(reset)
        self.assertNotEqual(self.adapter.epoch,old);self.spin(.35);self.assertFalse(self.masks);self.assertFalse(self.adapter.ready)
    def test_missing_retained_depth_never_publishes(self):
        self.fixture.mode='delay';self.send();self.until(lambda:self.fixture.entered.is_set())
        with self.adapter.lock:self.adapter.guard.pending.clear()
        self.spin(.3);self.assertFalse(self.masks);self.assertFalse(self.adapter.ready)
    def test_replayed_reply_and_duplicate_input_do_not_republish(self):
        self.send();self.until(lambda:len(self.masks)==1);self.send(seq=1);self.spin(.15);self.assertEqual(len(self.masks),1)
        self.fixture.mode='replay';self.send(seq=2);self.spin(.25);self.assertEqual(len(self.masks),1);self.assertFalse(self.adapter.ready)
    def test_late_reply_is_not_a_fresh_heartbeat(self):
        self.fixture.mode='delay';self.fixture.delay=.7;self.send();self.spin(.8)
        self.assertFalse(self.masks);self.assertFalse(self.adapter.ready);self.assertIsNone(self.adapter.valid_result_wall)
    def test_identity_mismatch_latches_not_ready(self):
        self.fixture.mode='wrong_deployment';self.send();self.spin(.2);self.assertFalse(self.masks)
        self.fixture.mode='ok';self.send();self.spin(.2);self.assertFalse(self.masks);self.assertTrue(self.adapter.backend.identity_fault)
    def test_input_and_inflight_buffers_bounded(self):
        self.fixture.mode='hang'
        for _ in range(30):self.send();self.spin(.005)
        with self.adapter.lock:
            self.assertLessEqual(len(self.adapter.work_queue),1);self.assertLessEqual(len(self.adapter.guard.pending),1)
            for q in (self.adapter.rgb_queue,self.adapter.depth_queue,self.adapter.info_queue):self.assertLessEqual(len(q),20)
        self.assertLessEqual(self.adapter.backend.in_flight,1)
    def test_configuration_changes_require_restart(self):
        r=self.adapter.set_parameters([Parameter('backend',value='local')]);self.assertFalse(r[0].successful)
        self.assertEqual(self.adapter.backend_kind,'http')
