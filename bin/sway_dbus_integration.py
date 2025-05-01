#!/usr/bin/env python3
from dbus_next.aio import MessageBus
from dbus_next.service import ServiceInterface, method

import asyncio
from collections import namedtuple
from dataclasses import dataclass
import enum
import logging
import queue
from typing import Self

import i3ipc
import numpy as np

import rockchip_ebc_custom_ioctl
from rockchip_ebc_custom_ioctl import Y1, Y2, Y4, DITHER, REDRAW

DO_IOCTL = True
OUTPUT_NAME = 'DPI-1'

log = logging.getLogger(__name__)

OutputChanged = namedtuple('OutputChanged', ['output'])
TreeChanged = namedtuple('TreeChanged', ['tree'])
AppHint = namedtuple('AppHint', ['app_id', 'pid', 'hint'])
AppHintRect = namedtuple('AppHintRect', ['app_id', 'pid', 'hint_rect'])
AppHintRects = namedtuple('AppHintRects', ['app_id', 'pid', 'hint_rects'])
GlobalRefresh = namedtuple('GlobalRefresh', [])

Item = OutputChanged | TreeChanged | AppHint | AppHintRect | AppHintRects | GlobalRefresh

Hint = int

@dataclass
class Rect:
    x1: int
    y1: int
    x2: int
    y2: int

    def from_xywh(x1: int, y1: int, width: int, height: int):
        return Rect(x1, y1, x1 + width, y1 + height)

    def overlap(self, r: Self):
        return self.x1 < r.x2 and self.y1 < r.y2 and r.x1 < self.x2 and r.y1 < self.y2

    def intersection(self, r: Self) -> Self:
        rect = Rect(max(self.x1, r.x1), max(self.y1, r.y1), min(self.x2, r.x2), min(self.y2, r.y2))
        if rect.is_valid():
            return rect
        else:
            return Rect(0, 0, 0, 0)

    def is_valid(self):
        return (self.x2 - self.x1) > 0 and (self.y2 - self.y1) > 0

    def to_ioctl_drm_mode_rect(self) -> rockchip_ebc_custom_ioctl.drm_mode_rect:
        return rockchip_ebc_custom_ioctl.drm_mode_rect(x1=round(self.x1), y1=round(self.y1), x2=round(self.x2), y2=round(self.y2))

@dataclass
class HintRect:
    hint: Hint
    rect: Rect

    def to_ioctl_hint_rect(self) -> rockchip_ebc_custom_ioctl.rect_hint:
        return rockchip_ebc_custom_ioctl.rect_hint(hints=self.hint, rect=self.rect.to_ioctl_drm_mode_rect())

@dataclass
class AppHintSetting:
    app_id: str
    pid: str
    configured_hint: Hint
    history: list[HintRect]

class HintSrcType(enum.Enum):
    AppId = 0
    Pid = 1

AffineTransformation = np.ndarray

def make_R(deg) -> AffineTransformation:
    phi = deg * np.pi / 180
    return np.round([[np.cos(phi), np.sin(phi), 0], [-np.sin(phi), np.cos(phi), 0], [0, 0, 1]], 0)

def make_T(x, y) -> AffineTransformation:
    return np.array([[1, 0, x], [0, 1, y], [0, 0, 1]])

def make_S(scale) -> AffineTransformation:
    return np.array([[scale, 0, 0], [0, scale, 0], [0, 0, 1]])

DEFAULT_HINTS = {
    'mpv': Y1 | DITHER,
    'KOReader': Y4,
    'kitty': Y2 | REDRAW,
    'com.github.xournalpp.xournalpp': Y4 | REDRAW,
    'firefox': Y4 | REDRAW,
    'org.qutebrowser.qutebrowser': Y4 | REDRAW,
    'mepo': Y4 | REDRAW,
    'imv': Y4 | REDRAW,
}

DEFAULT_HINT = Y4 | REDRAW

class EPDManager:
    output: i3ipc.replies.OutputReply | None
    log: logging.Logger
    queue: queue.Queue
    comp_to_drm: AffineTransformation
    drm_bb: Rect
    app_hint_settings: dict[tuple[list[AppHintSetting], str], AppHintSetting]
    default_hints: dict[str, Hint]
    default_hint: Hint
    drm_rect_hints: list[rockchip_ebc_custom_ioctl.rect_hint]

    def __init__(self):
        self.log = logging.getLogger('EPDManager')
        self.output = None
        self.output_rotation = 0
        self.tree = None
        self.comp_to_drm = np.zeros((3, 3))
        self.drm_bb = Rect(0, 0, 0, 0)
        self.app_hint_settings = {}
        self.queue = queue.Queue(0)
        self.default_hints = {}
        for app_id, hint in DEFAULT_HINTS.items():
            self.default_hints[app_id] = hint
        self.default_hint = DEFAULT_HINT
        self.drm_rect_hints = []

    def process_output(self, output: i3ipc.replies.OutputReply | None):
        """Compute affine transformation from compositor coordinate system to output coordinates"""
        if output is None or not output.active:
            self.output = None
            self.output_rotation = 0
            self.drm_bb = Rect(0, 0, 0, 0)
        else:
            self.output = output
            _r = output.rect
            x, y, width, height = _r.x, _r.y, _r.width, _r.height
            scale = output.scale
            S = make_S(scale)
            T = make_T(-x, -y)
            # 0: x, y
            # 90: height - y, x
            # 180: width - x, height - y
            # 270: y, width - x
            _w, _h = round(width * scale), round(height * scale)
            match output.transform:
                case 'normal':
                    self.output_rotation = 0
                    R = make_R(0)
                    T2 = make_T(0, 0)
                    _w = round(width * scale),
                case '90':
                    self.output_rotation = 90
                    R = make_R(-90)
                    T2 = make_T(height, 0)
                    _w, _h = _h, _w
                case '180':
                    self.output_rotation = 180
                    R = make_R(180)
                    T2 = make_T(width, height)
                case '270':
                    self.output_rotation = 270
                    R = make_R(-270)
                    T2 = make_T(0, width)
                    _w, _h = _h, _w
            comp_to_drm = S @ T2 @ R @ T
            self.log.info('output.transform %s transformation %s', output.transform, comp_to_drm)
            if np.allclose(comp_to_drm_rounded := np.round(comp_to_drm, 0), comp_to_drm):
                comp_to_drm = comp_to_drm_rounded
            if not np.allclose(comp_to_drm, self.comp_to_drm):
                self.comp_to_drm = comp_to_drm
                self.drm_bb = Rect(0, 0, _w, _h)
                self.recompute_hints()

    def get_app_hint_setting(self, app_id: str, pid: str | int, create_default: bool = False, insert_default: bool = False):
        pid = str(pid)
        setting = (
            self.app_hint_settings.get((HintSrcType.Pid, pid))
            or self.app_hint_settings.get((HintSrcType.AppId, app_id))
        )
        if not setting and create_default:
            hint = self.default_hints.get(app_id) or self.default_hint
            setting = AppHintSetting(app_id, pid, hint, [])
            if insert_default:
                self.app_hint_settings[(HintSrcType.Pid, pid)] = setting
        return setting

    def process_tree(self, tree: i3ipc.con.Con):
        cons = [d for d in tree.descendants() if d.type in ['floating_con', 'con']]
        visible_cons = [con for con in cons if con.ipc_data.get('visible')]
        self.log.debug('visible cons %s', visible_cons)
        # TODO: vectorise
        drm_rect_hints = []
        for con in visible_cons:
            # DRM coordinates of setting.app_hint
            win_overlap = self.get_overlap_on_epd_output(con)
            self.log.debug('process_tree name=%s win_overlap=%s is_valid=%d', con.name, win_overlap, win_overlap.is_valid())
            if win_overlap.is_valid():
                setting = self.get_app_hint_setting(con.app_id, con.pid, True, False)
                drm_rect_hints.append(HintRect(setting.configured_hint, win_overlap))
                for hint_rect in setting.history:
                    overlap = self.get_overlap_on_epd_output(con, hint_rect.rect)
                    if overlap.is_valid():
                        drm_rect_hints.append(HintRect(hint_rect.hint, overlap))
        self.update_drm_hints(drm_rect_hints)

    def update_drm_hints(self, drm_rect_hints: list[HintRect]):
        if self.drm_rect_hints != drm_rect_hints:
            self.drm_rect_hints = drm_rect_hints
            self.log.info("Setting drm hints %s", drm_rect_hints)
            if DO_IOCTL:
                rockchip_ebc_custom_ioctl.set_rect_hints(list(map(HintRect.to_ioctl_hint_rect, drm_rect_hints)), self.default_hint)

    def get_overlap_on_epd_output(self, con: i3ipc.con.Con, win_rect: Rect | None = None) -> Rect:
        r = con.rect
        if win_rect is None:
            x1, y1 = r.x, r.y
            x2, y2 = r.x + r.width, r.y + r.height
        else:
            x1, y1 = r.x + win_rect.x1, r.y + win_rect.y1
            x2, y2 = r.x + win_rect.x2, r.y + win_rect.y2
        win_coords = np.array([[x1, x2], [y1, y2], [1, 1]])
        drm_coords = np.sort(self.comp_to_drm @ win_coords, 1)
        win_drm_rect = Rect(drm_coords[0,0], drm_coords[1,0], drm_coords[0,1], drm_coords[1,1])
        self.log.debug('win_coords=%s drm_coords=%s win_drm_rect=%s drm_bb=%s',
                      win_coords, drm_coords, win_drm_rect, self.drm_bb)
        return win_drm_rect.intersection(self.drm_bb)

    def run(self):
        self.log.info('Started')
        while True:
            item = self.queue.get()
            self.log.debug('Received %s', item)

            self.process(item)

    def get_pids_from_tree(self, app_id: str) -> list[str]:
        if self.tree:
            return [str(d.pid) for d in self.tree.descendants() if d.type in ['floating_con', 'con'] and d.app_id == app_id]
        else:
            return []

    def update_app_hint_setting(self, app_id: str, pid: str | int | None, hint: Hint | None = None, history: list[HintRect] | None = None, add_history: list[HintRect] = [], recompute_hints: bool = True):
        # the pid is missing, apply this function to all relevant nodes in self.tree
        if pid is None or pid == '':
            pids = self.get_pids_from_tree(self, app_id)
            if pids:
                for pid in pids:
                    self.update_app_hint_setting(self, app_id, pid, hint, history, add_history, False)
                if recompute_hints:
                    self.recompute_hints()
            return
        _upd = False
        setting = self.get_app_hint_setting(app_id, pid, False)
        if not setting:
            _upd = True
            setting = self.get_app_hint_setting(app_id, pid, True, True)
        if hint is not None:
            _upd = True
            setting.configured_hint = hint
        if history is not None and history != setting.history:
            _upd = True
            setting.history = history
        if add_history:

            # TODO: remove items if they are completely covered by the union of all later items
            _upd = True
            setting.history.extend(add_history)
        # Enforce an arbitrary maximum for now until the above TODO is addressed
        setting.history = setting.history[:20]
        self.app_hint_settings[(HintSrcType.AppId, str(pid))] = setting
        if recompute_hints:
            self.recompute_hints()

    def process(self, item: Item):
        match item:
            case OutputChanged(output):
                self.process_output(output)
            case TreeChanged(tree):
                self.tree = tree
                self.recompute_hints()
            case AppHint(app_id, pid, hint):
                self.update_app_hint_setting(app_id, pid, hint=hint)
            case AppHintRect(app_id, pid, hint_rect):
                self.update_app_hint_setting(app_id, pid, add_history=[hint_rect])
            case AppHintRects(app_id, pid, hint_rects):
                self.update_app_hint_setting(app_id, pid, add_history=hint_rects)
            case GlobalRefresh():
                self.log.info('Triggering global refresh')
                if DO_IOCTL:
                    rockchip_ebc_custom_ioctl.global_refresh()

    def recompute_hints(self):
        if self.tree:
            self.process_tree(self.tree)

    def add_item(self, item: Item):
        self.log.debug('Adding item %d %s', id(self.queue), item)
        self.queue.put(item)

class PinenoteEbcCustomInterface(ServiceInterface):
    epd_manager: EPDManager
    log: logging.Logger

    def __init__(self, epd_manager: EPDManager):
        super().__init__('org.pinenote.ebc_custom')
        self.log = logging.getLogger('PineNoteEbcCustom')
        self.epd_manager = epd_manager

    @method()
    async def appHint(self, app_id: 's', pid: 's', hint: 'y') -> None:
        self.epd_manager.add_item(AppHint(app_id, pid, hint))

    @method()
    async def appHintRect(self, app_id: 's', pid: 's', hint_rect: '(yiiuu)') -> None:
        hint_rect = HintRect(hint_rect[0], Rect.from_xywh(*hint_rect[1:]))
        self.epd_manager.add_item(AppHintRect(app_id, pid, hint_rect))

    @method()
    async def appHintRects(self, app_id: 's', pid: 's', hint_rects: 'a(yiiuu)') -> None:
        hint_rects = [HintRect(hint_rect[0], Rect.from_xywh(*hint_rect[1:])) for hint_rect in hint_rects]
        self.epd_manager.add_item(AppHintRects(app_id, pid, hint_rects))

    @method()
    def GlobalRefresh(self) -> None:
        self.epd_manager.add_item(GlobalRefresh())

async def dbus_task_app_hint(pinenote_ebc_custom_interface: PinenoteEbcCustomInterface, epd_manager: EPDManager) -> None:
    log.info('running dbus task app_hints')
    async for x in pinenote_ebc_custom_interface.app_hint_rect:
        log.info('received app_hints %s', x)

async def dbus_task_global_refresh(pinenote_ebc_custom_interface: PinenoteEbcCustomInterface, epd_manager: EPDManager) -> None:
    log.info('running dbus task global_refresh')
    async for x in pinenote_ebc_custom_interface.global_refresh:
        log.info('received global_refresh %s', x)

def process_outputs(epd_manager: EPDManager, outputs: i3ipc.replies.OutputReply):
    log.info('process outputs')
    epd_output = None
    for output in outputs:
        if output.name == OUTPUT_NAME:
            epd_output = output
            break
    epd_manager.add_item(OutputChanged(epd_output))

def sway_task(epd_manager: EPDManager) -> None:
    log.info('starting sway task')
    def on_event(self, e):
        log.info('on_event: awaiting tree')
        tree = conn.get_tree()
        log.info('on_event: got tree')
        epd_manager.add_item(TreeChanged(tree))
        log.debug('on_event %s', e)
    def on_output_event(self, e):
        process_outputs(epd_manager, conn.get_outputs())
        log.info('on_output_event %s', e)

    log.info('connecting')
    conn = i3ipc.Connection()
    log.info('connected')
    conn.on(i3ipc.Event.OUTPUT, on_output_event)
    conn.on(i3ipc.Event.WORKSPACE, on_event)
    conn.on(i3ipc.Event.WINDOW, on_event)
    process_outputs(epd_manager, conn.get_outputs())
    epd_manager.add_item(TreeChanged(conn.get_tree()))
    # TODO: timer requesting tree regularly, as we don't catch resize or move events

    conn.main()

async def main():
    logging.basicConfig(level=logging.DEBUG)

    epd_manager = EPDManager()

    bus = await MessageBus().connect()
    interface = PinenoteEbcCustomInterface(epd_manager)
    bus.export('/', interface)
    await bus.request_name('org.pinenote.ebc_custom')

    _pinenote_ebc_custom_interface = PinenoteEbcCustomInterface(epd_manager)
    async with asyncio.TaskGroup() as tg:
        _task_sway = tg.create_task(asyncio.to_thread(lambda: sway_task(epd_manager)))
        _task_ebc = tg.create_task(asyncio.to_thread(epd_manager.run))
        log.info('started tasks')
    log.info('waiting for disconnect')
    await bus.wait_for_disconnect()
    log.info('waited for disconnect')

if __name__ == '__main__':
    asyncio.run(main(), debug=True)
