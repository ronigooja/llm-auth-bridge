import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { api } from "./api";
import { requestId } from "./id";

type BrowserTask = { id: number; state: string; kind?: string; phase?: string; takeover_available?: boolean };
const active = new Set(["queued", "running", "waiting_human"]);
export function accountViewerUrl(id: number, interactive: boolean) {
  return `/novnc/vnc.html?autoconnect=true&resize=scale&view_only=${!interactive}&shared=true&path=api/v1/tasks/${id}/${interactive ? "takeover" : "monitor"}`;
}

// One controller survives page navigation. A native close releases only idle
// browser sessions; it must never continue or cancel an automated login.
export function useAccountWindow(enabled: boolean) {
  const popup = useRef<Window | null>(null);
  const current = useRef<BrowserTask | null>(null);
  const hidden = useRef(false);
  const busyRef = useRef(false);
  const opening = useRef(false);
  const saving = useRef<number | null>(null);
  const [closing, setClosing] = useState(false);
  const account = useRef<number | null>(null);
  const [host, setHost] = useState<HTMLElement | null>(null);
  const [task, setTask] = useState<BrowserTask | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [takeoverRequested, setTakeoverRequested] = useState(false);
  const [interactive, setInteractive] = useState(false);
  const idle = (t: BrowserTask) => t.kind === "browser_window" || t.phase === "browser_window";
  function update(t: BrowserTask | null) { current.current = t; setTask(t); }
  function hide() {
    hidden.current = true;
    popup.current?.close();
    popup.current = null;
    setHost(null);
  }
  async function finish() {
    const t = current.current;
    if (!t || !idle(t) || t.state !== "waiting_human" || busyRef.current || saving.current === t.id) return;
    busyRef.current = true;
    saving.current = t.id;
    setClosing(true);
    setBusy(true);
    try {
      await api(`/tasks/${t.id}/continue`, "POST");
      // Continue only accepts the close command. Poll until archive persistence
      // and worker cleanup actually reach a terminal state.
      if (current.current?.id === t.id) setError("");
    } catch (e) {
      if (current.current?.id === t.id) {
        saving.current = null; setClosing(false);
        setError(e instanceof Error ? e.message : "保存失败，请重新打开账号窗口后重试。");
      }
    }
    finally { busyRef.current = false; setBusy(false); }
  }
  async function open(accountId: number) {
    if (popup.current && !popup.current.closed) {
      popup.current.focus();
      if (account.current !== accountId) setError("另一个账号窗口已打开，请先保存或隐藏该窗口，再打开此账号。");
      return;
    }
    if (opening.current) return;
    const previous = current.current;
    const resumeIdle = !!previous && idle(previous) && active.has(previous.state);
    if (resumeIdle && account.current !== accountId) {
      if (popup.current?.closed) hide();
      setError("上一个账号窗口正在保存或等待就绪，请等待保存完成后再打开其他账号。");
      return;
    }
    const width = Math.max(1, Math.min(1600, window.screen.availWidth || window.innerWidth));
    const height = Math.max(1, Math.min(1000, window.screen.availHeight || window.innerHeight));
    const target = window.open("about:blank", "_blank", `popup=yes,width=${width},height=${height},resizable=yes,scrollbars=yes`);
    if (!target) { setError("账号窗口被浏览器拦截，请允许弹窗后再次点击“账号窗口”。"); return; }
    target.opener = null;
    target.document.title = "账号窗口";
    target.document.body.style.cssText = "margin:0;background:#101820;color:#eef4f8;font:16px system-ui;height:100vh";
    const root = target.document.createElement("div");
    root.style.cssText = "height:100%;display:flex;flex-direction:column";
    target.document.body.replaceChildren(root);
    account.current = accountId;
    popup.current = target;
    hidden.current = false;
    setHost(root);
    if (resumeIdle) return;
    saving.current = null;
    setClosing(false);
    update(null);
    setInteractive(false);
    setTakeoverRequested(false);
    setError("");
    opening.current = true;
    try {
      const result = await api<{ task: BrowserTask }>(`/accounts/${accountId}/browser`, "POST", { idempotency_key: requestId() });
      update(result.task);
    } catch (e) { setError(e instanceof Error ? e.message : "无法打开账号窗口"); }
    finally { opening.current = false; }
  }
  async function takeControl() {
    const t = current.current;
    if (!t || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    try {
      await api(`/tasks/${t.id}/takeover`, "POST");
      if (current.current?.id !== t.id) return;
      setTakeoverRequested(true);
      // Switch only after the worker confirms waiting_human via the task API.
      const result = await api<BrowserTask & { task?: BrowserTask }>(`/tasks/${t.id}`);
      if (current.current?.id === t.id) update(result.task || result);
    } catch (e) { if (current.current?.id === t.id) setError(e instanceof Error ? e.message : "无法接管浏览器"); }
    finally { busyRef.current = false; setBusy(false); }
  }
  useEffect(() => {
    if (!enabled) { hide(); update(null); }
  }, [enabled]);
  useEffect(() => {
    if (task && current.current?.id === task.id && saving.current === task.id && !active.has(task.state)) {
      saving.current = null;
      setClosing(false);
      if (task.state === "succeeded") hide();
      else setError("账号窗口保存未成功，请检查任务记录并重试；浏览器状态尚未确认保存。");
    }
  }, [task]);
  useEffect(() => {
    if (!task || task.state !== "waiting_human") { setInteractive(false); return; }
    if (idle(task) || takeoverRequested) setInteractive(true);
  }, [task, takeoverRequested]);
  useEffect(() => {
    let disposed = false;
    let polling = false;
    const timer = window.setInterval(async () => {
      if (popup.current?.closed) hide();
      const t = current.current;
      if (polling || !t || !active.has(t.state)) return;
      if (hidden.current && idle(t) && t.state === "waiting_human" && saving.current !== t.id) { void finish(); return; }
      polling = true;
      try {
        const result = await api<BrowserTask & { task?: BrowserTask }>(`/tasks/${t.id}`);
        if (!disposed && current.current?.id === t.id) update(result.task || result);
      } catch (e) { if (!disposed) setError(e instanceof Error ? e.message : "账号窗口连接中断"); }
      finally { polling = false; }
    }, 1000);
    return () => { disposed = true; window.clearInterval(timer); popup.current?.close(); };
  }, []);
  const available = task && (task.state === "running" || task.state === "waiting_human") && task.takeover_available;
  const panel = <>
    {error && <p role="alert">{error}</p>}
    {host && createPortal(<>
      <header style={{ padding: 12, display: "flex", flexWrap: "wrap", alignItems: "center", gap: 12 }}>
        <strong>账号窗口 · 账号 #{account.current}</strong>
        <span role="status">{!task ? "正在准备账号浏览器…" : closing ? "正在保存浏览器状态，请稍候…" : !active.has(task.state) ? task.state === "succeeded" ? "任务已完成。" : "任务已结束，请检查任务记录。" : interactive ? "可操作浏览器" : "正在观察自动操作（只读）"}</span>
        {task && active.has(task.state) && !idle(task) && !interactive && <button disabled={busy || !available || takeoverRequested} onClick={() => void takeControl()}>{takeoverRequested ? "正在等待接管…" : "接管"}</button>}
        {task && idle(task) && active.has(task.state)
          ? <button disabled={busy || closing || task.state !== "waiting_human"} onClick={() => void finish()}>保存并关闭账号窗口</button>
          : <button onClick={hide}>隐藏账号窗口</button>}
      </header>
      <p style={{ margin: "0 12px 12px" }}>{task && idle(task) ? "关闭窗口会保存浏览器状态并结束本次手动会话。" : "隐藏窗口仅关闭查看器，登录任务会继续。接管后请返回任务页点击“继续任务”。"}</p>
      {error && <p role="alert">{error}</p>}
      {available && <iframe title="账号浏览器" src={accountViewerUrl(task.id, interactive)} style={{ border: 0, width: "100%", flex: 1, minHeight: 0 }} />}
    </>, host)}
  </>;
  return { open, panel };
}
