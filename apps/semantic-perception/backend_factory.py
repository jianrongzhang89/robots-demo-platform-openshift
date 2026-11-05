"""Explicit backend selection; remote initialization never imports CUDA code."""
import json
from pathlib import Path


def create_backend(kind, *, checkpoint, prompt, threshold, endpoint='', ca='', cert='', key='', identity=''):
    if kind == 'local':
        from PIL import Image
        from sam3_backend import LocalSam3Backend, Sam3ModelRunner
        runner = Sam3ModelRunner(checkpoint, threshold)
        runner.infer(Image.new('RGB', (640, 480)), prompt, threshold)
        return LocalSam3Backend(runner)
    if kind == 'http':
        from http_backend import HttpSam3Backend
        expected = json.loads(Path(identity).read_text())
        if expected['prompt'] != prompt or expected['threshold'] != threshold:
            raise ValueError('node prompt policy differs from pinned deployment')
        return HttpSam3Backend(endpoint, ca, cert, key, expected)
    raise ValueError('backend must be explicitly local or http')
