#!/usr/bin/env python3
"""Nightmare TV: libmpv playback cost on an Intel Mac runner.

Loads the macOS slice of a libmpv-darwin release through ctypes (the same
binaries the app bundles), plays test clips with vo=null / ao=null / untimed
and measures how fast mpv gets through them. Anything below real time
(fps < clip fps) would stutter on a machine of this class.

Usage: intel_bench.py <frameworks_dir> <label> <clips_dir> <out_json>
Each case runs in a fresh process (see main) so two library versions never
share one dyld image list.
"""
import ctypes, json, os, subprocess, sys, time

CASES = [
    # name, clip, clip_fps, frames, options
    ('h264_1080i_nofilter', 'h264_1080i25.ts', 25, 500, {'hwdec': 'no'}),
    ('h264_1080i_bwdif',    'h264_1080i25.ts', 25, 500, {'hwdec': 'no', 'vf': 'lavfi=[bwdif=mode=send_frame:parity=auto:deint=all]'}),
    ('h264_1080i_yadif',    'h264_1080i25.ts', 25, 500, {'hwdec': 'no', 'vf': 'lavfi=[yadif=mode=send_frame:parity=auto:deint=all]'}),
    ('h264_1080i_deint_yes','h264_1080i25.ts', 25, 500, {'hwdec': 'no', 'deinterlace': 'yes'}),
    ('h264_1080i_vt_copy_deint', 'h264_1080i25.ts', 25, 500, {'hwdec': 'videotoolbox-copy', 'deinterlace': 'yes'}),
    ('hevc10_1080p50',      'hevc10_1080p50.mkv', 50, 500, {'hwdec': 'no'}),
    ('hevc10_2160p25',      'hevc10_2160p25.mkv', 25, 125, {'hwdec': 'no'}),
    ('hevc10_2160p25_vt',   'hevc10_2160p25.mkv', 25, 125, {'hwdec': 'videotoolbox-copy'}),
    ('h264_1080p50_atadenoise', 'h264_1080p50.ts', 50, 500, {'hwdec': 'no', 'vf': 'lavfi=[atadenoise]'}),
]

class Event(ctypes.Structure):
    _fields_ = [('event_id', ctypes.c_int), ('error', ctypes.c_int),
                ('reply_userdata', ctypes.c_uint64), ('data', ctypes.c_void_p)]

class LogMsg(ctypes.Structure):
    _fields_ = [('prefix', ctypes.c_char_p), ('level', ctypes.c_char_p),
                ('text', ctypes.c_char_p), ('log_level', ctypes.c_int)]

class EndFile(ctypes.Structure):
    _fields_ = [('reason', ctypes.c_int), ('error', ctypes.c_int)]


def load(fw_dir):
    mpv = ctypes.CDLL(os.path.join(fw_dir, 'Mpv.framework', 'Mpv'), mode=ctypes.RTLD_GLOBAL)
    mpv.mpv_create.restype = ctypes.c_void_p
    mpv.mpv_wait_event.restype = ctypes.POINTER(Event)
    mpv.mpv_wait_event.argtypes = [ctypes.c_void_p, ctypes.c_double]
    mpv.mpv_get_property_string.restype = ctypes.c_void_p
    mpv.mpv_get_property_string.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    for f in ('mpv_set_option_string',):
        getattr(mpv, f).argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_char_p]
    mpv.mpv_initialize.argtypes = [ctypes.c_void_p]
    mpv.mpv_command.argtypes = [ctypes.c_void_p, ctypes.POINTER(ctypes.c_char_p)]
    mpv.mpv_request_log_messages.argtypes = [ctypes.c_void_p, ctypes.c_char_p]
    mpv.mpv_terminate_destroy.argtypes = [ctypes.c_void_p]
    mpv.mpv_free.argtypes = [ctypes.c_void_p]
    return mpv


def prop(mpv, h, name):
    p = mpv.mpv_get_property_string(h, name.encode())
    if not p:
        return None
    s = ctypes.cast(p, ctypes.c_char_p).value.decode(errors='replace')
    mpv.mpv_free(p)
    return s


def run_case(fw_dir, clips_dir, case):
    name, clip, clip_fps, frames, opts = case
    mpv = load(fw_dir)
    h = mpv.mpv_create()
    base = {'vo': 'null', 'ao': 'null', 'untimed': 'yes', 'framedrop': 'no',
            'audio': 'no', 'terminal': 'no', 'idle': 'no', 'keep-open': 'no',
            'demuxer-max-bytes': '64MiB'}
    base.update(opts)
    for k, v in base.items():
        mpv.mpv_set_option_string(h, k.encode(), v.encode())
    mpv.mpv_request_log_messages(h, b'warn')
    assert mpv.mpv_initialize(h) == 0
    logs = []
    path = os.path.join(clips_dir, clip).encode()
    args = (ctypes.c_char_p * 3)(b'loadfile', path, None)
    t0 = None
    hwdec_cur = None
    vf_active = None
    reason = None
    deadline = time.time() + 600
    mpv.mpv_command(h, args)
    while time.time() < deadline:
        ev = mpv.mpv_wait_event(h, 1.0).contents
        if ev.event_id == 2 and ev.data:
            m = ctypes.cast(ev.data, ctypes.POINTER(LogMsg)).contents
            logs.append(f"[{(m.prefix or b'').decode()}] {(m.level or b'').decode()}: {(m.text or b'').decode().strip()}")
        elif ev.event_id == 8:  # FILE_LOADED
            t0 = time.time()
        elif ev.event_id == 21 or ev.event_id == 9:  # PLAYBACK_RESTART / legacy
            if hwdec_cur is None:
                hwdec_cur = prop(mpv, h, 'hwdec-current')
                vf_active = prop(mpv, h, 'vf')
        elif ev.event_id == 7:  # END_FILE
            if ev.data:
                reason = ctypes.cast(ev.data, ctypes.POINTER(EndFile)).contents.reason
            break
        elif ev.event_id == 1:
            break
    t1 = time.time()
    if hwdec_cur is None:
        hwdec_cur = prop(mpv, h, 'hwdec-current')
    mpv.mpv_terminate_destroy(h)
    wall = (t1 - t0) if t0 else None
    fps = frames / wall if wall else None
    return {'case': name, 'wall_s': round(wall, 2) if wall else None,
            'fps': round(fps, 1) if fps else None, 'clip_fps': clip_fps,
            'realtime_x': round(fps / clip_fps, 2) if fps else None,
            'end_reason': reason, 'hwdec_current': hwdec_cur, 'vf': vf_active,
            'warnings': logs[:15]}


def config_line(fw_dir):
    avutil = ctypes.CDLL(os.path.join(fw_dir, 'Avutil.framework', 'Avutil'))
    avutil.avutil_configuration.restype = ctypes.c_char_p
    avutil.av_get_cpu_flags.restype = ctypes.c_int
    conf = avutil.avutil_configuration().decode()
    return {'x86asm_enabled_in_configure': '--enable-x86asm' in conf,
            'runtime_cpudetect_in_configure': '--enable-runtime-cpudetect' in conf,
            'av_get_cpu_flags': hex(avutil.av_get_cpu_flags())}


def main():
    if sys.argv[1] == '--case':
        fw_dir, clips_dir, idx = sys.argv[2], sys.argv[3], int(sys.argv[4])
        print(json.dumps(run_case(fw_dir, clips_dir, CASES[idx])))
        return
    if sys.argv[1] == '--config':
        print(json.dumps(config_line(sys.argv[2])))
        return
    fw_dir, label, clips_dir, out = sys.argv[1:5]
    env = dict(os.environ, DYLD_FRAMEWORK_PATH=fw_dir)
    res = {'label': label, 'arch': os.uname().machine}
    res['config'] = json.loads(subprocess.run(
        [sys.executable, __file__, '--config', fw_dir], env=env,
        capture_output=True, text=True, check=True).stdout)
    res['cases'] = []
    for i, c in enumerate(CASES):
        p = subprocess.run([sys.executable, __file__, '--case', fw_dir, clips_dir, str(i)],
                           env=env, capture_output=True, text=True, timeout=900)
        try:
            r = json.loads(p.stdout.strip().splitlines()[-1])
        except Exception:
            r = {'case': c[0], 'error': (p.stderr or p.stdout)[-800:]}
        print(label, json.dumps(r)[:400], flush=True)
        res['cases'].append(r)
    json.dump(res, open(out, 'w'), indent=1)


if __name__ == '__main__':
    main()
