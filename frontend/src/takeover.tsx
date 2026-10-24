import { useEffect, useRef, useState } from "react";

// Reserve the window inside the click gesture, before the takeover POST awaits.
// Only navigate after the worker has paused automation in the browser session.
export function useTakeoverWindow(ready: boolean, ended: boolean) {
  const popup = useRef<Window | null>(null);
  const [url, setUrl] = useState<string | null>(null);
  const [opened, setOpened] = useState(false);
  const wasReady = useRef(ready);
  function close() {
    popup.current?.close();
    popup.current = null;
    setOpened(false);
    setUrl(null);
  }
  function open() {
    if (popup.current && !popup.current.closed) {
      popup.current.focus();
      return true;
    }
    const width = Math.max(1, Math.min(1600, window.screen.availWidth || window.innerWidth));
    const height = Math.max(1, Math.min(1000, window.screen.availHeight || window.innerHeight));
    const left = Math.max(0, Math.round(((window.screen.availWidth || width) - width) / 2));
    const top = Math.max(0, Math.round(((window.screen.availHeight || height) - height) / 2));
    const target = window.open("about:blank", "_blank", `popup=yes,width=${width},height=${height},left=${left},top=${top},resizable=yes,scrollbars=yes`);
    if (!target) {
      setOpened(false);
      return false;
    }
    // Retain our close handle without giving the remote viewer an opener.
    target.opener = null;
    target.document.title = "浏览器接管";
    target.document.body.textContent = "正在准备浏览器接管，请稍候…";
    popup.current = target;
    setOpened(true);
    if (ready && url) target.location.replace(url);
    return true;
  }
  useEffect(() => {
    if (ready && url && popup.current && !popup.current.closed)
      popup.current.location.replace(url);
  }, [ready, url]);
  useEffect(() => {
    if (ended || (wasReady.current && !ready)) close();
    wasReady.current = ready;
  }, [ended, ready]);
  useEffect(() => {
    const timer = window.setInterval(() => {
      if (popup.current?.closed) {
        popup.current = null;
        setOpened(false);
      }
    }, 1000);
    return () => {
      window.clearInterval(timer);
      popup.current?.close();
    };
  }, []);
  return { url, setUrl, open, close, opened };
}

export function TakeoverPanel({ viewer, ready }: {
  viewer: ReturnType<typeof useTakeoverWindow>;
  ready: boolean;
}) {
  return (
    <div className="takeover">
      <h3>浏览器接管</h3>
      <p className="muted" role="status">
        {!ready ? "正在准备浏览器接管…" : viewer.opened
          ? "浏览器已在独立窗口中打开。完成操作后，返回此处点击“继续任务”。"
          : "如浏览器拦截了弹窗，请点击下方链接打开接管窗口。完成操作后，返回此处点击“继续任务”。"}
      </p>
      {ready && viewer.url && (
        <a className="button" href={viewer.url} target="_blank" rel="noopener noreferrer"
          onClick={(event) => { if (viewer.open()) event.preventDefault(); }}>
          {viewer.opened ? "返回接管窗口" : "打开接管窗口"}
        </a>
      )}
      <button onClick={viewer.close}>关闭接管窗口</button>
    </div>
  );
}
