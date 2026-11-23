"""Windows-only plumbing: read the active editor's full text, and global hotkeys.

Reading uses Windows UI Automation (UIA): no copy/paste, no selection, no saving.
Hotkeys use RegisterHotKey, so no extra package and no keyboard hooks are needed.
This module imports cleanly on any OS; Windows calls happen only inside functions.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import traceback
from ctypes import wintypes
from dataclasses import dataclass

# Hotkey modifier flags and virtual-key codes (Win32)
MOD_ALT, MOD_CONTROL, MOD_NOREPEAT = 0x0001, 0x0002, 0x4000
VK_F8, VK_F9 = 0x77, 0x78
WM_HOTKEY, WM_QUIT = 0x0312, 0x0012


@dataclass
class EditorSnapshot:
    ok: bool
    text: str = ""
    app: str = ""
    window_title: str = ""
    method: str = ""
    error: str = ""          # learner-facing explanation when ok is False


def _process_name(pid: int) -> str:
    try:
        k32 = ctypes.windll.kernel32
        k32.OpenProcess.restype = ctypes.c_void_p
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = k32.OpenProcess(0x1000, False, pid)      # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            k32.QueryFullProcessImageNameW.argtypes = [
                ctypes.c_void_p, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            if k32.QueryFullProcessImageNameW(handle, 0, buf, ctypes.byref(size)):
                return os.path.basename(buf.value).lower()
            return ""
        finally:
            k32.CloseHandle(handle)
    except Exception:
        return ""


def _text_from(auto, ctrl):
    """Try TextPattern (whole document, including off-screen lines), then ValuePattern."""
    try:
        pattern = ctrl.GetPattern(auto.PatternId.TextPattern)
        if pattern:
            return pattern.DocumentRange.GetText(-1), "TextPattern"
    except Exception:
        pass
    try:
        pattern = ctrl.GetPattern(auto.PatternId.ValuePattern)
        if pattern:
            return pattern.Value, "ValuePattern"
    except Exception:
        pass
    return None, ""


def _clean(text: str) -> str:
    return (text.replace("\r\n", "\n").replace("\r", "\n")
                .replace("\ufeff", "").replace("\x00", ""))


def _read(auto) -> EditorSnapshot:
    focused = auto.GetFocusedControl()
    if focused is None:
        return EditorSnapshot(False, error="No window has keyboard focus. Click into your editor and try again.")
    pid = focused.ProcessId
    app = _process_name(pid)
    if pid == os.getpid():
        return EditorSnapshot(False, app=app, error=(
            "The Synta overlay itself has focus. Click into your editor "
            "(for example the Notepad text area), then press the hotkey again."))
    title, top = "", None
    try:
        top = focused.GetTopLevelControl()
        title = top.Name or ""
    except Exception:
        pass

    text, method = _text_from(auto, focused)
    if text is None and top is not None:          # fallback: look for an edit/document control
        try:
            for ctrl, _depth in auto.WalkControl(top, maxDepth=8):
                if ctrl.ControlTypeName in ("EditControl", "DocumentControl"):
                    text, method = _text_from(auto, ctrl)
                    if text is not None:
                        break
        except Exception:
            pass
    if text is None:
        return EditorSnapshot(False, app=app, window_title=title, error=(
            f"I can't read text from {app or 'this app'}. It does not share its text with Windows "
            "UI Automation. Notepad works; other editors are a later milestone."))
    return EditorSnapshot(True, text=_clean(text), app=app, window_title=title, method=method)


def read_active_editor() -> EditorSnapshot:
    """Read the whole document in the focused editor. Safe to call from any thread."""
    if sys.platform != "win32":
        return EditorSnapshot(False, error="Reading editors needs Windows (UI Automation).")
    try:
        import uiautomation as auto
    except ImportError:
        return EditorSnapshot(False, error="The 'uiautomation' package is missing. Run: pip install uiautomation")
    try:
        with auto.UIAutomationInitializerInThread():
            return _read(auto)
    except Exception as exc:
        return EditorSnapshot(False, error=f"Could not read the editor ({type(exc).__name__}: {exc}).")


def describe_focus() -> str:
    """Debug helper for --probe: what does UI Automation see in the focused control?"""
    if sys.platform != "win32":
        return "Not Windows."
    import uiautomation as auto
    with auto.UIAutomationInitializerInThread():
        c = auto.GetFocusedControl()
        if c is None:
            return "No focused control."
        patterns = []
        for name in ("TextPattern", "ValuePattern"):
            try:
                if c.GetPattern(getattr(auto.PatternId, name)):
                    patterns.append(name)
            except Exception:
                pass
        return (f"process={_process_name(c.ProcessId)}  controlType={c.ControlTypeName}  "
                f"class={c.ClassName!r}  name={c.Name!r}  patterns={patterns or 'none'}")


class HotkeyListener(threading.Thread):
    """Registers global hotkeys and calls callback(hotkey_id) on this thread.

    The callback runs while the editor still has focus, so it can capture the
    code immediately. Keep it short; do Tk work via a queue, not directly.
    """

    def __init__(self, bindings: dict[int, tuple[int, int]], callback):
        super().__init__(daemon=True)
        self.bindings = bindings
        self.callback = callback
        self.failed: list[int] = []
        self.ready = threading.Event()
        self._thread_id = None

    def run(self):
        if sys.platform != "win32":
            self.failed = list(self.bindings)
            self.ready.set()
            return
        user32, kernel32 = ctypes.windll.user32, ctypes.windll.kernel32
        self._thread_id = kernel32.GetCurrentThreadId()
        registered = []
        for hk_id, (mods, vk) in self.bindings.items():
            if user32.RegisterHotKey(None, hk_id, mods | MOD_NOREPEAT, vk):
                registered.append(hk_id)
            else:
                self.failed.append(hk_id)        # another app already owns that combination
        self.ready.set()
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
            if msg.message == WM_HOTKEY:
                try:
                    self.callback(int(msg.wParam))
                except Exception:
                    traceback.print_exc()
        for hk_id in registered:
            user32.UnregisterHotKey(None, hk_id)

    def stop(self):
        if self._thread_id and sys.platform == "win32":
            ctypes.windll.user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
