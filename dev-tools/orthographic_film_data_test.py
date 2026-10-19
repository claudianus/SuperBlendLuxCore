"""Depth/position consistency oracle for orthographic_dof_render_test.py.

Its camera starts at z=cliphither and points along +Z. Every aperture ray
has dz in [1/sqrt(1+(radius/focal)^2), 1]. Thus POSITION.z and DEPTH must
obey an interval independently of which lens sample wins the film minimum.
This is a fixture-specific consistency gate, not a general projection API.
"""
import argparse
import json
from pathlib import Path
import numpy as np

p=argparse.ArgumentParser();p.add_argument('npz',type=Path);p.add_argument('--out',type=Path,required=True);p.add_argument('--observe',action='store_true');a=p.parse_args()
with np.load(a.npz,allow_pickle=False) as image:
 position=image['position'];depth=image['depth'][:,:,0]
 # The fixture uses radius .12, focal distance 10, hither .001.
 delta_z=position[:,:,2].astype(np.float64)-.001
 dz_min=1/np.sqrt(1+(.12/10)**2)
 bad=(~np.isfinite(depth))|(~np.isfinite(position).all(axis=2))|(depth<delta_z-2e-5)|(depth>delta_z/dz_min+2e-5)
 coords=np.argwhere(bad)
 report={'passed':len(coords)==0,'pixels':int(depth.size),'inconsistent_pixels':len(coords),
         'source':str(a.npz),'scope':__doc__,'dz_min':float(dz_min),'absolute_rounding_tolerance':2e-5,
         'examples':[{'y_x':q.tolist(),'depth':float(depth[tuple(q)]),'position':position[tuple(q)].tolist()} for q in coords[:8]],
         'observe_only':a.observe}
 a.out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps({k:v for k,v in report.items() if k not in ['examples','scope']}),flush=True)
 if not a.observe:assert report['passed'],'Depth and position select different primary samples'
