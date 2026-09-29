# Gamepad Mouse

Use an Xbox-style controller as a mouse on Windows. Runs in the system tray, starts with Windows, and can be switched off with a button combo so it stays out of your games.

## Controls

| Input | Action |
|---|---|
| Left stick | Move pointer |
| Right stick | Scroll (vertical and horizontal) |
| A | Left click (hold to drag) |
| B | Right click |
| X | Middle click |
| Y | Toggle on-screen keyboard |
| RT / LT | Hold for fast / slow pointer |
| R3 (right stick click) | Toggle precision mode |
| L3 (left stick click) | Double-click |
| LB / RB | Browser back / forward |
| D-pad | Arrow keys (with key repeat) |
| Start / Back | Enter / Esc |
| **Back + Start together** | Turn the program on / off |

The Xbox/Guide button can't be used; Windows reserves it.

## Download (no Python needed)

Grab `GamepadMouse.exe` from the [latest release](https://github.com/TanvirHafiz/gamepad-mouse/releases/latest) and run it. To start it with Windows / undo that:

```bash
GamepadMouse.exe --install-startup
GamepadMouse.exe --uninstall-startup
```

The config file is created next to the exe. The exe is unsigned, so Windows SmartScreen or antivirus may warn about it; you can verify it against the SHA-256 in the release notes or build it yourself (below).

## Run from source

Requires Windows and Python 3.10+.

```bash
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
```

Run it (no console window):

```bash
run.bat
```

Start with Windows / remove that again:

```bash
.venv\Scripts\python mousepad.py --install-startup
.venv\Scripts\python mousepad.py --uninstall-startup
```

## Build the exe

```bash
.venv\Scripts\pip install -r requirements-build.txt
.venv\Scripts\python -m PyInstaller --onefile --noconsole --name GamepadMouse mousepad.py
```

The result is `dist\GamepadMouse.exe`.

## Tray icon

- Green: active
- Red: turned off
- Gray: no controller connected
- Orange: auto-paused because a fullscreen app is in front

Right-click the icon for Enabled, Auto-pause, Open config, Reload config and Quit.

## Games

The program only reads the controller, so it doesn't block games, but the pointer would still move while you play. Turn it off with Back + Start, or enable **Auto-pause in fullscreen apps** from the tray menu (off by default, since it can misfire on fullscreen video).

## Configuration

`mousepad_config.json` is created next to the script on first run. Use "Reload config" in the tray menu after editing.

| Key | Meaning |
|---|---|
| `cursor_speed` | Pixels/second at full stick deflection |
| `deadzone`, `curve` | Stick dead zone and acceleration curve |
| `fast_multiplier`, `slow_multiplier` | Speed factors for RT / LT / precision mode |
| `scroll_speed`, `scroll_deadzone` | Right-stick scrolling |
| `horizontal_scroll`, `invert_scroll` | Scroll options |
| `key_repeat_delay`, `key_repeat_rate` | D-pad key repeat |
| `rumble_on_toggle` | Short rumble when toggled |
| `auto_pause_fullscreen` | Pause in fullscreen apps |
| `start_enabled` | Whether it starts active |

## How it works

Reads the controller via Windows XInput and sends mouse and keyboard input with `SendInput`, using only `ctypes`. `pystray` and `pillow` provide the tray icon.

## License

MIT
