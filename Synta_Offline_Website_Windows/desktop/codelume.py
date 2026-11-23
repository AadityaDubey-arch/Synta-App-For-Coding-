"""Synta - Syntax Shift. "Your code. Your pace. Your AI tutor."

Always-on-top tutor overlay for Windows 11. Reads the active editor (Notepad first)
through UI Automation, checks Python syntax locally, and gives adaptive AI hints on request.

Run:   python codelume.py            (start the overlay)
       python codelume.py --probe    (debug: what does UI Automation see in my editor?)
"""
from __future__ import annotations

import ctypes
import queue
import sys
import threading
import time
import traceback
import webbrowser
import http.client
import json
import re
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

if sys.version_info < (3, 10):
    sys.exit("Synta needs Python 3.10 or newer.")

from chat_panel import ChatPanel
import checker
import config
import diagnostic
import learner
import tutor
import website
import win_editor
from session import LABELS, STAGES, HelpSession

HK_CHECK, HK_ASK = 1, 2
BG, PANEL, FG, MUTED = "#1b1d24", "#262933", "#e8eaf0", "#9aa0b4"
GREEN, AMBER, RED, ACCENT = "#6fd08c", "#f2b84b", "#ff7b7b", "#7aa2ff"


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Synta")
        self.events: queue.Queue = queue.Queue()
        self.profile = learner.LearnerProfile.load()
        self.session = HelpSession()
        self.waiting = False
        self.last_fix = ""
        self.chat_panel = None
        self.website = None
        self.chat_context = ("", "General chat")
        self.snapshot_source = ""
        self.expected = ""
        self._ask_storage_consent()
        self._build()
        self.root.update_idletasks()
        self.root.protocol("WM_DELETE_WINDOW", self.quit)
        self._make_non_activating()
        self.hotkeys = win_editor.HotkeyListener(
            {HK_CHECK: (win_editor.MOD_CONTROL | win_editor.MOD_ALT, win_editor.VK_F8),
             HK_ASK: (win_editor.MOD_CONTROL | win_editor.MOD_ALT, win_editor.VK_F9)}, self._on_hotkey)
        self.hotkeys.start()
        self.hotkeys.ready.wait(2)
        self._refresh_status()
        self._welcome()
        self.root.after(100, self._pump)

    # ------------------------------------------------------------------ setup
    def _ask_storage_consent(self):
        if self.profile.asked_consent:
            return
        yes = messagebox.askyesno(
            "Synta - save progress?",
            "Save your level and per-topic progress on this computer, so Synta can personalise help?\n\n"
            f"Saved only here: {self.profile.path}\n"
            "Your code is never saved. You can delete everything any time with 'Forget my data'.")
        self.profile.set_consent(yes)

    def _make_non_activating(self):
        """Keep keyboard focus in the editor even when the overlay is clicked."""
        if sys.platform != "win32":
            return
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetParent(self.root.winfo_id())
            style = user32.GetWindowLongW(hwnd, -20)                       # GWL_EXSTYLE
            user32.SetWindowLongW(hwnd, -20, style | 0x08000000 | 0x00000080)  # NOACTIVATE | TOOLWINDOW
        except Exception:
            traceback.print_exc()

    def _build(self):
        r = self.root
        r.configure(bg=BG)
        r.attributes("-topmost", True)
        sw = r.winfo_screenwidth()
        r.geometry(f"410x640+{max(sw - 430, 0)}+50")
        r.minsize(380, 520)

        tk.Label(r, text="Synta", bg=BG, fg=FG, font=("Segoe UI", 15, "bold")).pack(anchor="w", padx=12, pady=(10, 0))
        tk.Label(r, text="Syntax Shift  -  Your code. Your pace. Your AI tutor.", bg=BG, fg=MUTED,
                 font=("Segoe UI", 9)).pack(anchor="w", padx=12)

        lv = tk.Frame(r, bg=BG)
        lv.pack(fill="x", padx=12, pady=(8, 2))
        tk.Label(lv, text="Level:", bg=BG, fg=MUTED).pack(side="left")
        self.level_var = tk.StringVar(value=self.profile.level)
        for lvl in learner.LEVELS:
            tk.Radiobutton(lv, text=lvl.title(), value=lvl, variable=self.level_var, command=self._on_level,
                           bg=BG, fg=FG, selectcolor=PANEL, activebackground=BG, activeforeground=FG).pack(side="left", padx=4)

        row = tk.Frame(r, bg=BG)
        row.pack(fill="x", padx=12, pady=4)
        self.btn_check = self._button(row, f"Check locally\n{config.HOTKEY_CHECK}", lambda: self._capture_async("check"))
        self.btn_ask = self._button(row, f"Ask AI tutor\n{config.HOTKEY_ASK}", lambda: self._capture_async("ask"), accent=True)
        self.btn_check.pack(side="left", expand=True, fill="x", padx=(0, 3))
        self.btn_ask.pack(side="left", expand=True, fill="x", padx=(3, 0))

        bar = tk.Frame(r, bg=BG)
        bar.pack(fill="x", padx=12, pady=(6, 0))
        tk.Label(bar, text="Help step:", bg=BG, fg=MUTED).pack(side="left")
        self.stage_labels = {}
        for s in STAGES:
            lab = tk.Label(bar, text=LABELS[s], bg=PANEL, fg=MUTED, padx=6, pady=1, font=("Segoe UI", 8))
            lab.pack(side="left", padx=2)
            self.stage_labels[s] = lab

        row2 = tk.Frame(r, bg=BG)
        row2.pack(fill="x", padx=12, pady=4)
        self.btn_more = self._button(row2, "More help >", lambda: self._capture_async("more"))
        self.btn_tech = self._button(row2, "Teach a technique", lambda: self._capture_async("technique"))
        self.btn_copy = self._button(row2, "Copy fix", self._copy_fix)
        for b in (self.btn_more, self.btn_tech, self.btn_copy):
            b.pack(side="left", expand=True, fill="x", padx=2)

        row3 = tk.Frame(r, bg=BG)
        row3.pack(fill="x", padx=12, pady=2)
        self.btn_fixed = self._button(row3, "I fixed it", self._mark_fixed)
        self.btn_expect = self._button(row3, "What I expected...", self._ask_expected)
        self.btn_reset = self._button(row3, "Start over", self._start_over)
        for b in (self.btn_fixed, self.btn_expect, self.btn_reset):
            b.pack(side="left", expand=True, fill="x", padx=2)

        chat_row = tk.Frame(r, bg=BG)
        chat_row.pack(fill="x", padx=12, pady=3)
        self._button(chat_row, "Chat with tutor", self._open_chat).pack(side="left", fill="x", expand=True, padx=(0, 3))
        self._button(chat_row, "Open website", self._open_website, accent=True).pack(side="left", fill="x", expand=True)

        box = tk.Frame(r, bg=BG)
        box.pack(fill="both", expand=True, padx=12, pady=6)
        self.text = tk.Text(box, wrap="word", bg=PANEL, fg=FG, relief="flat", padx=10, pady=8,
                            font=("Segoe UI", 10), state="disabled", insertbackground=FG)
        sb = ttk.Scrollbar(box, command=self.text.yview)
        self.text.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        for name, color, font in (("head", FG, ("Segoe UI", 11, "bold")), ("ok", GREEN, ("Segoe UI", 11, "bold")),
                                  ("error", RED, ("Segoe UI", 11, "bold")), ("muted", MUTED, ("Segoe UI", 9)),
                                  ("confirmed", GREEN, ("Segoe UI", 9, "bold")), ("inferred", AMBER, ("Segoe UI", 9, "bold")),
                                  ("code", FG, ("Consolas", 10))):
            self.text.tag_configure(name, foreground=color, font=font)

        bottom = tk.Frame(r, bg=BG)
        bottom.pack(fill="x", padx=12, pady=(0, 4))
        for label, cmd in (("Diagnostic", self.open_diagnostic), ("My path", self.show_path),
                           ("Forget my data", self._forget), ("Quit", self.quit)):
            self._button(bottom, label, cmd).pack(side="left", expand=True, fill="x", padx=2)
        self.status = tk.Label(r, text="", bg=BG, fg=MUTED, font=("Segoe UI", 8), anchor="w", justify="left", wraplength=380)
        self.status.pack(fill="x", padx=12, pady=(0, 8))
        self._update_buttons()

    def _open_chat(self):
        if self.chat_panel is None or not self.chat_panel.window.winfo_exists():
            self.chat_panel = ChatPanel(self.root, self.events, self.profile, *self.chat_context)
        self.chat_panel.window.lift()
        self.chat_panel.input.focus_force()

    def _synta_url(self):
        locator = config.data_dir().parent / "Synta" / "running.json"
        try:
            address = json.loads(locator.read_text(encoding="utf-8"))
            port = int(address["port"])
            origin = f"http://127.0.0.1:{port}"
            connection = http.client.HTTPConnection("127.0.0.1", port, timeout=2)
            try:
                body = {"action": "share", "code": self.snapshot_source, "title": self.chat_context[1][:300]}
                connection.request("POST", "/api/snapshot", json.dumps(body),
                                   {"Content-Type": "application/json", "Origin": origin,
                                    "X-Synta-Bridge": address["secret"]})
                response = connection.getresponse()
                if response.status == 200:
                    key = json.load(response).get("key", "")
                    if re.fullmatch("[0-9a-f]{48}", key):
                        return origin + "/workspace" + ("#snapshot=" + key if self.snapshot_source else "")
            finally:
                connection.close()
        except (OSError, ValueError, KeyError, http.client.HTTPException):
            return None

    def _open_website(self):
        try:
            url = self._synta_url()
            if not url:
                if self.website is None:
                    self.website = website.Website()
                    self.website.start()
                url = self.website.launch_url(*self.chat_context, self.profile.level)
            if not webbrowser.open(url):
                self.root.clipboard_clear()
                self.root.clipboard_append(url)
                messagebox.showinfo("Synta website", "Paste the copied link into your browser.", parent=self.root)
        except (OSError, website.sqlite3.Error) as exc:
            messagebox.showerror("Synta website", str(exc), parent=self.root)

    def _button(self, parent, text, command, accent=False):
        return tk.Button(parent, text=text, command=command, bg=ACCENT if accent else PANEL,
                         fg="#10131a" if accent else FG, activebackground=ACCENT, relief="flat",
                         padx=6, pady=4, font=("Segoe UI", 9), disabledforeground="#5a5f70")

    # ---------------------------------------------------------------- display
    def render(self, *segments):
        """segments: (text, tag) pairs."""
        t = self.text
        t.configure(state="normal")
        t.delete("1.0", "end")
        for s, tag in segments:
            t.insert("end", s, tag or ())
        t.configure(state="disabled")
        t.see("1.0")

    def _refresh_status(self):
        backend = f"Ollama ({config.get_model()})"
        save = "progress saved on this PC" if self.profile.consent else "progress not saved"
        warn = ""
        if self.hotkeys.failed:
            warn = " | A hotkey is taken by another app: use the buttons"
        self.status.configure(text=f"{self.profile.level.title()} | {backend} | {save}{warn}")

    def _update_buttons(self):
        has_help = bool(self.session.records)
        st = lambda cond: "normal" if cond and not self.waiting else "disabled"
        self.btn_more.configure(state=st(has_help and self.session.can_escalate))
        self.btn_tech.configure(state=st(has_help))
        self.btn_copy.configure(state=st(bool(self.last_fix)))
        self.btn_fixed.configure(state=st(has_help and not self.session.fixed))
        for s, lab in self.stage_labels.items():
            active = has_help and s == self.session.stage
            lab.configure(bg=ACCENT if active else PANEL, fg="#10131a" if active else MUTED)

    def _welcome(self):
        self.render(("Welcome", "head"),
                    ("\n\n1. Click into Notepad and write some Python (no need to save).\n"
                     f"2. Press {config.HOTKEY_CHECK} to check syntax offline.\n"
                     f"3. Press {config.HOTKEY_ASK} when you want an AI hint.\n\n"
                     "You choose how much help you get: Nudge, then Hint, then Explain, then Show solution.\n\n", None),
                    (self.profile.next_step_text() if self.profile.diagnostic else
                     "Tip: pick Intermediate to take a short diagnostic and get a personal learning path.", "muted"))

    # ---------------------------------------------------------- capture/events
    def _on_hotkey(self, hk_id):                      # runs on the hotkey thread
        action = {HK_CHECK: "check", HK_ASK: "ask"}.get(hk_id)
        if action:
            self._capture(action)

    def _capture(self, action):                       # editor still has focus here
        self.events.put(("snapshot", action, win_editor.read_active_editor()))

    def _capture_async(self, action):
        threading.Thread(target=self._capture, args=(action,), daemon=True).start()

    def _pump(self):
        try:
            while True:
                ev = self.events.get_nowait()
                try:
                    if ev[0] == "chat":
                        panel, question, reply = ev[1:]
                        if panel is self.chat_panel and panel.window.winfo_exists():
                            panel.receive(question, reply)
                    elif ev[0] == "snapshot":
                        self._on_snapshot(ev[1], ev[2])
                    elif ev[0] == "reply":
                        self._on_reply(ev[1], ev[2])
                except Exception as exc:
                    traceback.print_exc()
                    self.waiting = False
                    self.render(("Synta hit a problem", "error"), (f"\n\n{type(exc).__name__}: {exc}", None))
                    self._update_buttons()
        except queue.Empty:
            pass
        self.root.after(100, self._pump)

    # --------------------------------------------------------------- check path
    def _on_snapshot(self, action, snap):
        self.chat_context = ("", "General chat")
        self.snapshot_source = ""
        if not snap.ok:
            self.render(("Can't read the editor", "error"), (f"\n\n{snap.error}", None))
            return
        code = checker.normalize(snap.text)
        result = checker.check_python(code)
        if not result.empty:
            self.snapshot_source = code[:60000]
            self.chat_context = (tutor.build_input(code, result), snap.window_title or snap.app or "Editor")
        if action == "check":
            self._do_check(snap, result)
        else:
            self._do_ask(action, snap, code, result)

    def _do_check(self, snap, result):
        sig = checker.signature(result)
        before = self.session.outcome()
        prev = self.session.note_signature(sig)
        fixed_note = ""
        if prev is not None and before["helped"] and result.ok and prev not in ("ok", "empty"):
            if before["topic"] and before["attempt_logged"] and not before["fixed"]:
                self.profile.log_success(before["topic"], before["stage"])
            fixed_note = "That syntax error is fixed. Nice work.\n\n"
        head, body = checker.describe(result, self.profile.level)
        where = " - ".join(x for x in (snap.app, snap.window_title) if x)
        if result.empty:
            self.render((head, "head"), (f"\n\n{body}", None))
        else:
            tag = "ok" if result.ok else "error"
            self.render((("OK  " if result.ok else "ERROR  ") + head, tag),
                        ("\nConfirmed by Python's parser. Your code was not run.", "confirmed"),
                        (f"\n\n{fixed_note}{body}", None),
                        (f"\n\nRead from: {where or 'editor'} ({snap.method}, {result.line_count} lines)", "muted"))
        self._update_buttons()

    # ----------------------------------------------------------------- AI path
    def _do_ask(self, action, snap, code, result):
        if result.empty:
            self.render(("Nothing to ask about yet", "head"), ("\n\nThe editor is empty. Write some Python first.", None))
            return
        if self.waiting:
            return

        sig = checker.signature(result)
        before = self.session.outcome()
        prev = self.session.note_signature(sig)
        if prev is not None and before["helped"] and result.ok and prev not in ("ok", "empty"):
            if before["topic"] and before["attempt_logged"] and not before["fixed"]:
                self.profile.log_success(before["topic"], before["stage"])

        prev_index = self.session.stage_index
        if action == "more":
            if not self.session.escalate():
                self.render(("You are on the last step", "head"), ("\n\nTry 'Teach a technique', or 'Start over'.", None))
                return
            stage = self.session.stage
        elif action == "technique":
            stage = "technique"
        else:
            stage = self.session.stage
        if action == "ask" and self.session.is_repeat(code, stage):
            self.render((f"{LABELS[stage]} (same as before)", "head"),
                        ("\nYour code has not changed since this step, so I did not spend another request.", "muted"),
                        (f"\n\n{self.session.last_text()}\n\n", None),
                        ("Change something and press the hotkey again, or click 'More help >' for the next step.", "muted"))
            return

        ctx = dict(stage=stage, code=code, result=result, prev_index=prev_index, action=action,
                   level=self.profile.level, summary=self.profile.prompt_summary(),
                   hints=self.session.recent(3), expected=self.expected)
        self.waiting = True
        self._update_buttons()
        self.render(("Thinking...", "head"),
                    (f"\n{LABELS[stage]} for a {self.profile.level} learner. Your code is only being read, not run.", "muted"))
        threading.Thread(target=self._ask_worker, args=(ctx,), daemon=True).start()

    def _ask_worker(self, ctx):
        reply = tutor.ask_tutor(code=ctx["code"], check=ctx["result"], level=ctx["level"], stage=ctx["stage"],
                                learner_summary=ctx["summary"], hints_so_far=ctx["hints"], expected=ctx["expected"])
        self.events.put(("reply", ctx, reply))

    def _on_reply(self, ctx, reply):
        self.waiting = False
        result, stage = ctx["result"], ctx["stage"]
        if not reply.ok:
            if ctx["action"] == "more":
                self.session.stage_index = ctx["prev_index"]
            self.render((reply.error_title, "error"), (f"\n\n{reply.error_detail}", None))
            self._update_buttons()
            return
        self.session.record(stage, ctx["code"], reply.text)
        topic = reply.topic or checker.topic_for(result)
        if topic:
            self.session.topic = topic
            if not self.session.attempt_logged:
                self.session.attempt_logged = True
                self.profile.log_attempt(topic)
        if stage == "solution":
            self.last_fix = tutor.extract_code_block(reply.text)
        if result.ok:
            basis = ("Python found no syntax error. Anything below about behaviour is the tutor's inference. "
                     "Your code was NOT run.", "inferred")
        else:
            basis = (f"The syntax error on line {result.line} is confirmed by Python's parser. Your code was not run.", "confirmed")
        footer = ("Edit your code and press the hotkey again, or click 'More help >' when you want a bigger clue."
                  if stage != "solution" else
                  "Click 'Copy fix', then paste it yourself (Ctrl+A, Ctrl+V in the editor) when you are ready.")
        topic_line = f"Topic: {learner.TOPIC_LABELS[topic]}   |   " if topic else ""
        self.render((f"AI tutor - {LABELS[stage]}", "head"), (f"\n{topic_line}{self.profile.level.title()}", "muted"),
                    (f"\n{basis[0]}", basis[1]), (f"\n\n{reply.text}\n\n", None), (footer, "muted"))
        self._update_buttons()

    # ----------------------------------------------------------------- buttons
    def _copy_fix(self):
        if not self.last_fix:
            return
        self.root.clipboard_clear()
        self.root.clipboard_append(self.last_fix)
        self.root.update()
        self.render(("Fix copied", "head"),
                    ("\n\nIt is on your clipboard. Nothing in your editor was changed. Click into your editor, "
                     "select all (Ctrl+A) and paste (Ctrl+V) when you are ready, or compare it line by line first.", None))

    def _mark_fixed(self):
        o = self.session.outcome()
        if o["topic"] and o["attempt_logged"] and not self.session.fixed:
            self.profile.log_success(o["topic"], o["stage"])
        self.session.fixed = True
        self.render(("Nice work", "ok"), (f"\n\n{self.profile.next_step_text()}", None))
        self._update_buttons()

    def _ask_expected(self):
        ans = simpledialog.askstring(
            "What did you expect?",
            "Describe what the program should do, or give a sample input and the output you expect:",
            parent=self.root)
        if ans is not None:
            self.expected = ans.strip()
            self.render(("Saved for your next question", "head"), (f"\n\n{self.expected or '(cleared)'}", None))

    def _start_over(self):
        self.session.reset()
        self.last_fix = ""
        self.expected = ""
        self.render(("Starting fresh", "head"), ("\n\nThe next AI request begins again at Nudge.", "muted"))
        self._update_buttons()

    def _on_level(self):
        lvl = self.level_var.get()
        self.profile.set_level(lvl)
        self._refresh_status()
        if lvl == "intermediate" and not self.profile.diagnostic:
            if messagebox.askyesno("Intermediate level",
                                   f"Take the {config.DIAGNOSTIC_DEFAULT}-question diagnostic now? "
                                   "It builds your per-topic skill profile and learning path.", parent=self.root):
                self.open_diagnostic()

    def open_diagnostic(self):
        DiagnosticWindow(self)

    def show_path(self):
        rows = self.profile.rows()
        if not any(r.mastery is not None for r in rows):
            self.render(("No skill profile yet", "head"),
                        ("\n\nTake the diagnostic to build one. Ask the AI for help and your topics fill in too.", None))
            return
        segs = [("Your skill profile", "head"), ("\n", None)]
        for r in rows:
            if r.mastery is None:
                line = f"\n{r.label:<20} not assessed"
            else:
                filled = round(r.mastery * 10)
                line = f"\n{r.label:<20} {'#' * filled}{'.' * (10 - filled)} {r.mastery:>4.0%}  {r.band}"
            segs.append((line, "code"))
        segs.append(("\n\nYour learning path (weakest first; solid topics are skipped)", "head"))
        items = self.profile.path_items()
        if not items:
            segs.append(("\n\nEvery topic looks solid. Try the Advanced level.", None))
        for i, it in enumerate(items, 1):
            segs.append((f"\n\n{i}. {it.label}\n   {it.focus}", None))
        rec = self.profile.recommended_level()
        if rec:
            segs.append((f"\n\nSuggested level: {rec} (you choose).", "muted"))
        self.render(*segs)

    def _forget(self):
        if messagebox.askyesno("Forget my data", "Delete your saved level and progress? This cannot be undone.", parent=self.root):
            if self.chat_panel and self.chat_panel.window.winfo_exists():
                self.chat_panel.window.destroy()
            self.chat_panel = None
            self.chat_context = ("", "General chat")
            if self.website:
                self.website.clear_context()
            self.snapshot_source = ""
            self.profile.forget()
            self.session.reset()
            self.last_fix = ""
            self.level_var.set("beginner")
            self._refresh_status()
            self._update_buttons()
            self.render(("Your saved data was deleted", "head"), ("\n\nProgress is no longer saved on this computer.", None))

    def quit(self):
        try:
            self.hotkeys.stop()
            if self.website:
                self.website.shutdown()
                self.website.server_close()
        finally:
            self.root.destroy()

    def run(self):
        self.root.mainloop()


class DiagnosticWindow(tk.Toplevel):
    """A normal window (not the no-focus overlay) for the placement questions."""

    def __init__(self, app: App):
        super().__init__(app.root)
        self.app = app
        self.title("Synta diagnostic")
        self.configure(bg=BG)
        self.geometry("580x620+40+40")
        self.count = tk.StringVar(value=str(config.DIAGNOSTIC_DEFAULT))
        self.run: diagnostic.DiagnosticRun | None = None
        self._intro()
        self.lift()

    def _clear(self):
        for w in self.winfo_children():
            w.destroy()

    def _label(self, text, **kw):
        kw.setdefault("bg", BG)
        kw.setdefault("fg", FG)
        kw.setdefault("wraplength", 540)
        kw.setdefault("justify", "left")
        kw.setdefault("anchor", "w")
        lab = tk.Label(self, text=text, **kw)
        lab.pack(fill="x", padx=16, pady=4)
        return lab

    def _intro(self):
        self._clear()
        self._label("Placement diagnostic", font=("Segoe UI", 15, "bold"))
        self._label("Questions on syntax and types, control flow, functions and scope, data structures, debugging and "
                    "problem solving. You will predict output, fix bugs, explain snippets and choose approaches. "
                    "Nothing is run, and nothing is sent to the cloud.", fg=MUTED)
        row = tk.Frame(self, bg=BG)
        row.pack(anchor="w", padx=16, pady=8)
        tk.Label(row, text=f"How many questions ({config.DIAGNOSTIC_MIN}-{config.DIAGNOSTIC_MAX})?", bg=BG, fg=FG).pack(side="left")
        ttk.Spinbox(row, from_=config.DIAGNOSTIC_MIN, to=config.DIAGNOSTIC_MAX, width=5, textvariable=self.count).pack(side="left", padx=8)
        tk.Button(self, text="Start", command=self._start, bg=ACCENT, fg="#10131a", relief="flat", padx=14, pady=4).pack(anchor="w", padx=16, pady=8)

    def _start(self):
        try:
            n = int(self.count.get())
        except ValueError:
            n = config.DIAGNOSTIC_DEFAULT
        self.run = diagnostic.DiagnosticRun(n)
        self._question()

    def _question(self):
        self._clear()
        item = self.run.current
        q = item.question
        self._label(f"Question {self.run.index + 1} of {self.run.total}   ({learner.TOPIC_LABELS[q.topic]}, {q.kind})", fg=MUTED)
        self._label(q.prompt, font=("Segoe UI", 11, "bold"))
        if q.code:
            self._label(q.code, font=("Consolas", 11), bg=PANEL, justify="left")
        self.choice = tk.IntVar(value=-1)
        for i, opt in enumerate(item.options):
            tk.Radiobutton(self, text=opt, value=i, variable=self.choice, bg=BG, fg=FG, selectcolor=PANEL,
                           activebackground=BG, activeforeground=FG, wraplength=520, justify="left",
                           anchor="w", font=("Segoe UI", 10)).pack(fill="x", padx=24, pady=2)
        self.submit = tk.Button(self, text="Submit", command=self._submit, bg=ACCENT, fg="#10131a", relief="flat", padx=14, pady=4)
        self.submit.pack(anchor="w", padx=16, pady=10)

    def _submit(self):
        c = self.choice.get()
        if c < 0:
            return
        item = self.run.current
        correct = self.run.answer(c)
        self.submit.destroy()
        self._label("Correct" if correct else f"Not quite. Answer: {item.options[item.answer]}",
                    fg=GREEN if correct else RED, font=("Segoe UI", 11, "bold"))
        self._label(item.question.explain, fg=MUTED)
        tk.Button(self, text="Finish" if self.run.done else "Next", command=self._finish if self.run.done else self._question,
                  bg=ACCENT, fg="#10131a", relief="flat", padx=14, pady=4).pack(anchor="w", padx=16, pady=8)

    def _finish(self):
        self.app.profile.apply_diagnostic(self.run.summary())
        self.app.show_path()
        self.app._refresh_status()
        self._clear()
        self._label("Diagnostic complete", font=("Segoe UI", 15, "bold"))
        for topic, (c, n) in self.run.summary().items():
            self._label(f"{learner.TOPIC_LABELS[topic]}: {c} of {n}", font=("Consolas", 10))
        self._label(self.app.profile.next_step_text(), fg=MUTED)
        rec = self.app.profile.recommended_level()
        if rec:
            self._label(f"Suggested level: {rec}. You can change it in the overlay any time.", fg=MUTED)
        tk.Button(self, text="Close", command=self.destroy, bg=PANEL, fg=FG, relief="flat", padx=14, pady=4).pack(anchor="w", padx=16, pady=8)


def probe():
    print("Click into Notepad (or another editor) now. Reading in 5 seconds...")
    time.sleep(5)
    try:
        print(win_editor.describe_focus())
    except Exception as exc:
        print(f"describe_focus failed: {type(exc).__name__}: {exc}")
    snap = win_editor.read_active_editor()
    if snap.ok:
        print(f"OK via {snap.method}: {len(snap.text)} characters, {snap.text.count(chr(10)) + 1} lines")
        print("--- first 300 characters ---")
        print(snap.text[:300])
    else:
        print("FAILED:", snap.error)


def main():
    if "--probe" in sys.argv:
        probe()
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)     # crisp text on high-DPI screens
    except Exception:
        pass
    App().run()


if __name__ == "__main__":
    main()
