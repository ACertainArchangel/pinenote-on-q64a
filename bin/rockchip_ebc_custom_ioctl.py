#!/usr/bin/env python

# Based upon https://github.com/notro/pydrm :
# https://github.com/notro/pydrm/blob/master/pydrm/drm_h.py
# and
# https://github.com/m-weigand/mw_pinenote_misc/blob/main/rockchip_ebc/python_misc/extract_fbs/ioctl_extract_fbs.py
import ctypes
import fcntl
from pathlib import Path

Y1 = 0x00
Y2 = 0x10
Y4 = 0x20
THRESHOLD = 0x00
DITHER = 0x40
REDRAW = 0x80

MODE_NORMAL = 0
MODE_FAST = 1

SCREEN_DIMS = 1872, 1404

class trigger_global_refresh(ctypes.Structure):
    _fields_ = [
        ("trigger_global_refresh", ctypes.c_bool),
    ]

class off_screen(ctypes.Structure):
    _fields_ = [
        ("info1", ctypes.c_uint64),
        ("ptr_screen_content", ctypes.POINTER(ctypes.c_char_p)),
    ]

class extract_fbs(ctypes.Structure):
    _fields_ = [
        ("ptr_packed_inner_outer_nextprev", ctypes.POINTER(ctypes.c_char_p)),
        ("ptr_hints", ctypes.POINTER(ctypes.c_char_p)),
        ("ptr_prelim_target", ctypes.POINTER(ctypes.c_char_p)),
        ("ptr_phase1", ctypes.POINTER(ctypes.c_char_p)),
        ("ptr_phase2", ctypes.POINTER(ctypes.c_char_p)),
    ]

class drm_mode_rect(ctypes.Structure):
    _fields_ = [
        ("x1", ctypes.c_int32),
        ("y1", ctypes.c_int32),
        ("x2", ctypes.c_int32),
        ("y2", ctypes.c_int32),
    ]

class rect_hint(ctypes.Structure):
    _fields_ = [
        ("hints", ctypes.c_uint8),
        ("padding", ctypes.c_uint8 * 7),
        ("rect", drm_mode_rect),
    ]

class rect_hints(ctypes.Structure):
    _fields_ = [
        ("set_default_hint", ctypes.c_uint8),
        ("default_hint", ctypes.c_uint8),
        ("padding", ctypes.c_uint8 * 2),
        ("num_rects", ctypes.c_uint32),
        ("rect_hints", ctypes.POINTER(rect_hint)),
    ]

class mode(ctypes.Structure):
    _fields_ = [
        ("set_mode", ctypes.c_uint8),
        ("mode", ctypes.c_uint8),
        ("padding", ctypes.c_uint8 * 6),
    ]


_IOC_NRBITS = 8
_IOCtype_BITS = 8
_IOC_SIZEBITS = 14
_IOC_DIRBITS = 2

_IOC_NRMASK = ((1 << _IOC_NRBITS)-1)
_IOCtype_MASK = ((1 << _IOCtype_BITS)-1)
_IOC_SIZEMASK = ((1 << _IOC_SIZEBITS)-1)
_IOC_DIRMASK = ((1 << _IOC_DIRBITS)-1)

_IOC_NRSHIFT = 0
_IOCtype_SHIFT = (_IOC_NRSHIFT+_IOC_NRBITS)
_IOC_SIZESHIFT = (_IOCtype_SHIFT+_IOCtype_BITS)
_IOC_DIRSHIFT = (_IOC_SIZESHIFT+_IOC_SIZEBITS)

_IOC_NONE = 0
_IOC_WRITE = 1
_IOC_READ = 2


def _IOC(_dir, type_, nr, size):
    return ((_dir) << _IOC_DIRSHIFT) | \
           ((type_) << _IOCtype_SHIFT) | \
           ((nr) << _IOC_NRSHIFT) | \
           ((size) << _IOC_SIZESHIFT)


def _IOCtype_CHECK(t):
    return ctypes.sizeof(t)


def _IO(type_, nr):
    return _IOC(_IOC_NONE, (type_), (nr), 0)


def _IOR(type_, nr, size):
    return _IOC(_IOC_READ, (type_), (nr), (_IOCtype_CHECK(size)))


def _IOW(type_, nr, size):
    return _IOC(_IOC_WRITE, (type_), (nr), (_IOCtype_CHECK(size)))


def _IOWR(type_, nr, size):
    return _IOC(_IOC_READ | _IOC_WRITE, (type_), (nr), (_IOCtype_CHECK(size)))


DRM_IOCTL_BASE = ord('d')
DRM_COMMAND_BASE = 0x40

def DRM_IOR(nr, type_):
    return _IOR(DRM_IOCTL_BASE, nr, type_)

def DRM_IOW(nr, type_):
    return _IOW(DRM_IOCTL_BASE, nr, type_)

def DRM_IOWR(nr, type_):
    return _IOWR(DRM_IOCTL_BASE, nr, type_)

DRM_IOCTL_ROCKCHIP_EBC_GLOBAL_REFRESH = DRM_IOWR(DRM_COMMAND_BASE + 0, trigger_global_refresh)
DRM_IOCTL_ROCKCHIP_EBC_OFF_SCREEN = DRM_IOW(DRM_COMMAND_BASE + 1, off_screen)
DRM_IOCTL_ROCKCHIP_EBC_EXTRACT_FBS = DRM_IOWR(DRM_COMMAND_BASE + 2, extract_fbs)
DRM_IOCTL_ROCKCHIP_EBC_RECT_HINTS = DRM_IOW(DRM_COMMAND_BASE + 3, rect_hints)
DRM_IOCTL_ROCKCHIP_EBC_MODE = DRM_IOWR(DRM_COMMAND_BASE + 4, mode)
filename = '/dev/dri/by-path/platform-fdec0000.ebc-card'
direct_mode_parameter = '/sys/module/rockchip_ebc/parameters/direct_mode'

def global_refresh():
    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_GLOBAL_REFRESH, trigger_global_refresh(True))

def set_off_screen(off_screen_path: Path):
    from PIL import Image
    import numpy as np
    img = Image.open(off_screen_path).convert(mode='L', colors=16)
    if (img.height, img.width) == SCREEN_DIMS:
        img = img.transpose(Transpose.ROTATE_90)
    if (img.width, img.height) != SCREEN_DIMS:
        img = img.resize(SCREEN_DIMS)
    img = img.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
    arr = np.array(img, np.uint8) >> 4
    buf_off_screen = ctypes.create_string_buffer(arr.tobytes(), SCREEN_DIMS[0] * SCREEN_DIMS[1])
    _off_screen = off_screen(ptr_screen_content=ctypes.cast(buf_off_screen, ctypes.POINTER(ctypes.c_char_p)))
    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_OFF_SCREEN, _off_screen)

def extract_fbs_to_dir(parent_path: Path):
    num_pixels = SCREEN_DIMS[0] * SCREEN_DIMS[1]
    direct_mode = True
    _direct_mode_param = Path(direct_mode_parameter)
    try:
        if _direct_mode_param.exists() and _direct_mode_param.read_text().strip() == 'N':
            direct_mode = False
    except e:
        pass
    phase_size = num_pixels >> 2 if direct_mode else num_pixels
    buf_packed_inner_outer_nextprev = ctypes.create_string_buffer(3 * num_pixels)
    buf_hints = ctypes.create_string_buffer(num_pixels)
    buf_prelim_target = ctypes.create_string_buffer(num_pixels)
    buf_phase1 = ctypes.create_string_buffer(phase_size)
    buf_phase2 = ctypes.create_string_buffer(phase_size)
    _extract_fbs = extract_fbs(
        ctypes.cast(buf_packed_inner_outer_nextprev, ctypes.POINTER(ctypes.c_char_p)),
        ctypes.cast(buf_hints, ctypes.POINTER(ctypes.c_char_p)),
        ctypes.cast(buf_prelim_target, ctypes.POINTER(ctypes.c_char_p)),
        ctypes.cast(buf_phase1, ctypes.POINTER(ctypes.c_char_p)),
        ctypes.cast(buf_phase2, ctypes.POINTER(ctypes.c_char_p))
    )

    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_EXTRACT_FBS, _extract_fbs)

    (Path(parent_path) / 'buf_packed_inner_outer_nextprev.bin').write_bytes(buf_packed_inner_outer_nextprev)
    (Path(parent_path) / 'buf_hints.bin').write_bytes(buf_hints)
    (Path(parent_path) / 'buf_prelim_target.bin').write_bytes(buf_prelim_target)
    (Path(parent_path) / 'buf_phase1.bin').write_bytes(buf_phase1)
    (Path(parent_path) / 'buf_phase2.bin').write_bytes(buf_phase2)
    return r

def set_rect_hint(_rect_hint: rect_hint):
    set_rect_hints([_rect_hint])

def set_mode(_mode: int):
    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_MODE, mode(set_mode=1, mode=_mode))

def get_mode() -> int:
    _mode = mode(set_mode=0)
    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_MODE, _mode)
    return _mode.mode

def set_rect_hints(_rect_hints: list[rect_hint], default_hint : int | None = None):
    _rhs = (rect_hint * len(_rect_hints))(*_rect_hints)
    arg = rect_hints(set_default_hint=default_hint is not None,
                             default_hint=default_hint or 0,
                             num_rects=len(_rect_hints),
                             rect_hints=ctypes.cast(_rhs, ctypes.POINTER(rect_hint)))
    with open(filename, 'w+b', buffering=0) as fd:
        r = fcntl.ioctl(fd, DRM_IOCTL_ROCKCHIP_EBC_RECT_HINTS, arg)
