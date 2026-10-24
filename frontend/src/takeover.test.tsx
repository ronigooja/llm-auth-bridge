// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { TakeoverPanel, useTakeoverWindow } from "./takeover";
import { App } from "./main";

const url = "/novnc/vnc.html?autoconnect=true&resize=scale&path=api/v1/tasks/7/takeover";
function Harness({ ready = false, ended = false }) {
  const viewer = useTakeoverWindow(ready, ended);
  return <>
    <button onClick={() => { viewer.open(); viewer.setUrl(url); }}>接管浏览器</button>
    {viewer.url && <TakeoverPanel viewer={viewer} ready={ready} />}
  </>;
}
function mockPopup() {
  const target = {
    opener: window, closed: false, document: { title: "", body: { textContent: "" } },
    location: { replace: vi.fn() }, focus: vi.fn(), close: vi.fn(),
  };
  const open = vi.spyOn(window, "open").mockReturnValue(target as unknown as Window);
  return { target, open };
}
afterEach(() => { cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("takeover window", () => {
  it("opens only on click, fills available screen, and waits until automation pauses", () => {
    const { target, open } = mockPopup();
    vi.spyOn(window.screen, "availWidth", "get").mockReturnValue(1920);
    vi.spyOn(window.screen, "availHeight", "get").mockReturnValue(1080);
    const view = render(<Harness />);
    expect(open).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    expect(open).toHaveBeenCalledWith("about:blank", "_blank", expect.stringContaining("width=1600,height=1000"));
    expect(target.opener).toBeNull();
    expect(target.document.body.textContent).toContain("正在准备");
    expect(target.location.replace).not.toHaveBeenCalled();
    expect(screen.queryByRole("link")).toBeNull();
    expect(document.querySelector("iframe")).toBeNull();
    view.rerender(<Harness ready />);
    expect(target.location.replace).toHaveBeenCalledWith(url);
    fireEvent.click(screen.getByRole("link", { name: "返回接管窗口" }));
    expect(open).toHaveBeenCalledTimes(1);
    expect(target.focus).toHaveBeenCalledOnce();
    view.rerender(<Harness ready ended />);
    expect(target.close).toHaveBeenCalledOnce();
    expect(screen.queryByRole("link")).toBeNull();
  });
  it("offers a same-origin manual link when popup is blocked", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<Harness ready />);
    fireEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    const link = screen.getByRole("link", { name: "打开接管窗口" });
    expect(link.getAttribute("href")).toBe(url);
    expect(link.getAttribute("rel")).toBe("noopener noreferrer");
    expect(link.getAttribute("target")).toBe("_blank");
    expect(screen.getByRole("status").textContent).toContain("拦截了弹窗");
    // If another window.open is blocked, preserve the browser's normal link action.
    const click = new MouseEvent("click", { bubbles: true, cancelable: true });
    link.dispatchEvent(click);
    expect(click.defaultPrevented).toBe(false);
    expect(open).toHaveBeenCalledTimes(2);
  });
  it("fits small screens and closes the managed viewer on continuation or unmount", () => {
    const { target, open } = mockPopup();
    vi.spyOn(window.screen, "availWidth", "get").mockReturnValue(390);
    vi.spyOn(window.screen, "availHeight", "get").mockReturnValue(844);
    const view = render(<Harness ready />);
    fireEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    expect(open).toHaveBeenCalledWith("about:blank", "_blank", expect.stringContaining("width=390,height=844"));
    view.rerender(<Harness />);
    expect(target.close).toHaveBeenCalledOnce();
    fireEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    view.unmount();
    expect(target.close).toHaveBeenCalledTimes(2);
  });
  it("lets users reopen after closing the native window", () => {
    vi.useFakeTimers();
    const { target } = mockPopup();
    render(<Harness ready />);
    fireEvent.click(screen.getByRole("button", { name: "接管浏览器" }));
    target.closed = true;
    act(() => { vi.advanceTimersByTime(1000); });
    expect(screen.getByRole("link", { name: "打开接管窗口" })).toBeTruthy();
  });
});


describe("takeover request integration", () => {
  it("reserves the popup before the API resolves and closes it on an unsafe URL", async () => {
    window.history.replaceState(null, "", "/#tasks/7");
    vi.stubGlobal("EventSource", class { addEventListener() {} close() {} });
    let finish: ((response: Response) => void) | undefined;
    const task = { id: 7, state: "waiting_human", phase: "waiting_human", takeover_available: true };
    const json = (data: unknown) => Promise.resolve(new Response(JSON.stringify(data), { headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", vi.fn((input: unknown) => {
      const path = String(input);
      if (path.endsWith("/auth/session")) return json({ csrf_token: "synthetic" });
      if (path.endsWith("/takeover")) return new Promise<Response>((resolve) => { finish = resolve; });
      if (path.endsWith("/tasks")) return json({ tasks: [task] });
      if (path.endsWith("/history")) return json({ events: [] });
      if (path.endsWith("/tasks/7")) return json(task);
      return json({ accounts: [], targets: [] });
    }));
    const { target, open } = mockPopup();
    render(<App />);
    fireEvent.click(await screen.findByRole("button", { name: "接管浏览器" }));
    expect(open).toHaveBeenCalledOnce();
    expect(target.location.replace).not.toHaveBeenCalled();
    expect(finish).toBeTypeOf("function");
    await act(async () => { finish!(await json({ url: "https://outside.example.test/viewer" })); });
    await waitFor(() => expect(target.close).toHaveBeenCalledOnce());
    expect(target.location.replace).not.toHaveBeenCalled();
    expect(await screen.findByRole("alert")).toHaveProperty("textContent", expect.stringContaining("同源"));
  });
});
