"""Replay actual renderer-owned frame captures through the optional CUDA backend.

Reports quality measurements without asserting a speedup or promoting a default.
The capture manifest must describe the material/sample/motion scope separately.
"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('slc_dlss_backend', ROOT/'engine/dlss.py')
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)
PLANES = ('color', 'depth', 'diffuse', 'specular', 'normal_roughness', 'motion', 'specular_motion')


def digest(planes):
    return {name: hashlib.sha256(planes[name].tobytes()).hexdigest() for name in PLANES}


def metrics(image, reference):
    a, b = image[:, :, :3].astype(np.float64), reference[:, :, :3].astype(np.float64)
    return {'mse_linear': float(np.mean((a-b)**2)),
            'mse_log1p': float(np.mean((np.log1p(np.maximum(a, 0))-np.log1p(np.maximum(b, 0)))**2)),
            'rgb_mean': a.mean(axis=(0, 1)).tolist(),
            'relative_mean_delta': (a.mean(axis=(0, 1))/b.mean(axis=(0, 1))-1).tolist(),
            'negative_rgb_fraction': float(np.mean(a < 0))}


def bilinear(image, width, height):
    """Explicit display baseline for low-resolution raw/averaged SR inputs."""
    h, w, _ = image.shape
    x = np.clip((np.arange(width)+.5)*w/width-.5, 0, w-1)
    y = np.clip((np.arange(height)+.5)*h/height-.5, 0, h-1)
    ix, iy = np.floor(x).astype(int), np.floor(y).astype(int)
    fx, fy = (x-ix).astype(np.float32), (y-iy).astype(np.float32)
    rows = image[:, ix]*(1-fx)[None, :, None]+image[:, np.minimum(ix+1, w-1)]*fx[None, :, None]
    return rows[iy]*(1-fy)[:, None, None]+rows[np.minimum(iy+1, h-1)]*fy[:, None, None]


def capture_jitter_space(entry, capture, legacy_space=None):
    """Never guess the sign of an untagged historical capture."""
    space = entry.get('jitter_semantics', capture.get('jitter_semantics', legacy_space))
    if space == 'NGX compensation; negative native ray displacement':
        space = 'ngx-compensation'
    if space not in ('ngx-compensation', 'ray-displacement'):
        raise ValueError('Capture needs explicit jitter semantics; use --legacy-jitter-space for untagged historical data')
    return space


def capture_jitter(entry, data, capture, legacy_space=None):
    space = capture_jitter_space(entry, capture, legacy_space)
    value = np.asarray(entry['jitter'] if 'jitter' in entry else data['jitter'], dtype=np.float64)
    if value.shape != (2,) or not np.isfinite(value).all() or np.any(np.abs(value) > .5):
        raise ValueError('Invalid captured subpixel jitter')
    if space == 'ray-displacement':
        value = -value
    return tuple(float(component) for component in value)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('capture', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--scale', type=int, choices=(1, 2, 3, 4), default=1)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--save-checkpoints', action='store_true')
    parser.add_argument('--legacy-jitter-space', choices=('ray-displacement', 'ngx-compensation'),
                        help='Required for historical captures without declared jitter semantics')
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    capture = json.loads((args.capture/'capture.json').read_text())
    # Reject ambiguous historical metadata before allocating any GPU backend.
    for entry in capture['frames']:
        capture_jitter_space(entry, capture, args.legacy_jitter_space)
    average = None
    average_count = 0
    previous_serial = None
    records = {'capture': capture, 'frames': [], 'scale': args.scale, 'performance_comparison': False}
    library = Path(os.environ['SLC_DLSS_TEST_LIBRARY'])
    records['backend_sha256'] = hashlib.file_digest(library.open('rb'), 'sha256').hexdigest()
    with m.CUDADLSS(os.environ['SLC_DLSS_TEST_RUNTIME'], os.environ['SLC_DLSS_TEST_CACHE'], library=library) as backend:
        for entry in capture['frames']:
            with np.load(args.capture/entry['file'], allow_pickle=False) as data:
                planes = {name: data[name] for name in PLANES}
                before = digest(planes)
                assert before['color'] == entry['raw_sha256']
                frame_id = entry.get('frame_id', entry.get('id'))
                frame = m.DLSSFrame(**planes, frame_id=frame_id, scene_serial=entry.get('scene_serial', 1),
                                    jitter=capture_jitter(entry, data, capture, args.legacy_jitter_space), independent_samples=True,
                                    reset=entry.get('reset', entry == capture['frames'][0]),
                                    output_size=(planes['color'].shape[1]*args.scale, planes['color'].shape[0]*args.scale))
                result = backend.process(frame)
                assert np.isfinite(result).all()
                if args.scale == 1:
                    assert np.array_equal(result[:, :, 3], frame.color[:, :, 3])
                assert digest(planes) == before
                # Average only a stationary view with a common shape/scene.
                # Mixing pre-edit pixels would turn resize into an exception
                # and create a ghosted, invalid current-camera baseline.
                if (average is None or average.shape != frame.color.shape or frame.reset or
                        frame.scene_serial != previous_serial or np.any(frame.motion != 0)):
                    average = frame.color.astype(np.float64)
                    average_count = 1
                else:
                    average += frame.color
                    average_count += 1
                previous_serial = frame.scene_serial
                records['frames'].append({'id': frame_id, 'scene_serial': frame.scene_serial,
                                           'reset': frame.reset, 'raw_unchanged': True,
                                           'alpha_exact': True if args.scale == 1 else None,
                                           'alpha_mode': 'raw exact' if args.scale == 1 else 'SDK upscaled',
                                           'stats': backend.stats()})
                if args.save_checkpoints:
                    np.save(args.out/f'dlss-frame-{frame_id:03}.npy', result)
                    np.save(args.out/f'raw-frame-{frame_id:03}.npy', frame.color)
                print('DLSS frame', frame_id, flush=True)
        average = (average/average_count).astype(np.float32)
        records['average_stationary_frames'] = average_count
        np.save(args.out/'dlss-rgba.npy', result)
        moving = bool(capture.get('camera_orbit_degrees'))
        average_name = 'unregistered-history-average' if moving else 'matched-average'
        np.save(args.out/(average_name+'-rgba.npy'), average)
        np.save(args.out/'last-raw-rgba.npy', planes['color'])
        reference_path = args.reference or args.capture/'reference-rgba.npy'
        if reference_path.is_file():
            reference = np.load(reference_path, allow_pickle=False)
            raw_baseline, average_baseline = planes['color'], average
            if args.scale != 1:
                raw_baseline = bilinear(raw_baseline, result.shape[1], result.shape[0])
                average_baseline = bilinear(average_baseline, result.shape[1], result.shape[0])
            records['quality'] = {'dlss': metrics(result, reference),
                                  'last_raw' if args.scale == 1 else 'last_raw_bilinear': metrics(raw_baseline, reference)}
            # Averaging moving frames without reprojection is a ghosting
            # diagnostic, never a matched-SPP current-camera reference.
            if not moving:
                records['quality']['matched_average' if args.scale == 1 else 'matched_average_bilinear'] = metrics(average_baseline, reference)
            matched_path = args.capture/'last-camera-16spp-rgba.npy'
            if matched_path.is_file():
                records['quality']['last_camera_16spp'] = metrics(np.load(matched_path, allow_pickle=False), reference)
    (args.out/'result.json').write_text(json.dumps(records, indent=2)+'\n')
    print(json.dumps(records.get('quality', {}), indent=2), flush=True)


if __name__ == '__main__':
    main()
