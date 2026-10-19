"""Lightweight real UI split/join check; no renderer or addon is started."""
import json
import os
from pathlib import Path
import traceback
import bpy

window=bpy.context.window_manager.windows[0]
area=next(a for a in window.screen.areas if a.type=='VIEW_3D')
width=area.width
record={'initial_width':width}
def done():
    try:
        record['final_width']=area.width
        assert area.width==width
        record['status']='passed'
    except Exception:record['error']=traceback.format_exc();record['status']='failed'
    Path(os.environ['SLC_RESIZE_RECEIPT']).write_text(json.dumps(record,indent=2)+'\n')
    bpy.ops.wm.quit_blender()
def join():
    try:
        record['split_width']=area.width;assert area.width<width
        other=next(a for a in window.screen.areas if a.type=='VIEW_3D' and a!=area)
        with bpy.context.temp_override(window=window,area=area):
            bpy.ops.screen.area_join(source_xy=(area.x+area.width//2,area.y+area.height//2),
                target_xy=(other.x+other.width//2,other.y+other.height//2))
        bpy.app.timers.register(done,first_interval=.5)
    except Exception:record['error']=traceback.format_exc();done()
def split():
    with bpy.context.temp_override(window=window,area=area):
        bpy.ops.screen.area_split(direction='VERTICAL',factor=.9)
    bpy.app.timers.register(join,first_interval=.5)
bpy.app.timers.register(split,first_interval=.5)
