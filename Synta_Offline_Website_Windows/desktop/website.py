"""Local browser companion for the Synta overlay."""
import argparse
import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import webbrowser
from contextlib import closing
from http.cookies import SimpleCookie, CookieError
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import config
import tutor

ASSETS = Path(__file__).with_name("web")
SESSION_SECONDS = 8 * 60 * 60
FILES = {
    "/": ("index.html", "text/html"),
    "/style.css": ("style.css", "text/css"),
    "/app.js": ("app.js", "text/javascript"),
}


def password_hash(password, salt):
    return hashlib.scrypt(password.encode(), salt=salt, n=2**15, r=8, p=1, maxmem=64 * 1024 * 1024)


class Website(ThreadingHTTPServer):
    def __init__(self, directory=None):
        directory = config.data_dir() if directory is None else directory
        directory.mkdir(parents=True, exist_ok=True)
        self.database = directory / "website-account.sqlite3"
        with closing(self.connect()) as db, db:
            db.execute("CREATE TABLE IF NOT EXISTS account (id INTEGER PRIMARY KEY CHECK(id = 1), "
                       "name TEXT NOT NULL, salt BLOB NOT NULL, hash BLOB NOT NULL)")
        self.lock = threading.Lock()
        self.links = {}
        self.sessions = {}
        self.auth_slot = threading.Lock()
        self.chat_slot = threading.Lock()
        super().__init__(("127.0.0.1", 0), Handler)
        self.host = f"127.0.0.1:{self.server_port}"
        self.origin = f"http://{self.host}"
        self.cookie_name = f"codelume_session_{self.server_port}"

    def connect(self):
        return sqlite3.connect(self.database)

    def account(self):
        with closing(self.connect()) as db:
            return db.execute("SELECT name, salt, hash FROM account WHERE id = 1").fetchone()

    def start(self):
        threading.Thread(target=self.serve_forever, daemon=True).start()

    def launch_url(self, context="", title="General chat", level="beginner"):
        token = secrets.token_urlsafe(32)
        now = time.monotonic()
        with self.lock:
            self.links = {key: value for key, value in self.links.items() if value[0] > now}
            self.links[token] = (now + 600, context, title, level)
        return f"{self.origin}/#{token}"

    def clear_context(self):
        with self.lock:
            self.links.clear()
            for session in self.sessions.values():
                session["contexts"].clear()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass

    def send(self, status, body, mime, cookie=None):
        self.send_response(status)
        self.send_header("Content-Type", mime + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; "
                         "base-uri 'none'; form-action 'self'")
        if cookie is not None:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def json(self, status, data, cookie=None):
        self.send(status, json.dumps(data).encode(), "application/json", cookie)

    def error(self, status, message):
        self.json(status, {"error": message})

    def session(self):
        try:
            cookie = SimpleCookie(self.headers.get("Cookie", "")).get(self.server.cookie_name)
        except CookieError:
            cookie = None
        token = cookie.value if cookie else ""
        with self.server.lock:
            session = self.server.sessions.get(token)
            if session and session["expires"] <= time.monotonic():
                self.server.sessions.pop(token, None)
                session = None
            return token, session

    def do_GET(self):
        if self.headers.get("Host") != self.server.host:
            return self.error(403, "Open the website from the Synta overlay.")
        if self.path == "/api/session":
            _, session = self.session()
            with self.server.lock:
                name = session["name"] if session else None
            return self.json(200, {"name": name, "setup": not self.server.account(),
                                   "model": config.get_model()})
        if self.path in FILES:
            filename, mime = FILES[self.path]
            return self.send(200, (ASSETS / filename).read_bytes(), mime)
        self.error(404, "Page unavailable.")

    def do_POST(self):
        if (self.headers.get("Host") != self.server.host
                or self.headers.get("Origin") != self.server.origin):
            return self.error(403, "Open the website from the Synta overlay.")
        if self.headers.get_content_type() != "application/json":
            return self.error(415, "Expected JSON.")
        try:
            size = int(self.headers.get("Content-Length", "0"))
            if not 0 < size <= 450_000:
                return self.error(413, "This request is too large or empty.")
            self.connection.settimeout(10)
            data = json.loads(self.rfile.read(size))
            if not isinstance(data, dict):
                raise ValueError
        except (ValueError, OSError):
            return self.error(400, "Invalid request.")

        token, session = self.session()
        if self.path in ("/api/setup", "/api/login"):
            return self.authenticate(data, setup=self.path == "/api/setup", old_token=token)
        if not session:
            return self.error(401, "Sign in to continue.")
        if self.path == "/api/logout":
            with self.server.lock:
                self.server.sessions.pop(token, None)
            return self.json(200, {}, self.cookie("", 0))
        if self.path == "/api/context":
            link = data.get("link")
            if not isinstance(link, str):
                return self.error(400, "Invalid overlay link.")
            with self.server.lock:
                snapshot = self.server.links.pop(link, None)
                if snapshot and snapshot[0] > time.monotonic():
                    _, context, title, level = snapshot
                    if context:
                        contexts = session["contexts"]
                        if len(contexts) >= 20:
                            del contexts[next(iter(contexts))]
                        contexts[link] = (context, level)
                else:
                    snapshot = None
            if not snapshot:
                return self.error(410, "This overlay link has expired. Open a fresh link from the overlay.")
            return self.json(200, {"title": title if context else None, "context": link if context else None})
        if self.path == "/api/chat":
            return self.chat(data, session)
        self.error(404, "Page unavailable.")

    def cookie(self, value, age):
        return f"{self.server.cookie_name}={value}; Path=/; HttpOnly; SameSite=Strict; Max-Age={age}"

    def authenticate(self, data, setup, old_token):
        name, password = data.get("name"), data.get("password")
        if (not isinstance(name, str) or not isinstance(password, str)
                or not 1 <= len(name.strip()) <= 64 or len(password) > 256):
            return self.error(400, "Enter a valid username and password.")
        name = name.strip()
        if not self.server.auth_slot.acquire(blocking=False):
            return self.error(429, "Please try signing in again in a moment.")
        try:
            account = self.server.account()
            if setup:
                if account:
                    return self.error(409, "An account already exists. Reload the page to sign in.")
                link = data.get("link")
                with self.server.lock:
                    launch = self.server.links.get(link) if isinstance(link, str) else None
                if not launch or launch[0] <= time.monotonic():
                    return self.error(403, "Open a fresh website link from the overlay to create your account.")
                if len(password) < 12:
                    return self.error(400, "Use at least 12 characters for your password.")
                salt = secrets.token_bytes(16)
                try:
                    with closing(self.server.connect()) as db, db:
                        db.execute("INSERT INTO account VALUES (1, ?, ?, ?)",
                                   (name, salt, password_hash(password, salt)))
                except sqlite3.IntegrityError:
                    return self.error(409, "An account already exists. Reload the page to sign in.")
            else:
                if not account:
                    return self.error(409, "Create your account first.")
                matches = hmac.compare_digest(password_hash(password, account[1]), account[2])
                if not matches or name != account[0]:
                    time.sleep(0.5)
                    return self.error(401, "That username or password is incorrect.")
            token = secrets.token_urlsafe(32)
            now = time.monotonic()
            with self.server.lock:
                self.server.sessions = {
                    key: value for key, value in self.server.sessions.items()
                    if key != old_token and value["expires"] > now
                }
                self.server.sessions[token] = {"name": name, "expires": now + SESSION_SECONDS, "contexts": {}}
            return self.json(200, {"name": name}, self.cookie(token, SESSION_SECONDS))
        finally:
            self.server.auth_slot.release()

    def chat(self, data, session):
        question, history = data.get("question"), data.get("history", [])
        if not isinstance(question, str) or not 1 <= len(question.strip()) <= 4000:
            return self.error(400, "Enter a question up to 4,000 characters long.")
        if not isinstance(history, list) or len(history) > 16 or len(history) % 2:
            return self.error(400, "Invalid conversation history.")
        messages = []
        for i, message in enumerate(history):
            role = "assistant" if i % 2 else "user"
            if (not isinstance(message, dict) or message.get("role") != role
                    or not isinstance(message.get("content"), str) or len(message["content"]) > 4000):
                return self.error(400, "Invalid conversation history.")
            messages.append({"role": role, "content": message["content"]})
        context_id = data.get("context")
        if context_id is not None and not isinstance(context_id, str):
            return self.error(400, "Invalid editor snapshot.")
        with self.server.lock:
            attachment = session["contexts"].get(context_id)
        if context_id and not attachment:
            return self.error(410, "The editor snapshot has expired. Reopen it from the overlay or remove it.")
        context, level = attachment or ("", "beginner")
        if not self.server.chat_slot.acquire(blocking=False):
            return self.error(429, "The tutor is already answering. Try again in a moment.")
        try:
            reply = tutor.chat(question.strip(), messages, context, level, "")
        finally:
            self.server.chat_slot.release()
        if not reply.ok:
            return self.error(502, f"{reply.error_title}. {reply.error_detail}")
        self.json(200, {"reply": reply.text})


def main():
    parser = argparse.ArgumentParser(description="Run the local Synta website.")
    parser.add_argument("--no-browser", action="store_true", help="Print the URL without opening it.")
    args = parser.parse_args()
    try:
        with Website() as website:
            url = website.launch_url()
            print("Open this link in your browser if it does not open automatically.", flush=True)
            print(url, flush=True)
            print("Keep this window open while using Synta. Press Ctrl+C to stop.", flush=True)
            if not args.no_browser:
                webbrowser.open(url)
            website.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
