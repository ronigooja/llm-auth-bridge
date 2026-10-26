// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { useAccountWindow } from "./account-window";
import { App } from "./main";

const json = (value: unknown) => Promise.resolve(new Response(JSON.stringify(value), { headers: { "Content-Type": "application/json" } }));
function Harness() {
  const viewer = useAccountWindow(true);
  return <><button onClick={() => void viewer.open(1)}>账号窗口</button><button onClick={() => void viewer.open(2)}>另一个账号窗口</button>{viewer.panel}</>;
}
function popup() {
  // Accessibility queries need the document's own window for computed styles.
  // createHTMLDocument() has no defaultView and cannot model a live popup.
  const frame = document.createElement("iframe");
  frame.dataset.popupFixture = "true";
  document.body.appendChild(frame);
  const doc = frame.contentDocument!;
  const target = { document: doc, closed: false, opener: window, focus: vi.fn(), close: vi.fn() };
  vi.spyOn(window, "open").mockReturnValue(target as unknown as Window);
  return target;
}
afterEach(() => {
  cleanup();
  document.querySelectorAll("iframe[data-popup-fixture]").forEach((frame) => frame.remove());
  vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers();
});
describe("unified account window", () => {
  it("reserves one large window and monitors without requesting takeover", async () => {
    const target = popup();
    const task = { id: 7, state: "running", takeover_available: true };
    vi.stubGlobal("fetch", vi.fn(() => json({ task })));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "账号窗口" }));
    expect(window.open).toHaveBeenCalledWith("about:blank", "_blank", expect.stringContaining("resizable=yes"));
    await waitFor(() => expect(target.document.querySelector("iframe")?.src).toContain("view_only=true&shared=true&path=api/v1/tasks/7/monitor"));
    expect(target.opener).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(vi.mocked(fetch).mock.calls[0][0]).toBe("/api/v1/accounts/1/browser");
    fireEvent.click(screen.getByRole("button", { name: "账号窗口" }));
    expect(window.open).toHaveBeenCalledOnce();
    expect(target.focus).toHaveBeenCalledOnce();
    expect(within(target.document.body).queryByRole("button", { name: /保存|隐藏/ })).toBeNull();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
  it("keeps monitoring until the worker confirms paused automation", async () => {
    const target = popup();
    const task = { id: 7, state: "running", takeover_available: true };
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input) => {
      const path = String(input); calls.push(path);
      return json(path.endsWith("/browser") ? { task } : task);
    }));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "账号窗口" }));
    await waitFor(() => expect(target.document.querySelector("iframe")).toBeTruthy());
    fireEvent.click(within(target.document.body).getByRole("button", { name: "接管" }));
    await waitFor(() => expect(calls).toContain("/api/v1/tasks/7/takeover"));
    expect(target.document.querySelector("iframe")?.src).toContain("/monitor");
    task.state = "waiting_human";
    await waitFor(() => expect(target.document.querySelector("iframe")?.src).toContain("view_only=false&shared=true&path=api/v1/tasks/7/takeover"), { timeout: 2500 });
  });
  it("waits for idle readiness after native closure without offering extra close controls", async () => {
    vi.useFakeTimers();
    const target = popup();
    const task = { id: 8, kind: "browser_window", state: "queued", phase: "browser_window", takeover_available: false };
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input) => { calls.push(String(input)); return json({ task }); }));
    render(<Harness />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    expect(within(target.document.body).queryAllByRole("button")).toHaveLength(0);
    target.closed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(calls.filter((path) => path.endsWith("/continue"))).toHaveLength(0);
    task.state = "waiting_human";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(calls.filter((path) => path.endsWith("/continue"))).toHaveLength(1);
    task.state = "succeeded";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it.each(["browser_window", "login"])("handles native closure for %s without cancelling login", async (kind) => {
    const target = popup();
    const task = { id: 8, kind, state: "waiting_human", phase: kind, takeover_available: true };
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input) => { calls.push(String(input)); return json({ task }); }));
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "账号窗口" }));
    await waitFor(() => expect(target.document.querySelector("iframe")).toBeTruthy());
    target.closed = true;
    await waitFor(() => expect(target.close).toHaveBeenCalled(), { timeout: 2500 });
    if (kind === "browser_window") await waitFor(() => expect(calls).toContain("/api/v1/tasks/8/continue"));
    else expect(calls.some((path) => /\/(continue|takeover|cancel)$/.test(path))).toBe(false);
  });
  it("polls a natively closed idle session through saving and then permits another account", async () => {
    vi.useFakeTimers();
    const target = popup();
    const task = { id: 8, kind: "browser_window", state: "waiting_human", phase: "browser_window", takeover_available: true };
    const calls: string[] = [];
    const polledStates: string[] = [];
    vi.stubGlobal("fetch", vi.fn((input) => {
      const path = String(input);
      calls.push(path);
      if (path === "/api/v1/tasks/8") polledStates.push(task.state);
      return json({ task });
    }));
    render(<Harness />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    target.closed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(calls.filter((path) => path.endsWith("/continue"))).toHaveLength(1);
    expect(target.close).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "另一个账号窗口" }));
    expect(screen.getByRole("alert").textContent).toContain("正在关闭或等待就绪");
    expect(window.open).toHaveBeenCalledOnce();

    // The server can still report waiting_human after accepting Continue.
    // Saving must not repeatedly re-enter finish() and starve this GET.
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(polledStates).toEqual(["waiting_human", "waiting_human"]);
    task.state = "running";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    task.state = "succeeded";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(polledStates).toEqual(["waiting_human", "waiting_human", "running", "succeeded"]);
    expect(calls.filter((path) => path.endsWith("/continue"))).toHaveLength(1);
    target.closed = false;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "另一个账号窗口" })); });
    expect(calls).toContain("/api/v1/accounts/2/browser");
    expect(window.open).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it.each([
    ["succeeded", false], ["failed", false],
    ["succeeded", true], ["failed", true],
  ] as const)("reconciles a lost close response before %s (conflict: %s)", async (terminal, conflict) => {
    vi.useFakeTimers();
    const target = popup();
    const task = { id: 8, kind: "browser_window", state: "waiting_human", phase: "browser_window", takeover_available: true };
    const calls: string[] = [];
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn((input) => {
      const path = String(input); calls.push(path);
      if (path.endsWith("/continue")) {
        attempts++;
        if (attempts === 1) return Promise.reject(new Error("synthetic lost close response"));
        return Promise.resolve(new Response(JSON.stringify({ detail: "synthetic already closing" }), { status: 409 }));
      }
      return json({ task });
    }));
    render(<Harness />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    target.closed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(screen.getByRole("alert").textContent).toContain("synthetic lost close response");
    if (conflict) {
      // An accepted close may temporarily still appear waiting_human.
      await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
      expect(screen.getByRole("alert").textContent).toContain("synthetic already closing");
    }
    task.state = terminal;
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(calls.slice(1)).toEqual([
      "/api/v1/tasks/8", "/api/v1/tasks/8/continue",
      ...(conflict ? ["/api/v1/tasks/8", "/api/v1/tasks/8/continue"] : []),
      "/api/v1/tasks/8",
    ]);
    if (terminal === "succeeded") expect(screen.queryByRole("alert")).toBeNull();
    else expect(screen.getByRole("alert").textContent).toContain("浏览器状态尚未确认保存");
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(attempts).toBe(conflict ? 2 : 1);
    // Either terminal result releases the account switch; a failure stays visible
    // until the operator explicitly opens a different account.
    target.closed = false;
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "另一个账号窗口" })); });
    expect(calls).toContain("/api/v1/accounts/2/browser");
    expect(window.open).toHaveBeenCalledTimes(2);
  });
  it.each([false, true])("finishes closing after reopening the same idle viewer (lost response: %s)", async (lost) => {
    vi.useFakeTimers();
    const target = popup();
    const task = { id: 8, kind: "browser_window", state: "waiting_human", takeover_available: true };
    let attempts = 0;
    vi.stubGlobal("fetch", vi.fn((input) => {
      if (String(input).endsWith("/continue")) {
        attempts++;
        if (lost && attempts === 1) return Promise.reject(new Error("synthetic lost response"));
      }
      return json({ task });
    }));
    render(<Harness />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    target.closed = true;
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    target.closed = false;
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(attempts).toBe(lost ? 2 : 1);
    expect(within(target.document.body).getByRole("status").textContent).toContain("正在关闭");
    task.state = "succeeded";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(target.close).toHaveBeenCalledTimes(2);
    expect(screen.queryByRole("alert")).toBeNull();
  });
  it("keeps polling through Voice synchronization, follows Codex, and explicitly rebinds an ended popup", async () => {
    vi.useFakeTimers();
    const target = popup();
    const voice = { id: 7, account_id: 1, state: "running", takeover_available: true };
    const codex = { id: 8, account_id: 1, depends_on_task_id: 7, state: "queued", takeover_available: true };
    const calls: string[] = [];
    let opened = false;
    vi.stubGlobal("fetch", vi.fn((input) => {
      const path = String(input); calls.push(path);
      if (path.endsWith("/browser")) {
        if (opened) return json({ task: { id: 9, account_id: 1, kind: "browser_window", state: "waiting_human", takeover_available: true } });
        opened = true; return json({ task: voice });
      }
      if (path.endsWith("/takeover")) return json({});
      if (path === "/api/v1/tasks") return json({ tasks: [
        { ...codex, id: 90, account_id: 2 }, codex,
      ] });
      return json(path.endsWith("/7") ? voice : codex);
    }));
    render(<Harness />);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    await act(async () => { fireEvent.click(within(target.document.body).getByRole("button", { name: "接管" })); });
    voice.state = "waiting_human";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(target.document.querySelector("iframe")?.src).toContain("tasks/7/takeover");
    voice.state = "running";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    voice.state = "sync_pending";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(within(target.document.body).getByRole("status").textContent).toContain("正在同步账号");
    expect(target.document.querySelector("iframe")).toBeNull();
    expect(within(target.document.body).queryByRole("button", { name: "接管" })).toBeNull();
    voice.state = "succeeded";
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(target.document.querySelector("iframe")).toBeNull();
    codex.state = "waiting_human";
    await act(async () => { await vi.advanceTimersByTimeAsync(1000); });
    expect(target.document.querySelector("iframe")?.src).toContain("tasks/8/monitor");
    expect(calls.filter((path) => path.endsWith("/browser"))).toHaveLength(1);
    expect(window.open).toHaveBeenCalledOnce();
    codex.state = "succeeded";
    await act(async () => { await vi.advanceTimersByTimeAsync(2000); });
    expect(calls.filter((path) => path.endsWith("/browser"))).toHaveLength(1);
    await act(async () => { fireEvent.click(screen.getByRole("button", { name: "账号窗口" })); });
    expect(calls.filter((path) => path.endsWith("/browser"))).toHaveLength(2);
    expect(window.open).toHaveBeenCalledOnce();
    expect(target.document.querySelector("iframe")?.src).toContain("tasks/9/takeover");
  });
  it("does not queue an idle task if popups are blocked", async () => {
    vi.spyOn(window, "open").mockReturnValue(null);
    vi.stubGlobal("fetch", vi.fn());
    render(<Harness />);
    fireEvent.click(screen.getByRole("button", { name: "账号窗口" }));
    expect(screen.getByRole("alert").textContent).toContain("拦截");
    expect(fetch).not.toHaveBeenCalled();
  });
});

it.each([
  ["browser_window", "opening", false],
  ["login", "browser_window", false],
  ["login", "manual_required", true],
] as const)("only offers task-page Continue for login work (%s, %s)", async (kind, phase, canContinue) => {
  window.history.replaceState(null, "", "/#tasks/7");
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  const task = { id: 7, account_id: 1, kind, phase, state: "waiting_human" };
  const calls: { path: string; method?: string }[] = [];
  vi.stubGlobal("fetch", vi.fn((input, init) => {
    const path = String(input); calls.push({ path, method: init?.method });
    if (path.endsWith("/auth/session")) return json({ csrf_token: "synthetic" });
    if (path.endsWith("/accounts")) return json({ accounts: [] });
    if (path.endsWith("/targets")) return json({ targets: [] });
    if (path.endsWith("/tasks")) return json({ tasks: [task] });
    if (path.endsWith("/history")) return json({ events: [] });
    return json(task);
  }));
  render(<App />);
  await screen.findByRole("button", { name: "账号窗口" });
  expect(screen.queryByRole("button", { name: /保存账号窗口|隐藏账号窗口|保存并关闭账号窗口/ })).toBeNull();
  if (canContinue) {
    fireEvent.click(screen.getByRole("button", { name: "继续任务" }));
    await waitFor(() => expect(calls.some((call) => call.path.endsWith("/tasks/7/continue") && call.method === "POST")).toBe(true));
  } else expect(screen.queryByRole("button", { name: "继续任务" })).toBeNull();
});

it("requires an explicit bound target choice when a kind has multiple targets", async () => {
  window.history.replaceState(null, "", "/#accounts");
  const calls: { path: string; init?: RequestInit }[] = [];
  vi.stubGlobal("fetch", vi.fn((input, init) => {
    const path = String(input); calls.push({ path, init });
    if (path.endsWith("/auth/session")) return json({ csrf_token: "synthetic" });
    if (path.endsWith("/accounts")) return json({ accounts: [{ id: 1, username: "synthetic@example.test", route_type: "direct", status: "new", target_ids: [1, 2, 3] }] });
    if (path.endsWith("/targets")) return json({ targets: [
      { id: 1, name: "Voice one", kind: "chatgpt-web-voice" },
      { id: 2, name: "Voice two", kind: "chatgpt-web-voice" },
      { id: 3, name: "CPA", kind: "cliproxyapi" },
      { id: 99, name: "Unbound voice", kind: "chatgpt-web-voice" },
    ] });
    return json({ tasks: [] });
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: "登录 Codex" }));
  const dialog = within(screen.getByRole("dialog"));
  expect(dialog.getByLabelText("第一步：ChatGPT Web Voice")).toHaveProperty("value", "0");
  expect(dialog.getByLabelText("第二步：CLIProxyAPI")).toHaveProperty("value", "3");
  expect(dialog.getByRole("button", { name: "登录 Codex" })).toHaveProperty("disabled", true);
  expect(dialog.queryByRole("option", { name: "Unbound voice" })).toBeNull();
  expect(calls.some((call) => call.init?.method === "POST")).toBe(false);
});


it.each(["ChatGPT", "Codex"])("validates 登录 %s with only a bound Voice target", async (mode) => {
  window.history.replaceState(null, "", "/#accounts");
  vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
  const calls: { path: string; init?: RequestInit }[] = [];
  const task = { id: 7, account_id: 1, state: "running", target_id: 1 };
  vi.stubGlobal("fetch", vi.fn((input, init) => {
    const path = String(input); calls.push({ path, init });
    if (path.endsWith("/auth/session")) return json({ csrf_token: "synthetic" });
    if (path.endsWith("/accounts")) return json({ accounts: [{ id: 1, username: "synthetic@example.test", route_type: "direct", status: "new", target_ids: [1] }] });
    if (path.endsWith("/targets")) return json({ targets: [{ id: 1, name: "Voice", kind: "chatgpt-web-voice" }] });
    if (path.endsWith("/history")) return json({ events: [] });
    if (path.endsWith("/tasks") || path.endsWith("/login-flow")) return json({ tasks: [task] });
    return json(task);
  }));
  render(<App />);
  fireEvent.click(await screen.findByRole("button", { name: `登录 ${mode}` }));
  const dialog = within(screen.getByRole("dialog"));
  expect(dialog.getByLabelText("第一步：ChatGPT Web Voice")).toHaveProperty("value", "1");
  const submit = dialog.getByRole("button", { name: `登录 ${mode}` });
  if (mode === "ChatGPT") {
    expect(dialog.queryByLabelText("第二步：CLIProxyAPI")).toBeNull();
    expect(submit).toHaveProperty("disabled", false);
    fireEvent.click(submit);
    await waitFor(() => expect(calls.some((call) => call.path.endsWith("/login-flow"))).toBe(true));
    const call = calls.find((item) => item.path.endsWith("/login-flow"))!;
    const body = JSON.parse(String(call.init?.body));
    expect(body).toMatchObject({ voice_target_id: 1, idempotency_key: expect.any(String) });
    expect(body).not.toHaveProperty("cli_target_id");
  } else {
    expect(dialog.getByText(/检查 ChatGPT 会话/)).toBeTruthy();
    expect(dialog.getByText(/请先在“编辑与绑定”中绑定 CLIProxyAPI/)).toBeTruthy();
    expect(submit).toHaveProperty("disabled", true);
    expect(calls.some((call) => call.init?.method === "POST")).toBe(false);
  }
});
