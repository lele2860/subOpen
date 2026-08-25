#!/usr/bin/env python3
"""Temporary password-gated subscription access service.

The service deliberately keeps the subscription file outside of the public
filesystem route. Nginx proxies only the login page/API and the legacy
subscription path to this loopback-only service.
"""

from __future__ import annotations

import argparse
import hmac
import html
import json
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, urlsplit


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
  <p>输入访问密码后开启此配置文件的临时订阅链接，有效期 10 分钟。链接到期后会自动失效，也可以提前关闭。</p>
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
  let token = "";
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
    token = "";
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
      token = data.token;
      expiresAt = data.expires_at * 1000;
      link.href = new URL(data.url, window.location.origin).href;
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
    if (!link.href || !token) return;
    try {
      await navigator.clipboard.writeText(link.href);
      setMessage("临时链接已复制。", false);
    } catch {
      setMessage("浏览器不允许自动复制，请手动复制上方链接。", true);
    }
  });

  closeButton.addEventListener("click", async () => {
    if (!token) return;
    closeButton.disabled = true;
    try {
      const response = await fetch("/sub-access/api/revoke", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token })
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
    required = ("PASSWORD", "LINK_TOKEN", "FILE_PATH", "SUB_PATH", "BIND", "PORT", "TTL_SECONDS")
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise RuntimeError("missing config keys: " + ", ".join(missing))
    if not values["SUB_PATH"].startswith("/") or ".." in values["SUB_PATH"]:
        raise RuntimeError("invalid SUB_PATH")
    if len(values["LINK_TOKEN"]) < 32:
        raise RuntimeError("LINK_TOKEN is too short")
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
        self.token_lock = threading.Lock()
        self.failed_attempts: dict[str, tuple[int, float]] = {}
        self.failed_lock = threading.Lock()

    def purge_expired(self, now: float | None = None) -> None:
        now = now or time.time()
        with self.token_lock:
            if self.active_until and self.active_until <= now:
                self.active_until = 0.0

    def issue_token(self) -> tuple[str, int]:
        now = time.time()
        expires = now + int(self.config["TTL_SECONDS"])
        with self.token_lock:
            self.active_until = expires
        return self.config["LINK_TOKEN"], int(expires)

    def valid_token(self, token: str) -> bool:
        self.purge_expired()
        if not hmac.compare_digest(token, self.config["LINK_TOKEN"]):
            return False
        with self.token_lock:
            return self.active_until > time.time()

    def revoke_token(self, token: str) -> bool:
        if not hmac.compare_digest(token, self.config["LINK_TOKEN"]):
            return False
        with self.token_lock:
            was_active = self.active_until > time.time()
            self.active_until = 0.0
            return was_active

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

    def serve_subscription(self, token: str, head_only: bool = False) -> None:
        if not token:
            self.send_response_body(401, b"subscription access is locked\n")
            return
        if not self.server.valid_token(token):
            self.send_response_body(403, b"subscription link is invalid or expired\n")
            return
        try:
            body = Path(self.server.config["FILE_PATH"]).read_bytes()
        except OSError:
            self.send_response_body(503, b"subscription file is temporarily unavailable\n")
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
            token = parse_qs(parsed.query).get("token", [""])[0]
            self.serve_subscription(token, head_only)
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
            token, expires_at = self.server.issue_token()
            url = self.server.config["SUB_PATH"] + "?token=" + quote(token, safe="")
            self.send_json(
                200,
                {
                    "ok": True,
                    "token": token,
                    "expires_at": expires_at,
                    "ttl_seconds": int(self.server.config["TTL_SECONDS"]),
                    "url": url,
                },
            )
            return

        if path == "/sub-access/api/revoke":
            token = payload.get("token", "")
            if not isinstance(token, str) or not token or len(token) > 256:
                self.send_json(400, {"ok": False, "error": "临时链接无效"})
                return
            if not self.server.revoke_token(token):
                self.send_json(404, {"ok": False, "error": "链接已失效"})
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
