"""A replay must preserve the recorded sampling convention, not guess its sign."""
import importlib.util
from pathlib import Path
import unittest
import numpy as np

spec=importlib.util.spec_from_file_location('jitter_capture_replay',Path(__file__).with_name('dlss_sequence_test.py'))
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)


class CaptureJitter(unittest.TestCase):
    def test_tagged_compensation_is_not_negated_again(self):
        entry={'jitter':(-.25,.125),'jitter_semantics':'ngx-compensation'}
        self.assertEqual(m.capture_jitter(entry,{},{}),(-.25,.125))
        self.assertEqual(m.capture_jitter({}, {'jitter':np.array([-.25,.125])},
                                        {'jitter_semantics':'ngx-compensation'}),(-.25,.125))

    def test_legacy_ray_displacement_requires_explicit_conversion(self):
        data={'jitter':np.array([.25,-.125])}
        before=data['jitter'].copy()
        with self.assertRaisesRegex(ValueError,'explicit jitter semantics'):
            m.capture_jitter({},data,{})
        compensation=m.capture_jitter({},data,{},'ray-displacement')
        np.testing.assert_array_equal(np.array([8.5,17.5])+data['jitter']+compensation,[8.5,17.5])
        np.testing.assert_array_equal(data['jitter'],before)

    def test_unknown_or_invalid_metadata_is_not_silently_reinterpreted(self):
        for value in [[.6,0.],[float('nan'),0.],[0.]]:
            with self.assertRaises(ValueError):
                m.capture_jitter({'jitter':value,'jitter_semantics':'ngx-compensation'},{},{})
        with self.assertRaises(ValueError):
            m.capture_jitter({'jitter':(0.,0.),'jitter_semantics':'unspecified'},{},{},'ray-displacement')


if __name__=='__main__':unittest.main(verbosity=2)
