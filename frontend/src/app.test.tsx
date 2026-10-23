// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { cleanup, render, screen, waitFor } from "@testing-library/react";
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
      if (path.endsWith("/targets")) return response({ targets: [] });
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
      route_type: "unset",
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
});
