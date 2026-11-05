import time
import unittest
import numpy as np
from g3_cloud_validation import valid_cloud_values


def original(points):
    finite=np.isfinite(points).all(axis=1)
    return bool(np.all(finite | np.isnan(points).all(axis=1))) and bool(np.all((points[finite,2]>=.15)&(points[finite,2]<=5)))

class ValidationTests(unittest.TestCase):
    def test_finite_nan_inf_and_range_combinations(self):
        from itertools import product
        values=[-float('inf'),-.1,0,.15,1,5,5.1,float('inf'),float('nan')]
        for row in product(values,repeat=3):
            p=np.asarray([row],dtype=np.float32)
            self.assertEqual(valid_cloud_values(p),original(p),row)
    def test_random_full_clouds_match(self):
        rng=np.random.default_rng(2031)
        for mode in range(10):
            p=rng.uniform(-5,5,(480*640,3)).astype(np.float32);p[:,2]=rng.uniform(.15,5,480*640)
            p[::3]=np.nan
            if mode: p[mode,mode%3]=[np.nan,np.inf,-np.inf,-.5,6][mode%5]
            self.assertEqual(valid_cloud_values(p),original(p))

if __name__=='__main__':
    result=unittest.main(exit=False).result
    if not result.wasSuccessful():raise SystemExit(1)
    p=np.ones((480*640,3),dtype=np.float32);p[::3]=np.nan
    for fn in (original,valid_cloud_values):
        start=time.monotonic()
        for _ in range(100):assert fn(p)
        print(fn.__name__,(time.monotonic()-start)*10,'ms/frame')
