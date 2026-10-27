import importlib.util,unittest
from pathlib import Path
import numpy as np
spec=importlib.util.spec_from_file_location('detector',Path(__file__).resolve().parents[1]/'scripts/detect-body.py')
m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
class DetectionTests(unittest.TestCase):
 def test_overlap_same_class_suppressed_but_other_class_kept(self):
  boxes=np.array([[0,0,1,1],[.01,.01,.99,.99],[0,0,1,1]])
  self.assertEqual(m.nms(boxes,np.array([.9,.8,.7]),np.array([0,0,1])),[0,2])
 def test_non_overlapping_objects_and_limit(self):
  boxes=np.array([[0,0,.2,.2],[.5,.5,1,1]])
  self.assertEqual(m.nms(boxes,np.array([.8,.9]),np.array([1,1])),[1,0])
  self.assertEqual(m.nms(boxes,np.array([.8,.9]),np.array([1,1]),limit=1),[1])
 def test_empty_and_labels(self):
  self.assertEqual(m.nms(np.empty((0,4)),np.array([]),np.array([])),[])
  self.assertEqual(len(m.LABELS),80)
