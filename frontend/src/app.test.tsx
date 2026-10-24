// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { App } from "./main";

const response = (data: unknown, status = 200) =>
  Promise.resolve(
    new Response(JSON.stringify(data), {
      status,
      headers: { "Content-Type": "application/json" },
    }),
  );
beforeEach(() => {
  window.history.replaceState(null, "", "/");
  vi.stubGlobal("fetch", vi.fn());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
describe("management interactions", () => {
  it("logs in using a cookie session and sends CSRF on account creation", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path.endsWith("/auth/session"))
        return response({ detail: "Authentication required" }, 401);
      if (path.endsWith("/auth/login"))
        return response({ csrf_token: "synthetic-token" });
      if (path.endsWith("/accounts") && init?.method === "POST")
        return response({ id: 1 });
      if (path.endsWith("/accounts")) return response({ accounts: [] });
      if (path.endsWith("/targets")) return response({ targets: [{ id: 1, name: "CLIProxyAPI", kind: "cliproxyapi" }, { id: 2, name: "Voice", kind: "chatgpt-web-voice" }] });
      return response({ tasks: [] });
    });
    render(<App />);
    const user = userEvent.setup();
    await user.type(
      await screen.findByLabelText("管理员密码"),
      "synthetic-password",
    );
    await user.click(screen.getByRole("button", { name: /^登录$/ }));
    await user.click(await screen.findByRole("button", { name: "添加账号" }));
    await user.type(
      screen.getByLabelText("账号邮箱"),
      "synthetic@example.test",
    );
    await user.type(
      screen.getByLabelText("密码", { exact: true }),
      "synthetic-password",
    );
    expect(screen.getByLabelText("网络路由")).toHaveProperty("value", "proxy");
    expect(screen.getByLabelText("CLIProxyAPI")).toHaveProperty("checked", true);
    expect(screen.getByLabelText("Voice")).toHaveProperty("checked", false);
    await user.type(screen.getByLabelText("代理 URL"), "socks5://user:p%40ss@proxy.example.test:1080");
    await user.click(screen.getByRole("button", { name: "保存账号" }));
    await waitFor(() =>
      expect(
        calls.some(
          (c) => c.path.endsWith("/accounts") && c.init?.method === "POST",
        ),
      ).toBe(true),
    );
    const call = calls.find(
      (c) => c.path.endsWith("/accounts") && c.init?.method === "POST",
    )!;
    expect(call.init?.headers).toMatchObject({
      "X-CSRF-Token": "synthetic-token",
    });
    expect(JSON.parse(String(call.init?.body))).toMatchObject({
      username: "synthetic@example.test",
      route_type: "proxy",
      target_ids: [1],
      proxy: { server: "socks5://proxy.example.test:1080", username: "user", password: "p@ss" },
    });
  });
  it("shows a retryable resource failure without claiming the account list is empty", async () => {
    vi.mocked(fetch).mockImplementation((input) =>
      String(input).endsWith("/auth/session")
        ? response({ csrf_token: "synthetic-token" })
        : response({ detail: "Database temporarily unavailable" }, 503),
    );
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("Database temporarily unavailable"),
    );
    expect(screen.queryByText("还没有账号。请添加或导入账号。")).toBeNull();
    expect(screen.getByRole("button", { name: "重试" })).toBeTruthy();
  });
  it("shows connection failure instead of silently presenting the login form", async () => {
    vi.mocked(fetch).mockRejectedValue(new Error("Network unavailable"));
    render(<App />);
    expect(await screen.findByRole("alert")).toHaveProperty(
      "textContent",
      expect.stringContaining("Network unavailable"),
    );
    expect(screen.queryByLabelText("管理员密码")).toBeNull();
  });
  it("keeps waiting-task code actions in one view and uses idempotent submissions", async () => {
    const task = {
      id: 7,
      account_id: 2,
      target_id: 3,
      state: "waiting_human",
      phase: "等待验证码",
    };
    const calls: { path: string; init?: RequestInit }[] = [];
    class SyntheticEvents {
      addEventListener() {}
      close() {}
    }
    vi.stubGlobal("EventSource", SyntheticEvents);
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path.endsWith("/auth/session"))
        return response({ csrf_token: "synthetic-token" });
      if (path.endsWith("/accounts")) return response({ accounts: [] });
      if (path.endsWith("/targets")) return response({ targets: [] });
      if (path.endsWith("/tasks")) return response({ tasks: [task] });
      return response(task);
    });
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /^任务$/ }));
    await user.click(await screen.findByRole("button", { name: /任务 #7/ }));
    await user.type(await screen.findByLabelText("验证码"), "123456");
    await user.click(screen.getByRole("button", { name: "提交验证码" }));
    await waitFor(() =>
      expect(calls.some((c) => c.path.endsWith("/tasks/7/code"))).toBe(true),
    );
    const call = calls.find((c) => c.path.endsWith("/tasks/7/code"))!;
    expect(JSON.parse(String(call.init?.body))).toMatchObject({
      code: "123456",
      submission_id: expect.any(String),
    });
    expect(screen.getByRole("button", { name: "接管浏览器" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "取消任务" })).toBeTruthy();
  });
  it("previews and confirms import using the exact versioned import contract", async () => {
    const calls: { path: string; init?: RequestInit }[] = [];
    const text = "synthetic@example.test----synthetic-password";
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path === "/api/v1/auth/session")
        return response({ csrf_token: "synthetic-token" });
      if (path === "/api/v1/accounts") return response({ accounts: [] });
      if (path === "/api/v1/targets") return response({ targets: [] });
      if (path === "/api/v1/tasks") return response({ tasks: [] });
      if (path === "/api/v1/import/preview")
        return response({ records: [{ line: 1, valid: true }] });
      if (path === "/api/v1/import/confirm")
        return response({ imported: ["synthetic@example.test"] });
      return response({ detail: "Unexpected endpoint" }, 404);
    });
    render(<App />);
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: "导入账号" }));
    await user.type(screen.getByLabelText("账号文本"), text);
    await user.click(screen.getByRole("button", { name: "预览导入" }));
    await user.click(await screen.findByRole("button", { name: "确认导入" }));
    await waitFor(() =>
      expect(
        calls.filter((c) => c.path.startsWith("/api/v1/import/")),
      ).toHaveLength(2),
    );
    for (const suffix of ["preview", "confirm"]) {
      const call = calls.find((c) => c.path === `/api/v1/import/${suffix}`)!;
      expect(call.init?.method).toBe("POST");
      expect(call.init?.headers).toMatchObject({
        "X-CSRF-Token": "synthetic-token",
      });
      expect(JSON.parse(String(call.init?.body))).toEqual({ text });
    }
    expect(calls.some((c) => c.path.includes("/accounts/import/"))).toBe(false);
  });
  it("restores the selected task, merges persisted logs, and closes a terminal SSE stream", async () => {
    window.history.replaceState(null, "", "/#tasks/7");
    const task = {
      id: 7,
      account_id: 2,
      target_id: 3,
      state: "running",
      takeover_available: false,
    };
    let emit: ((event: MessageEvent) => void) | undefined;
    let current: SyntheticEvents | undefined;
    const close = vi.fn();
    class SyntheticEvents {
      onerror?: () => void;
      constructor() {
        current = this;
      }
      addEventListener(_name: string, listener: (event: MessageEvent) => void) {
        emit = listener;
      }
      close = close;
    }
    vi.stubGlobal("EventSource", SyntheticEvents);
    vi.mocked(fetch).mockImplementation((input) => {
      const path = String(input);
      if (path.endsWith("/auth/session"))
        return response({ csrf_token: "synthetic-token" });
      if (path.endsWith("/accounts")) return response({ accounts: [] });
      if (path.endsWith("/targets")) return response({ targets: [] });
      if (path.endsWith("/tasks")) return response({ tasks: [task] });
      if (path.endsWith("/history"))
        return response({
          events: [
            {
              id: 7,
              event_id: 41,
              state: "running",
              takeover_available: false,
              phase: "browser",
              message: "Browser ready",
            },
          ],
        });
      return response(task);
    });
    const view = render(<App />);
    expect(
      await screen.findByRole("heading", { name: "任务 #7" }),
    ).toBeTruthy();
    expect(await screen.findByText("Browser ready")).toBeTruthy();
    const { act } = await import("@testing-library/react");
    await act(async () => {
      task.takeover_available = true;
      emit!(
        new MessageEvent("task", {
          lastEventId: "41",
          data: JSON.stringify({
            id: 7,
            task_id: 7,
            event_id: 41,
            state: "running",
            phase: "browser",
            message: "Browser ready",
            takeover_available: true,
          }),
        }),
      );
    });
    expect(screen.getAllByText("Browser ready")).toHaveLength(1);
    expect(screen.getByRole("button", { name: "接管浏览器" })).toHaveProperty(
      "disabled",
      false,
    );
    await act(async () => {
      task.state = "succeeded";
      emit!(
        new MessageEvent("task", {
          lastEventId: "42",
          data: JSON.stringify({
            id: 7,
            task_id: 7,
            event_id: 42,
            state: "succeeded",
            phase: "verified",
            message: "Synchronization complete",
          }),
        }),
      );
      current?.onerror?.();
    });
    expect(close).toHaveBeenCalled();
    expect(screen.queryByText("实时连接已断开，正在重连…")).toBeNull();
    expect(screen.getByText("Synchronization complete")).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "任务 #42" })).toBeNull();
    expect(window.location.hash).toBe("#tasks/7");
    view.unmount();
    render(<App />);
    expect(
      await screen.findByRole("heading", { name: "任务 #7" }),
    ).toBeTruthy();
  });
  it("requires the exact account identity before discarding an uncertain sync result", async () => {
    window.history.replaceState(null, "", "/#tasks/9");
    const task = {
      id: 9,
      account_id: 2,
      account_username: "synthetic@example.test",
      target_id: 3,
      state: "sync_pending",
      phase: "sync_failed",
    };
    const calls: { path: string; init?: RequestInit }[] = [];
    class SyntheticEvents {
      addEventListener() {}
      close() {}
    }
    vi.stubGlobal("EventSource", SyntheticEvents);
    const prompt = vi
      .spyOn(window, "prompt")
      .mockReturnValueOnce("wrong@example.test")
      .mockReturnValueOnce(task.account_username);
    vi.mocked(fetch).mockImplementation((input, init) => {
      const path = String(input);
      calls.push({ path, init });
      if (path.endsWith("/auth/session"))
        return response({ csrf_token: "synthetic-token" });
      if (path.endsWith("/accounts")) return response({ accounts: [] });
      if (path.endsWith("/targets")) return response({ targets: [] });
      if (path.endsWith("/tasks")) return response({ tasks: [task] });
      if (path.endsWith("/history")) return response({ events: [] });
      return response(task);
    });
    render(<App />);
    const user = userEvent.setup();
    const discard = await screen.findByRole("button", {
      name: "放弃本地同步结果",
    });
    expect(
      screen.getByRole("button", { name: "重试同步" }).className,
    ).toContain("primary");
    await user.click(discard);
    expect(
      await screen.findByText("账号邮箱不匹配，未放弃同步结果。"),
    ).toBeTruthy();
    expect(calls.some((c) => c.path.endsWith("/discard-sync"))).toBe(false);
    await user.click(discard);
    await waitFor(() =>
      expect(calls.some((c) => c.path === "/api/v1/tasks/9/discard-sync")).toBe(
        true,
      ),
    );
    const call = calls.find((c) => c.path === "/api/v1/tasks/9/discard-sync")!;
    expect(call.init?.method).toBe("POST");
    expect(JSON.parse(String(call.init?.body))).toEqual({
      confirmation: task.account_username,
    });
    expect(prompt).toHaveBeenLastCalledWith(
      expect.stringContaining("此操作不会删除目标服务中的账号"),
    );
    prompt.mockRestore();
  });
});


it("keeps account editor busy until new route and bindings finish refreshing", async () => {
  let updated = false;
  let release: ((value: Response) => void) | undefined;
  const account = { id: 1, username: "synthetic@example.test", status: "new", route_type: "unset", target_ids: [], has_password: true, has_totp: false, has_mailbox: false };
  vi.mocked(fetch).mockImplementation((input, init) => {
    const path = String(input);
    if (path.endsWith("/auth/session")) return response({ csrf_token: "synthetic-token" });
    if (path.endsWith("/accounts/1") && init?.method === "PATCH") { updated = true; return response({}); }
    if (path.endsWith("/accounts")) {
      if (updated) return new Promise<Response>((resolve) => { release = resolve; });
      return response({ accounts: [account] });
    }
    if (path.endsWith("/targets")) return response({ targets: [{ id: 1, name: "Synthetic CPA", kind: "cliproxyapi", verification: "unverified" }] });
    return response({ tasks: [] });
  });
  render(<App />);
  const user = userEvent.setup();
  await user.click(await screen.findByRole("button", { name: "编辑与绑定" }));
  expect(screen.getByLabelText("网络路由")).toHaveProperty("value", "proxy");
  expect(screen.getByLabelText("Synthetic CPA")).toHaveProperty("checked", true);
  expect(screen.getByLabelText("新代理 URL（留空保留）")).toHaveProperty("required", true);
  await user.selectOptions(screen.getByLabelText("网络路由"), "direct");
  await user.click(screen.getByRole("button", { name: "保存账号" }));
  await waitFor(() => expect(release).toBeTypeOf("function"));
  expect(screen.getByRole("dialog")).toBeTruthy();
  expect(screen.getByRole("button", { name: "保存中…" })).toHaveProperty("disabled", true);
  release!(new Response(JSON.stringify({ accounts: [{ ...account, route_type: "direct", target_ids: [1] }] }), { status: 200, headers: { "Content-Type": "application/json" } }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  await user.click(screen.getByRole("button", { name: "开始登录" }));
  expect(within(screen.getByRole("dialog")).getByRole("button", { name: "开始登录" })).toHaveProperty("disabled", false);
});
