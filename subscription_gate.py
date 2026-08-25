#!/usr/bin/env python3
"""Temporary password-gated subscription access service.

The subscription URL is fixed and intentionally has no query-string token.
The service exposes the public filename only while access is active. When the
window closes, the public filename is removed and the file remains under a
hidden filename.
"""

from __future__ import annotations

import argparse
import hmac
import html
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


MAX_BODY_BYTES = 64 * 1024
HTML_PAGE = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>订阅临时访问</title>
  <style>
    :root { color-scheme: light dark; font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f4f7fb; color: #18212f; }
    main { width: min(92vw, 520px); box-sizing: border-box; padding: 28px; border-radius: 18px; background: white; box-shadow: 0 12px 36px #18212f1c; }
    h1 { margin: 0 0 10px; font-size: 1.45rem; }
    p { line-height: 1.6; color: #536174; }
    label { display: block; margin: 20px 0 8px; font-weight: 600; }
    input { width: 100%; box-sizing: border-box; padding: 12px 13px; border: 1px solid #c8d1df; border-radius: 10px; font-size: 1rem; }
    button { margin-top: 14px; border: 0; border-radius: 10px; padding: 11px 15px; font-size: .95rem; cursor: pointer; background: #2463eb; color: white; }
    button.secondary { background: #667085; }
    button.danger { background: #c0392b; }
    button:disabled { opacity: .55; cursor: not-allowed; }
    .message { min-height: 1.5em; margin-top: 14px; color: #2463eb; }
    .error { color: #c0392b; }
    .hidden { display: none; }
    .panel { margin-top: 22px; padding: 16px; border-radius: 12px; background: #eef4ff; }
    .countdown { font-size: 2rem; font-variant-numeric: tabular-nums; font-weight: 700; color: #174ea6; }
    a { word-break: break-all; color: #174ea6; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    @media (prefers-color-scheme: dark) {
      body { background: #10141c; color: #eef2f7; }
      main { background: #1b2330; box-shadow: 0 12px 36px #0005; }
      p { color: #acb7c7; }
      input { background: #121923; color: #eef2f7; border-color: #46546a; }
      .panel { background: #233452; }
      .countdown, a { color: #9fc0ff; }
    }
  </style>
</head>
<body>
<main>
  <h1>订阅临时访问</h1>
  <p>输入访问密码后开启固定订阅链接，有效期 10 分钟。链接到期后会自动失效，也可以提前关闭。</p>
  <form id="unlock-form">
    <label for="password">访问密码</label>
    <input id="password" name="password" type="password" autocomplete="current-password" required>
    <button id="unlock-button" type="submit">开启 10 分钟访问</button>
  </form>
  <div id="message" class="message" role="status"></div>
  <section id="panel" class="panel hidden">
    <div>剩余时间</div>
    <div id="countdown" class="countdown">10:00</div>
    <p><a id="subscription-link" href="#" target="_blank" rel="noreferrer noopener"></a></p>
    <div class="actions">
      <button id="copy-button" type="button" class="secondary">复制临时链接</button>
      <button id="close-button" type="button" class="danger">提前关闭访问</button>
    </div>
  </section>
</main>
<script>
(() => {
  const form = document.getElementById("unlock-form");
  const password = document.getElementById("password");
  const unlockButton = document.getElementById("unlock-button");
  const message = document.getElementById("message");
  const panel = document.getElementById("panel");
  const countdown = document.getElementById("countdown");
  const link = document.getElementById("subscription-link");
  const copyButton = document.getElementById("copy-button");
  const closeButton = document.getElementById("close-button");
  let subscriptionUrl = "";
  let expiresAt = 0;
  let timer = 0;

  function setMessage(text, error) {
    message.textContent = text;
    message.className = error ? "message error" : "message";
  }

  function formatSeconds(seconds) {
    const minutes = Math.floor(seconds / 60);
    const rest = seconds % 60;
    return String(minutes).padStart(2, "0") + ":" + String(rest).padStart(2, "0");
  }

  function closeLocal(text) {
    if (timer) window.clearInterval(timer);
    timer = 0;
    subscriptionUrl = "";
    countdown.textContent = "00:00";
    link.removeAttribute("href");
    link.textContent = text || "访问链接已关闭";
    copyButton.disabled = true;
    closeButton.disabled = true;
  }

  function tick() {
    const left = Math.max(0, Math.ceil((expiresAt - Date.now()) / 1000));
    countdown.textContent = formatSeconds(left);
    if (left <= 0) {
      closeLocal("访问链接已自动失效");
      setMessage("10 分钟已到，订阅文件访问已关闭。", true);
    }
  }

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    unlockButton.disabled = true;
    setMessage("正在验证…", false);
    try {
      const response = await fetch("/sub-access/api/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ password: password.value })
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "密码错误");
      expiresAt = data.expires_at * 1000;
      subscriptionUrl = new URL(data.url, window.location.origin).href;
      link.href = subscriptionUrl;
      link.textContent = link.href;
      panel.classList.remove("hidden");
      password.value = "";
      setMessage("验证成功。请在有效期内使用临时订阅链接。", false);
      if (timer) window.clearInterval(timer);
      copyButton.disabled = false;
      closeButton.disabled = false;
      tick();
      timer = window.setInterval(tick, 1000);
    } catch (error) {
      setMessage(error.message || "请求失败，请稍后重试。", true);
    } finally {
      unlockButton.disabled = false;
    }
  });

  copyButton.addEventListener("click", async () => {
    if (!subscriptionUrl) return;
    try {
      await navigator.clipboard.writeText(subscriptionUrl);
      setMessage("临时链接已复制。", false);
    } catch {
      setMessage("浏览器不允许自动复制，请手动复制上方链接。", true);
    }
  });

  closeButton.addEventListener("click", async () => {
    closeButton.disabled = true;
    try {
      const response = await fetch("/sub-access/api/revoke", {
        method: "POST",
      });
      if (!response.ok) throw new Error("关闭请求失败");
      closeLocal("访问链接已提前关闭");
      setMessage("订阅文件访问已关闭。", false);
    } catch (error) {
      closeButton.disabled = false;
      setMessage(error.message || "关闭请求失败。", true);
    }
  });
})();
</script>
</body>
</html>
"""


def load_config(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    required = (
        "PASSWORD",
        "FILE_PATH",
        "LOCKED_FILE_PATH",
        "SUB_PATH",
        "BIND",
        "PORT",
        "TTL_SECONDS",
    )
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError("missing config keys: " + ", ".join(missing))
    if not values["SUB_PATH"].startswith("/") or ".." in values["SUB_PATH"]:
        raise RuntimeError("invalid SUB_PATH")
    public_path = Path(values["FILE_PATH"])
    locked_path = Path(values["LOCKED_FILE_PATH"])
    if not public_path.is_absolute() or not locked_path.is_absolute():
        raise RuntimeError("FILE_PATH and LOCKED_FILE_PATH must be absolute")
    if os.path.abspath(public_path) == os.path.abspath(locked_path):
        raise RuntimeError("FILE_PATH and LOCKED_FILE_PATH must be different")
    if public_path.parent != locked_path.parent:
        raise RuntimeError("FILE_PATH and LOCKED_FILE_PATH must share a directory")
    int(values["PORT"])
    int(values["TTL_SECONDS"])
    return values


class GateServer(ThreadingHTTPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, address, handler, config):
        super().__init__(address, handler)
        self.config = config
        self.active_until = 0.0
        self.state_lock = threading.RLock()
        self.stop_expiry = threading.Event()
        self.failed_attempts: dict[str, tuple[int, float]] = {}
        self.failed_lock = threading.Lock()
        with self.state_lock:
            self.lock_file()
        self.expiry_thread = threading.Thread(target=self.expiry_loop, name="subscription-expiry", daemon=True)
        self.expiry_thread.start()

    @property
    def public_path(self) -> Path:
        return Path(self.config["FILE_PATH"])

    @property
    def locked_path(self) -> Path:
        return Path(self.config["LOCKED_FILE_PATH"])

    @staticmethod
    def path_exists(path: Path) -> bool:
        return path.exists() or path.is_symlink()

    def lock_file(self) -> None:
        """Hide the public filename while access is not active.

        The real file stays under LOCKED_FILE_PATH while access is closed.
        During an active window it is moved to FILE_PATH, and it is moved back
        when the window closes.
        """
        public = self.public_path
        locked = self.locked_path
        if public.is_symlink():
            public.unlink()
        if public.exists():
            if self.path_exists(locked):
                raise RuntimeError("both FILE_PATH and LOCKED_FILE_PATH exist")
            os.replace(public, locked)
        if not locked.is_file():
            raise RuntimeError("locked subscription file is missing")

    def expose_file(self) -> None:
        public = self.public_path
        locked = self.locked_path
        if public.exists() and not self.path_exists(locked):
            return
        if public.is_symlink():
            public.unlink()
        if public.exists():
            raise RuntimeError("public subscription filename is already occupied")
        if not locked.is_file():
            raise RuntimeError("locked subscription file is missing")
        os.replace(locked, public)

    def hide_file(self) -> None:
        public = self.public_path
        locked = self.locked_path
        if public.is_symlink():
            public.unlink()
            return
        if public.exists():
            if self.path_exists(locked):
                raise RuntimeError("both FILE_PATH and LOCKED_FILE_PATH exist")
            os.replace(public, locked)

    def expire_if_due(self, now: float | None = None) -> None:
        now = now or time.time()
        if self.active_until and self.active_until <= now:
            self.active_until = 0.0
            try:
                self.hide_file()
            except OSError as exc:
                sys.stderr.write("cannot hide expired subscription file: %s\n" % exc)

    def issue_access(self) -> int:
        with self.state_lock:
            self.expire_if_due()
            self.expose_file()
            expires = int(time.time()) + int(self.config["TTL_SECONDS"])
            self.active_until = float(expires)
            return expires

    def access_active(self) -> bool:
        with self.state_lock:
            self.expire_if_due()
            return self.active_until > time.time() and self.public_path.is_file()

    def revoke_access(self) -> bool:
        with self.state_lock:
            was_active = self.active_until > time.time() or self.public_path.is_file()
            self.active_until = 0.0
            self.hide_file()
            return was_active

    def expiry_loop(self) -> None:
        while not self.stop_expiry.wait(0.5):
            with self.state_lock:
                should_hide = bool(self.active_until and self.active_until <= time.time())
                if should_hide:
                    self.active_until = 0.0
                if should_hide or (not self.active_until and self.path_exists(self.public_path)):
                    try:
                        self.hide_file()
                    except OSError as exc:
                        sys.stderr.write("cannot hide subscription file: %s\n" % exc)

    def server_close(self) -> None:
        self.stop_expiry.set()
        if hasattr(self, "expiry_thread"):
            self.expiry_thread.join(timeout=2)
        super().server_close()

    def verify_password(self, candidate: str) -> bool:
        return hmac.compare_digest(candidate, self.config["PASSWORD"])

    def login_allowed(self, client_ip: str) -> tuple[bool, int]:
        now = time.time()
        with self.failed_lock:
            count, blocked_until = self.failed_attempts.get(client_ip, (0, 0.0))
            if blocked_until > now:
                return False, int(blocked_until - now) + 1
            if blocked_until:
                self.failed_attempts.pop(client_ip, None)
        return True, 0

    def record_failure(self, client_ip: str) -> None:
        now = time.time()
        with self.failed_lock:
            count, _ = self.failed_attempts.get(client_ip, (0, 0.0))
            count += 1
            blocked_until = now + 600 if count >= 5 else 0.0
            self.failed_attempts[client_ip] = (count, blocked_until)

    def clear_failures(self, client_ip: str) -> None:
        with self.failed_lock:
            self.failed_attempts.pop(client_ip, None)


class Handler(BaseHTTPRequestHandler):
    server: GateServer
    protocol_version = "HTTP/1.1"

    def log_message(self, format_string: str, *args) -> None:
        request_path = "-"
        try:
            request_line = self.requestline.split(" ", 2)
            if len(request_line) >= 2:
                request_path = urlsplit(request_line[1]).path
        except Exception:
            pass
        sys.stderr.write(
            "%s %s %s %s\n"
            % (self.client_address[0], self.command, request_path, args[1] if len(args) > 1 else "-")
        )

    def client_ip(self) -> str:
        forwarded = self.headers.get("X-Real-IP", "")
        return forwarded.split(",", 1)[0].strip() or self.client_address[0]

    def send_response_body(
        self,
        status: int,
        body: bytes,
        content_type: str = "text/plain; charset=utf-8",
        extra_headers: dict[str, str] | None = None,
        head_only: bool = False,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Connection", "close")
        for key, value in (extra_headers or {}).items():
            self.send_header(key, value)
        self.end_headers()
        self.close_connection = True
        if not head_only and body:
            try:
                self.wfile.write(body)
            except BrokenPipeError:
                pass

    def send_json(self, status: int, payload: dict, head_only: bool = False) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response_body(status, body, "application/json; charset=utf-8", head_only=head_only)

    def read_json(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("invalid content length")
        if length < 0 or length > MAX_BODY_BYTES:
            raise OverflowError("request body too large")
        raw = self.rfile.read(length)
        if not raw:
            return {}
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("JSON object required")
        return value

    def serve_login_page(self, head_only: bool = False) -> None:
        body = HTML_PAGE.encode("utf-8")
        self.send_response_body(200, body, "text/html; charset=utf-8", head_only=head_only)

    def serve_subscription(self, head_only: bool = False) -> None:
        if not self.server.access_active():
            self.send_response_body(404, b"subscription file not found\n")
            return
        try:
            body = self.server.public_path.read_bytes()
        except OSError:
            self.send_response_body(404, b"subscription file not found\n")
            return
        self.send_response_body(
            200,
            body,
            "text/plain; charset=utf-8",
            {"Content-Disposition": 'inline; filename="config.yaml"'},
            head_only=head_only,
        )

    def route_get(self, head_only: bool = False) -> None:
        parsed = urlsplit(self.path)
        path = parsed.path
        if path == "/sub-access":
            self.send_response_body(301, b"", extra_headers={"Location": "/sub-access/"}, head_only=head_only)
            return
        if path == "/sub-access/":
            self.serve_login_page(head_only)
            return
        if path == self.server.config["SUB_PATH"]:
            self.serve_subscription(head_only)
            return
        if path == "/healthz":
            self.send_response_body(200, b"ok\n", head_only=head_only)
            return
        self.send_response_body(404, b"not found\n", head_only=head_only)

    def route_post(self) -> None:
        path = urlsplit(self.path).path
        try:
            payload = self.read_json()
        except OverflowError:
            self.send_json(413, {"ok": False, "error": "请求体过大"})
            return
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "error": "请求格式无效"})
            return

        if path == "/sub-access/api/login":
            client_ip = self.client_ip()
            allowed, _ = self.server.login_allowed(client_ip)
            if not allowed:
                self.send_json(429, {"ok": False, "error": "尝试次数过多，请稍后再试"})
                return
            candidate = payload.get("password", "")
            if not isinstance(candidate, str) or not self.server.verify_password(candidate):
                self.server.record_failure(client_ip)
                self.send_json(401, {"ok": False, "error": "密码错误"})
                return
            self.server.clear_failures(client_ip)
            try:
                expires_at = self.server.issue_access()
            except (OSError, RuntimeError) as exc:
                sys.stderr.write("cannot expose subscription file: %s\n" % exc)
                self.send_json(503, {"ok": False, "error": "订阅文件暂时无法开启"})
                return
            self.send_json(
                200,
                {
                    "ok": True,
                    "expires_at": expires_at,
                    "ttl_seconds": int(self.server.config["TTL_SECONDS"]),
                    "url": self.server.config["SUB_PATH"],
                },
            )
            return

        if path == "/sub-access/api/revoke":
            try:
                self.server.revoke_access()
            except (OSError, RuntimeError) as exc:
                sys.stderr.write("cannot hide subscription file: %s\n" % exc)
                self.send_json(503, {"ok": False, "error": "订阅文件暂时无法关闭"})
                return
            self.send_json(200, {"ok": True})
            return

        self.send_json(404, {"ok": False, "error": "not found"})

    def do_GET(self) -> None:
        self.route_get(False)

    def do_HEAD(self) -> None:
        self.route_get(True)

    def do_POST(self) -> None:
        self.route_post()

    def do_OPTIONS(self) -> None:
        self.send_response_body(204, b"")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = load_config(args.config)
    server = GateServer((config["BIND"], int(config["PORT"])), Handler, config)
    sys.stderr.write("subscription gate listening on %s:%s\n" % (config["BIND"], config["PORT"]))
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

