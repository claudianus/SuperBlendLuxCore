# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software; you can redistribute it and/or
#  modify it under the terms of the GNU General Public License
#  as published by the Free Software Foundation; either version 2
#  of the License, or (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software Foundation,
#  Inc., 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301, USA.
#
# ##### END GPL LICENSE BLOCK #####
#
#  This code is based on the Blenderkit Addon
#  Homepage: https://www.blenderkit.com/
#  Sourcecode: https://github.com/blender/blender-addons/tree/master/blenderkit
#
# #####

import bpy
from . import utils


def _tag_view3d_redraw():
    """Redraw the 3D viewport if one exists. Background mode (or a
    layout without a window) has no 'WinMan'/windows — IndexError or
    KeyError here would silently kill the timer."""
    try:
        wm = bpy.data.window_managers.get('WinMan')
        if wm is None or not wm.windows:
            return
        for area in wm.windows[0].screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()
    except Exception:
        pass


def timer_update():
    '''check for running and finished downloads and react. write progressbars too.'''
    if len(utils.download_threads) == 0:
        return None

    running = 0
    for threaddata in list(utils.download_threads):
        thread, asset, tcom = threaddata

        asset_type = tcom.passargs['asset type']

        try:
            if asset_type == 'MODEL':
                assets = bpy.context.scene.superluxcoreOL.model['assets']
            elif asset_type == 'SCENE':
                assets = bpy.context.scene.superluxcoreOL.scene['assets']
            elif asset_type == 'MATERIAL':
                assets = bpy.context.scene.superluxcoreOL.material['assets']
            else:
                raise ValueError(f"Unhandled asset properties '{asset_type}'")
        except Exception:
            # RNA context can be transiently unavailable (file load,
            # scene switch) — skip this tick instead of killing the timer.
            continue

        if tcom.finished:
            thread.stop()
            for a in assets:
                if a['hash'] == asset['hash']:
                    a['downloaded'] = 100.0
                    break
            for d in tcom.passargs['downloaders']:
                # The target object may have been deleted/renamed while
                # the download ran (RNA objects resolved by name) — a
                # KeyError/IndexError here must not kill the timer.
                try:
                    if tcom.passargs['asset type'] == 'MATERIAL':
                        utils.append_material(bpy.context, asset, d['target_object'], d['target_slot'])
                    else:
                        utils.link_asset(bpy.context, asset, d['location'], d['rotation'])
                except Exception:
                    import traceback
                    traceback.print_exc()

            utils.download_threads.remove(threaddata)
            _tag_view3d_redraw()
            # Keep processing remaining downloads — returning None here
            # would unregister the timer and orphan them.
            continue
        else:
            if thread.is_alive():
                running = running + 1
            elif running < 10:
                running = running + 1
                thread.start()

        for a in assets:
            if a['hash'] == asset['hash']:
                a['downloaded'] = tcom.progress
                break

        _tag_view3d_redraw()
    return 0.5
