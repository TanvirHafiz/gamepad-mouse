"""Gamepad Mouse - use an Xbox-style controller as a mouse (Windows).

Left stick  = move pointer      Right stick = scroll
A/B/X       = left/right/middle click
Back+Start  = toggle on/off     (see README.txt / tray menu for the rest)
"""
import ctypes
import json
import math
import os
import subprocess
import sys
import threading
import time
from ctypes import wintypes

import pystray
from PIL import Image, ImageDraw

APP_NAME = "Gamepad Mouse"
FROZEN = getattr(sys, "frozen", False)
BASE_DIR = os.path.dirname(sys.executable if FROZEN else os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE_DIR, "mousepad_config.json")

DEFAULTS = {
    "poll_hz": 125,
    "deadzone": 0.18,
    "curve": 2.0,
    "cursor_speed": 1200,        # pixels/second at full stick deflection
    "fast_multiplier": 2.5,      # while RT held
    "slow_multiplier": 0.3,      # while LT held or precision mode on
    "trigger_threshold": 0.3,
    "scroll_deadzone": 0.25,
    "scroll_speed": 10,          # wheel notches/second at full deflection
    "horizontal_scroll": True,
    "invert_scroll": False,
    "key_repeat_delay": 0.4,
    "key_repeat_rate": 0.05,
    "rumble_on_toggle": True,
    "auto_pause_fullscreen": False,
    "start_enabled": True,
}


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as f:
            cfg.update(json.load(f))
    except FileNotFoundError:
        pass
    except Exception as e:
        print("Config error, using defaults:", e)
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2)
    except OSError:
        pass
    return cfg


# ---------------------------------------------------------------- XInput
class XINPUT_GAMEPAD(ctypes.Structure):
    _fields_ = [
        ("wButtons", wintypes.WORD),
        ("bLeftTrigger", ctypes.c_ubyte),
        ("bRightTrigger", ctypes.c_ubyte),
        ("sThumbLX", ctypes.c_short),
        ("sThumbLY", ctypes.c_short),
        ("sThumbRX", ctypes.c_short),
        ("sThumbRY", ctypes.c_short),
    ]


class XINPUT_STATE(ctypes.Structure):
    _fields_ = [("dwPacketNumber", wintypes.DWORD), ("Gamepad", XINPUT_GAMEPAD)]


class XINPUT_VIBRATION(ctypes.Structure):
    _fields_ = [("wLeftMotorSpeed", wintypes.WORD), ("wRightMotorSpeed", wintypes.WORD)]


def _load_xinput():
    for name in ("xinput1_4", "xinput1_3", "xinput9_1_0"):
        try:
            return ctypes.WinDLL(name)
        except OSError:
            continue
    raise RuntimeError("XInput DLL not found")


xinput = _load_xinput()
xinput.XInputGetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_STATE)]
xinput.XInputSetState.argtypes = [wintypes.DWORD, ctypes.POINTER(XINPUT_VIBRATION)]

DPAD_UP, DPAD_DOWN, DPAD_LEFT, DPAD_RIGHT = 0x0001, 0x0002, 0x0004, 0x0008
START, BACK, L3, R3 = 0x0010, 0x0020, 0x0040, 0x0080
LB, RB = 0x0100, 0x0200
BTN_A, BTN_B, BTN_X, BTN_Y = 0x1000, 0x2000, 0x4000, 0x8000

# ---------------------------------------------------------------- SendInput
user32 = ctypes.WinDLL("user32", use_last_error=True)
kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 else ctypes.c_ulong


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _anonymous_ = ("u",)
    _fields_ = [("type", wintypes.DWORD), ("u", _INPUT_UNION)]


user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]

MOUSEEVENTF_MOVE = 0x0001
MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP = 0x0002, 0x0004
MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP = 0x0008, 0x0010
MOUSEEVENTF_MIDDLEDOWN, MOUSEEVENTF_MIDDLEUP = 0x0020, 0x0040
MOUSEEVENTF_WHEEL, MOUSEEVENTF_HWHEEL = 0x0800, 0x1000
KEYEVENTF_EXTENDEDKEY, KEYEVENTF_KEYUP = 0x0001, 0x0002

VK_RETURN, VK_ESCAPE = 0x0D, 0x1B
VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN = 0x25, 0x26, 0x27, 0x28
VK_BROWSER_BACK, VK_BROWSER_FORWARD = 0xA6, 0xA7
EXTENDED_VKS = {VK_LEFT, VK_UP, VK_RIGHT, VK_DOWN, VK_BROWSER_BACK, VK_BROWSER_FORWARD}


def _send(inp):
    user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))


def mouse_event(flags, dx=0, dy=0, data=0):
    inp = INPUT(type=0)
    inp.mi = MOUSEINPUT(dx, dy, data & 0xFFFFFFFF, flags, 0, 0)
    _send(inp)


def key_event(vk, down):
    flags = (KEYEVENTF_EXTENDEDKEY if vk in EXTENDED_VKS else 0) | (0 if down else KEYEVENTF_KEYUP)
    inp = INPUT(type=1)
    inp.ki = KEYBDINPUT(vk, 0, flags, 0, 0)
    _send(inp)


def tap_key(vk):
    key_event(vk, True)
    key_event(vk, False)


def click(down_flag, up_flag, times=1):
    for _ in range(times):
        mouse_event(down_flag)
        mouse_event(up_flag)


# ---------------------------------------------------------------- helpers
def is_foreground_fullscreen():
    hwnd = user32.GetForegroundWindow()
    if not hwnd:
        return False
    buf = ctypes.create_unicode_buffer(64)
    user32.GetClassNameW(hwnd, buf, 64)
    if buf.value in ("Progman", "WorkerW", "Shell_TrayWnd"):
        return False

    class MONITORINFO(ctypes.Structure):
        _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT),
                    ("rcWork", wintypes.RECT), ("dwFlags", wintypes.DWORD)]

    rect = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(rect))
    mon = user32.MonitorFromWindow(hwnd, 2)  # MONITOR_DEFAULTTONEAREST
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    user32.GetMonitorInfoW(mon, ctypes.byref(mi))
    m = mi.rcMonitor
    return (rect.left <= m.left and rect.top <= m.top and
            rect.right >= m.right and rect.bottom >= m.bottom)


def toggle_osk():
    r = subprocess.run(["taskkill", "/im", "osk.exe", "/f"], capture_output=True,
                       creationflags=0x08000000)
    if r.returncode != 0:
        try:
            os.startfile("osk.exe")
        except OSError:
            pass


def rumble(index, ms=150, strength=40000):
    vib = XINPUT_VIBRATION(strength, strength)
    xinput.XInputSetState(index, ctypes.byref(vib))

    def stop():
        xinput.XInputSetState(index, ctypes.byref(XINPUT_VIBRATION(0, 0)))
    threading.Timer(ms / 1000.0, stop).start()


# ---------------------------------------------------------------- engine
class Engine:
    def __init__(self, on_state_change):
        self.cfg = load_config()
        self.enabled = bool(self.cfg["start_enabled"])
        self.auto_pause = bool(self.cfg["auto_pause_fullscreen"])
        self.game_pause = False
        self.precision = False
        self.connected = False
        self.stop_event = threading.Event()
        self.on_state_change = on_state_change
        self.pad = 0
        self.prev = 0
        self.combo_used = False
        self.left_held = self.right_held = self.middle_held = False
        self.acc_x = self.acc_y = self.acc_sx = self.acc_sy = 0.0
        self.repeat = {}  # vk -> next fire time
        self.last_fs_check = 0.0

    # state ---------------------------------------------------------
    @property
    def active(self):
        return self.enabled and not self.game_pause

    def reload_config(self):
        self.cfg = load_config()

    def set_enabled(self, value, buzz=True):
        if self.enabled == value:
            return
        self.enabled = value
        if not self.active:
            self.release_all()
        if buzz and self.cfg["rumble_on_toggle"] and self.connected:
            rumble(self.pad)
        self.on_state_change()

    def release_all(self):
        if self.left_held:
            mouse_event(MOUSEEVENTF_LEFTUP)
        if self.right_held:
            mouse_event(MOUSEEVENTF_RIGHTUP)
        if self.middle_held:
            mouse_event(MOUSEEVENTF_MIDDLEUP)
        self.left_held = self.right_held = self.middle_held = False
        for vk in list(self.repeat):
            key_event(vk, False)
        self.repeat.clear()

    # controller ----------------------------------------------------
    def poll(self):
        st = XINPUT_STATE()
        order = [self.pad] + [i for i in range(4) if i != self.pad]
        for i in order:
            if xinput.XInputGetState(i, ctypes.byref(st)) == 0:
                if not self.connected or i != self.pad:
                    self.pad = i
                    self.connected = True
                    self.on_state_change()
                return st.Gamepad
        if self.connected:
            self.connected = False
            self.release_all()
            self.on_state_change()
        return None

    def run(self):
        last = time.perf_counter()
        while not self.stop_event.is_set():
            gp = self.poll()
            if gp is None:
                time.sleep(1.0)
                last = time.perf_counter()
                continue
            now = time.perf_counter()
            dt = min(now - last, 0.1)
            last = now
            try:
                self.step(gp, dt, now)
            except Exception as e:  # never let the loop die
                print("step error:", e)
            time.sleep(1.0 / max(30, self.cfg["poll_hz"]))
        self.release_all()

    # per-frame -----------------------------------------------------
    def step(self, gp, dt, now):
        cfg = self.cfg
        b = gp.wButtons
        pressed = b & ~self.prev
        released = self.prev & ~b

        # master toggle: Back + Start together
        if (b & START) and (b & BACK):
            if not self.combo_used:
                self.combo_used = True
                self.set_enabled(not self.enabled)
        elif not (b & (START | BACK)):
            self.combo_used = False

        # fullscreen auto-pause
        if self.auto_pause and now - self.last_fs_check > 1.0:
            self.last_fs_check = now
            fs = is_foreground_fullscreen()
            if fs != self.game_pause:
                self.game_pause = fs
                if not self.active:
                    self.release_all()
                self.on_state_change()
        elif not self.auto_pause and self.game_pause:
            self.game_pause = False
            self.on_state_change()

        if not self.active:
            self.prev = b
            return

        # clicks
        if pressed & BTN_A:
            mouse_event(MOUSEEVENTF_LEFTDOWN)
            self.left_held = True
        if released & BTN_A and self.left_held:
            mouse_event(MOUSEEVENTF_LEFTUP)
            self.left_held = False
        if pressed & BTN_B:
            mouse_event(MOUSEEVENTF_RIGHTDOWN)
            self.right_held = True
        if released & BTN_B and self.right_held:
            mouse_event(MOUSEEVENTF_RIGHTUP)
            self.right_held = False
        if pressed & BTN_X:
            mouse_event(MOUSEEVENTF_MIDDLEDOWN)
            self.middle_held = True
        if released & BTN_X and self.middle_held:
            mouse_event(MOUSEEVENTF_MIDDLEUP)
            self.middle_held = False
        if pressed & L3:
            click(MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, 2)
        if pressed & R3:
            self.precision = not self.precision
            self.on_state_change()
        if pressed & BTN_Y:
            threading.Thread(target=toggle_osk, daemon=True).start()

        # tap keys
        if pressed & LB:
            tap_key(VK_BROWSER_BACK)
        if pressed & RB:
            tap_key(VK_BROWSER_FORWARD)
        # Start/Back act on release, unless they were part of the toggle combo
        if released & START and not self.combo_used:
            tap_key(VK_RETURN)
        if released & BACK and not self.combo_used:
            tap_key(VK_ESCAPE)

        # d-pad arrows with key repeat
        for mask, vk in ((DPAD_UP, VK_UP), (DPAD_DOWN, VK_DOWN),
                         (DPAD_LEFT, VK_LEFT), (DPAD_RIGHT, VK_RIGHT)):
            if pressed & mask:
                key_event(vk, True)
                key_event(vk, False)
                self.repeat[vk] = now + cfg["key_repeat_delay"]
            elif b & mask and vk in self.repeat:
                if now >= self.repeat[vk]:
                    tap_key(vk)
                    self.repeat[vk] = now + cfg["key_repeat_rate"]
            elif released & mask:
                self.repeat.pop(vk, None)

        # pointer
        rt = gp.bRightTrigger / 255.0
        lt = gp.bLeftTrigger / 255.0
        mult = 1.0
        if rt > cfg["trigger_threshold"]:
            mult = cfg["fast_multiplier"]
        elif lt > cfg["trigger_threshold"] or self.precision:
            mult = cfg["slow_multiplier"]
        vx, vy = self.stick(gp.sThumbLX, gp.sThumbLY, cfg["deadzone"], cfg["curve"])
        self.acc_x += vx * cfg["cursor_speed"] * mult * dt
        self.acc_y -= vy * cfg["cursor_speed"] * mult * dt  # screen Y is inverted
        ix, iy = int(self.acc_x), int(self.acc_y)
        if ix or iy:
            self.acc_x -= ix
            self.acc_y -= iy
            mouse_event(MOUSEEVENTF_MOVE, ix, iy)

        # scroll
        sx, sy = self.stick(gp.sThumbRX, gp.sThumbRY, cfg["scroll_deadzone"], 1.5)
        sign = -1 if cfg["invert_scroll"] else 1
        self.acc_sy += sign * sy * cfg["scroll_speed"] * dt
        self.acc_sx += sign * sx * cfg["scroll_speed"] * dt if cfg["horizontal_scroll"] else 0
        wy, wx = int(self.acc_sy), int(self.acc_sx)
        if wy:
            self.acc_sy -= wy
            mouse_event(MOUSEEVENTF_WHEEL, data=wy * 120)
        if wx:
            self.acc_sx -= wx
            mouse_event(MOUSEEVENTF_HWHEEL, data=wx * 120)

        self.prev = b

    @staticmethod
    def stick(x, y, deadzone, curve):
        fx, fy = x / 32767.0, y / 32767.0
        mag = math.hypot(fx, fy)
        if mag < deadzone:
            return 0.0, 0.0
        mag = min(mag, 1.0) if mag <= 1.0 else 1.0
        scaled = ((mag - deadzone) / (1.0 - deadzone)) ** curve
        ux, uy = fx / math.hypot(fx, fy), fy / math.hypot(fx, fy)
        return ux * scaled, uy * scaled


# ---------------------------------------------------------------- tray
def make_icon(color):
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=color)
    d.rectangle((28, 14, 36, 50), fill="white")   # d-pad cross
    d.rectangle((14, 28, 50, 36), fill="white")
    return img


def startup_script_path():
    return os.path.join(os.environ["APPDATA"], "Microsoft", "Windows",
                        "Start Menu", "Programs", "Startup", "GamepadMouse.vbs")


def install_startup():
    if FROZEN:
        cmd = '""%s""' % sys.executable
    else:
        exe = os.path.join(BASE_DIR, ".venv", "Scripts", "pythonw.exe")
        if not os.path.exists(exe):
            sys.exit("venv not found. Create it first: python -m venv .venv && "
                     ".venv\\Scripts\\pip install -r requirements.txt")
        cmd = '""%s"" ""%s""' % (exe, os.path.abspath(__file__))
    with open(startup_script_path(), "w", encoding="utf-8") as f:
        f.write('CreateObject("Wscript.Shell").Run "%s", 0, False\n' % cmd)
    print("Installed startup entry:", startup_script_path())


def uninstall_startup():
    try:
        os.remove(startup_script_path())
        print("Removed startup entry.")
    except FileNotFoundError:
        print("No startup entry found.")


def main():
    if "--install-startup" in sys.argv:
        return install_startup()
    if "--uninstall-startup" in sys.argv:
        return uninstall_startup()

    mutex = kernel32.CreateMutexW(None, False, "GamepadMouseSingleInstance")
    if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
        return

    icon = None

    def status_text():
        if not engine.connected:
            return "no controller"
        if not engine.enabled:
            return "off"
        if engine.game_pause:
            return "paused (fullscreen app)"
        return "precision mode" if engine.precision else "on"

    def refresh():
        if icon is None:
            return
        if not engine.connected:
            color = (120, 120, 120, 255)
        elif not engine.enabled:
            color = (190, 60, 60, 255)
        elif engine.game_pause:
            color = (220, 150, 30, 255)
        else:
            color = (40, 170, 80, 255)
        icon.icon = make_icon(color)
        icon.title = "%s - %s" % (APP_NAME, status_text())

    engine = Engine(refresh)

    def toggle_enabled(icon_, item):
        engine.set_enabled(not engine.enabled)

    def toggle_auto(icon_, item):
        engine.auto_pause = not engine.auto_pause

    def open_config(icon_, item):
        load_config()
        os.startfile(CONFIG_PATH)

    def reload_cfg(icon_, item):
        engine.reload_config()

    def quit_app(icon_, item):
        engine.stop_event.set()
        icon_.stop()

    menu = pystray.Menu(
        pystray.MenuItem(lambda item: "Status: " + status_text(), None, enabled=False),
        pystray.MenuItem("Enabled", toggle_enabled, checked=lambda item: engine.enabled),
        pystray.MenuItem("Auto-pause in fullscreen apps", toggle_auto,
                         checked=lambda item: engine.auto_pause),
        pystray.MenuItem("Open config file", open_config),
        pystray.MenuItem("Reload config", reload_cfg),
        pystray.MenuItem("Quit", quit_app),
    )
    icon = pystray.Icon(APP_NAME, make_icon((120, 120, 120, 255)), APP_NAME, menu)
    threading.Thread(target=engine.run, daemon=True).start()
    icon.run(setup=lambda i: (setattr(i, "visible", True), refresh()))
    engine.stop_event.set()
    time.sleep(0.1)
    del mutex


if __name__ == "__main__":
    main()
