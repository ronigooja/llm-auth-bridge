// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { HealthTime, SessionHealth, type TargetSync, type WebSession } from "./session-health";

const now = 1800000000000;
const session: WebSession = { status: "valid", checked_at: now / 1000 - 3600, last_success_at: now / 1000 - 3600, error_code: null, activity: "idle", task_id: null };
const sync: TargetSync = { target_id: 2, kind: "chatgpt-web-voice", state: "verified", verified_at: now / 1000 - 7200, next_check: now / 1000 - 60, pause_reason: null, task_id: null };
afterEach(() => { cleanup(); vi.restoreAllMocks(); });

describe("account session health", () => {
  it("keeps historical health valid while a due maintenance check is queued", () => {
    vi.spyOn(Date, "now").mockReturnValue(now);
    const openTask = vi.fn();
    render(<SessionHealth session={{ ...session, activity: "queued", task_id: 7 }} syncs={[sync]} targets={[{ id: 2, name: "Synthetic Voice" }]} openTask={openTask} />);
    expect(screen.getByText("会话有效")).toBeTruthy();
    expect(screen.getByText("检查排队中")).toBeTruthy();
    expect(screen.getByText("已验证同步")).toBeTruthy();
    expect(screen.getByText(/维护已到期，等待检查/)).toBeTruthy();
    expect(screen.queryByText("已退出登录")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "查看任务 #7" }));
    expect(openTask).toHaveBeenCalledWith(7);
    const time = screen.getByText("2 小时前");
    expect(time.tagName).toBe("TIME");
    expect(time.getAttribute("datetime")).toBe(new Date(sync.verified_at! * 1000).toISOString());
    expect(time.getAttribute("title")).toContain("2027");
  });
  it.each([
    ["signed_out", "会话已退出，请重新登录"],
    ["identity_mismatch", "账号身份不匹配"],
    ["maintenance_disabled", "自动维护已关闭"],
  ] as const)("shows %s pause without replacing successful sync history", (pause_reason, text) => {
    render(<SessionHealth session={session} syncs={[{ ...sync, pause_reason }]} targets={[]} openTask={vi.fn()} />);
    expect(screen.getByText("已验证同步")).toBeTruthy();
    expect(screen.getByText(new RegExp(`维护已暂停：${text}`))).toBeTruthy();
    expect(screen.queryByText(/维护已到期/)).toBeNull();
  });
  it("shows independent target outcomes and links their tasks", () => {
    const openTask = vi.fn();
    render(<SessionHealth session={{ ...session, status: "signed_out" }} syncs={[sync, { ...sync, target_id: 3, state: "sync_pending", task_id: 8 }]} targets={[{ id: 2, name: "Voice" }, { id: 3, name: "CPA" }]} openTask={openTask} />);
    expect(screen.getByText("已退出登录")).toBeTruthy();
    expect(within(screen.getByText("Voice").closest(".target-health") as HTMLElement).getByText("已验证同步")).toBeTruthy();
    expect(within(screen.getByText("CPA").closest(".target-health") as HTMLElement).getByText("等待同步")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "查看任务 #8" }));
    expect(openTask).toHaveBeenCalledWith(8);
  });
  it("distinguishes failed checks from sign-out and retains last successful time", () => {
    render(<SessionHealth session={{ ...session, status: "error", error_code: "navigation_failed", activity: "checking", task_id: 9 }} targets={[]} openTask={vi.fn()} />);
    expect(screen.getByText("检查失败")).toBeTruthy();
    expect(screen.getByText("正在检查会话")).toBeTruthy();
    expect(screen.getByText(/navigation_failed/)).toBeTruthy();
    expect(screen.queryByText("已退出登录")).toBeNull();
    expect(document.querySelectorAll("time")).toHaveLength(2);
  });
  it("prioritizes account deletion over an unhelpful never-successful message", () => {
    render(<SessionHealth session={{ ...session, status: "unavailable", error_code: "account_deleted", last_success_at: null }} targets={[]} openTask={vi.fn()} />);
    expect(screen.getByText("账号不可用")).toBeTruthy();
    expect(screen.queryByText("检查失败")).toBeNull();
    expect(screen.getByText(/最近检查/)).toBeTruthy();
    expect(screen.getAllByText(/已被 OpenAI 删除/)).toHaveLength(1);
    expect(screen.queryByText("从未成功")).toBeNull();
    expect(screen.queryByText("尚无成功记录")).toBeNull();
  });
  it("does not repeat the status label as the reason and avoids the global error class", () => {
    render(<SessionHealth session={{ ...session, status: "error", error_code: "check_failed", last_success_at: null }} targets={[]} openTask={vi.fn()} />);
    expect(screen.getAllByText(/检查失败/)).toHaveLength(1);
    expect(screen.getByText(/尚无成功记录/)).toBeTruthy();
    const badge = screen.getByText("检查失败");
    expect(badge.classList.contains("badge")).toBe(true);
    expect(badge.classList.contains("error")).toBe(false);
    expect(badge.classList.contains("session-error")).toBe(true);
  });
  it("shows no activity badge when the backend omits or idles activity", () => {
    const { rerender } = render(<SessionHealth session={{ ...session, activity: undefined, task_id: undefined }} targets={[]} openTask={vi.fn()} />);
    expect(screen.queryByText("正在检查会话")).toBeNull();
    expect(screen.queryByText("检查排队中")).toBeNull();
    rerender(<SessionHealth session={{ ...session, activity: "idle", task_id: null }} targets={[]} openTask={vi.fn()} />);
    expect(screen.queryByText("正在检查会话")).toBeNull();
    rerender(<SessionHealth session={{ ...session, activity: "queued", task_id: 4 }} targets={[]} openTask={vi.fn()} />);
    expect(screen.getByText("检查排队中")).toBeTruthy();
  });
  it("does not infer validity when session health is missing", () => {
    render(<SessionHealth targets={[]} openTask={vi.fn()} />);
    expect(screen.getByText("尚未检查")).toBeTruthy();
    expect(document.querySelectorAll("time")).toHaveLength(0);
    expect(screen.queryByText("会话有效")).toBeNull();
  });
  it("uses epoch seconds and gives future times an absolute timestamp", () => {
    render(<HealthTime value={now / 1000 + 3600} now={now} />);
    expect(screen.getByText("1 小时后").getAttribute("datetime")).toBe(new Date(now + 3600000).toISOString());
  });
});
