"""Built UI -> real HTTP API -> serial synthetic worker acceptance."""

from contextlib import contextmanager
from pathlib import Path
import socket
import threading
import time
import uvicorn
import pytest
from playwright.sync_api import expect
from app.main import create_app
from app.worker import Worker
from test_browser_live import real_browser


@contextmanager
def web_server(settings):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(
        uvicorn.Config(create_app(settings), log_level="error", access_log=False)
    )
    thread = threading.Thread(target=lambda: server.run(sockets=[sock]), daemon=True)
    thread.start()
    try:
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.03)
        assert server.started
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(5)
        sock.close()


def test_built_ui_completes_import_login_human_code_and_sync(settings):
    if not Path("frontend/dist/index.html").exists():
        pytest.skip("build frontend before UI acceptance")
    calls = []
    sync_calls = []
    voice_sync_started = threading.Event()
    release_voice_sync = threading.Event()
    voice_verified = threading.Event()

    def runner(account, target, control, saved):
        is_voice = target["kind"] == "chatgpt-web-voice"
        if not is_voice:
            assert voice_verified.is_set(), "CLI must wait for verified Voice sync"
        calls.append("voice" if is_voice else "cli")
        control.browser_ready()
        if is_voice:
            control.phase("email_code", "Enter verification code")
            code = control.wait_human("Enter verification code", phase="email_code_required")
            assert code == "123456"
        control.save_state({"cookies": [], "origins": []})
        control.browser_closed()
        return {
            "credential_type": "chatgpt_web" if is_voice else "codex_oauth",
            "identity": account["username"],
            "credential": {"access_token": "synthetic-voice-access"} if is_voice else {
                "access_token": "synthetic-access",
                "refresh_token": "synthetic-refresh",
                "id_token": "synthetic-id",
                "account_id": "synthetic",
            },
            "expires_at": time.time() + 7200,
        }

    def syncer(target, result, account, remote_id):
        is_voice = target["kind"] == "chatgpt-web-voice"
        sync_calls.append("voice" if is_voice else "cli")
        if is_voice:
            voice_sync_started.set()
            assert release_voice_sync.wait(10), "UI did not release synthetic Voice sync"
            voice_verified.set()
        else:
            assert voice_verified.is_set()
        return {"remote_id": remote_id, "verified": True}

    worker = Worker(settings, runner=runner, syncer=syncer)
    thread = None
    with web_server(settings) as url, real_browser() as browser:
        page = browser.new_page()
        page.goto(url)
        page.get_by_label("管理员密码").fill("synthetic-password-123")
        page.get_by_role("button", name="登录", exact=True).click()
        page.get_by_role("button", name="目标", exact=True).click()
        page.get_by_role("button", name="添加目标", exact=True).click()
        page.get_by_label("目标名称").fill("Synthetic CPA")
        page.get_by_label("服务地址", exact=True).fill("https://cpa.example.test")
        page.get_by_label("管理密钥", exact=True).fill("synthetic-management-secret")
        page.get_by_role("button", name="保存目标").click()
        expect(page.get_by_role("heading", name="Synthetic CPA")).to_be_visible()
        page.get_by_role("button", name="添加目标", exact=True).click()
        page.get_by_label("目标名称").fill("Synthetic Voice")
        page.get_by_label("类型", exact=True).select_option("chatgpt-web-voice")
        page.get_by_label("服务地址", exact=True).fill("https://voice.example.test")
        page.get_by_label("管理员用户名（留空保留）", exact=True).fill("synthetic-admin")
        page.get_by_label("管理员密码（留空保留）", exact=True).fill("synthetic-voice-secret")
        page.get_by_role("button", name="保存目标").click()
        expect(page.get_by_role("heading", name="Synthetic Voice")).to_be_visible()
        page.get_by_role("button", name="账号", exact=True).click()
        page.get_by_role("button", name="导入账号", exact=True).click()
        page.get_by_label("账号文本").fill(
            "synthetic@example.com----synthetic-password----JBSWY3DPEHPK3PXP"
        )
        page.get_by_role("button", name="预览导入").click()
        expect(page.get_by_text("第 1 行：可导入")).to_be_visible()
        page.get_by_role("button", name="确认导入").click()
        expect(
            page.get_by_role("heading", name="synthetic@example.com")
        ).to_be_visible()
        page.get_by_role("button", name="编辑与绑定").click()
        page.get_by_label("网络路由").select_option("direct")
        page.get_by_label("Synthetic CPA", exact=True).check()
        page.get_by_label("Synthetic Voice", exact=True).check()
        page.get_by_role("button", name="保存账号").click()
        page.get_by_role("button", name="登录 Codex", exact=True).click()
        expect(page.get_by_label("第一步：ChatGPT Web Voice")).to_have_value("2")
        expect(page.get_by_label("第二步：CLIProxyAPI")).to_have_value("1")
        page.get_by_role("dialog").get_by_role(
            "button", name="登录 Codex", exact=True
        ).click()
        expect(page.get_by_role("heading", name="任务 #1")).to_be_visible()
        thread = threading.Thread(target=worker.run, daemon=True)
        thread.start()
        try:
            expect(page.get_by_label("验证码")).to_be_visible(timeout=10000)
            expect(page.get_by_role("button", name="账号窗口", exact=True)).to_be_enabled()
            assert calls == ["voice"]
            assert sync_calls == []
            page.get_by_label("验证码").fill("123456")
            page.get_by_role("button", name="提交验证码").click()
            assert voice_sync_started.wait(5)
            assert calls == ["voice"], "CLI ran while Voice sync was still pending"
            assert sync_calls == ["voice"]
            release_voice_sync.set()
            page.get_by_role("button", name="任务 #2", exact=False).click()
            expect(page.get_by_role("heading", name="任务 #2")).to_be_visible()
            expect(
                page.locator(".task-detail").get_by_text("已完成", exact=True).first
            ).to_be_visible(timeout=10000)
            assert calls == ["voice", "cli"]
            assert sync_calls == ["voice", "cli"]
            page.reload()
            expect(page.get_by_role("heading", name="任务 #2")).to_be_visible()
            expect(
                page.get_by_text("Downstream synchronization verified").first
            ).to_be_visible()
            assert "synthetic-refresh" not in page.content()
        finally:
            release_voice_sync.set()
            worker.stopping.set()
            thread.join(6)
        page.close()
