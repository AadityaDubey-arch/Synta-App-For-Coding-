"""A focusable chat window alongside the non-activating overlay."""
import threading
import tkinter as tk
from tkinter import ttk
from tkinter.scrolledtext import ScrolledText

import tutor


class ChatPanel:
    def __init__(self, parent, events, profile, context, title):
        self.events = events
        self.profile = profile
        self.context = context
        self.history = []
        self.pending = False
        self.window = tk.Toplevel(parent)
        self.window.title("Synta · Chat with tutor")
        self.window.geometry("470x500")
        self.window.attributes("-topmost", True)
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(1, weight=1)
        label = f"Code snapshot: {title}" if context else "General chat · no code attached"
        ttk.Label(self.window, text=label, wraplength=430).grid(row=0, sticky="w", padx=12, pady=8)
        self.log = ScrolledText(self.window, wrap="word", state="disabled", width=40, height=12)
        self.log.grid(row=1, sticky="nsew", padx=12)
        ttk.Label(self.window, text="Describe your problem or ask a follow-up").grid(row=2, sticky="w", padx=12, pady=4)
        self.input = tk.Text(self.window, height=4, width=40, wrap="word")
        self.input.grid(row=3, sticky="ew", padx=12)
        self.send_button = ttk.Button(self.window, text="Send · Ctrl+Enter", command=self.send)
        self.send_button.grid(row=4, sticky="e", padx=12, pady=8)
        self.input.bind("<Control-Return>", self.send)

    def append(self, who, text):
        self.log.configure(state="normal")
        self.log.insert("end", f"{who}\n{text}\n\n")
        self.log.configure(state="disabled")
        self.log.see("end")

    def send(self, event=None):
        question = self.input.get("1.0", "end-1c").strip()
        if not question or self.pending:
            return "break"
        self.pending = True
        self.input.configure(state="disabled")
        self.send_button.configure(state="disabled", text="Thinking…")
        self.append("You", question)
        args = (question, self.history[-16:], self.context, self.profile.level, self.profile.prompt_summary())
        threading.Thread(target=self.worker, args=args, daemon=True).start()
        return "break"

    def worker(self, question, history, context, level, profile):
        try:
            reply = tutor.chat(question, history, context, level, profile)
        except Exception as exc:
            reply = tutor.TutorReply(False, error_title="Chat request failed", error_detail=type(exc).__name__)
        self.events.put(("chat", self, question, reply))

    def receive(self, question, reply):
        self.pending = False
        self.input.configure(state="normal")
        self.send_button.configure(state="normal", text="Send · Ctrl+Enter")
        if reply.ok:
            self.input.delete("1.0", "end")
            self.history.extend([{"role": "user", "content": question},
                                 {"role": "assistant", "content": reply.text}])
            self.append("Synta", reply.text)
        else:
            self.append("Connection status", reply.error_title + "\n" + reply.error_detail)
