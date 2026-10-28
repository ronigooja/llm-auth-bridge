import RFB from "/novnc/core/rfb.js";

// noVNC 1.3 suppresses desktop resize in view-only mode. Geometry is allowed
// by our bounded server filter; keyboard and pointer input remain blocked in
// monitor mode. Clipboard text is explicitly surfaced to avoid browser-policy
// surprises and is sent to the remote browser only during takeover.
class AccountRFB extends RFB {
    _requestRemoteResize() {
        clearTimeout(this._resizeTimeout);
        this._resizeTimeout = null;
        if (!this._resizeSession || !this._supportsSetDesktopSize) return;
        const { w, h } = this._screenSize();
        const width = Math.floor(w), height = Math.floor(h);
        if (width < 64 || height < 64 || width > 4096 || height > 4096 || width * height > 8847360) return;
        RFB.messages.setDesktopSize(this._sock, width, height, this._screenID, this._screenFlags);
    }
}

const params = new URLSearchParams(location.search);
const path = params.get("path") || "";
if (!/^api\/v1\/tasks\/[1-9]\d*\/(monitor|takeover)$/.test(path)) throw new Error("Invalid account viewer path");
const url = new URL(`/${path}`, location.href);
url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
export const rfb = new AccountRFB(document.getElementById("desktop"), url.href, { shared: true });
const viewOnly = path.endsWith("/monitor");
rfb.viewOnly = viewOnly;
rfb.scaleViewport = false;
rfb.clipViewport = false;
rfb.resizeSession = true;
const status = document.getElementById("status");
const fullscreen = document.getElementById("fullscreen");
const clipboardToggle = document.getElementById("clipboard-toggle");
const clipboardPanel = document.getElementById("clipboard-panel");
const clipboardText = document.getElementById("clipboard-text");
const clipboardSend = document.getElementById("clipboard-send");
const clipboardCopy = document.getElementById("clipboard-copy");
const setFullscreenLabel = () => { fullscreen.textContent = document.fullscreenElement ? "退出全屏" : "全屏"; };
fullscreen.addEventListener("click", async () => {
    try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
        setFullscreenLabel();
    } catch {
        // Fullscreen can be denied by an embedding policy; the viewer remains usable.
    }
});
document.addEventListener("fullscreenchange", setFullscreenLabel);
document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && document.fullscreenElement) {
        event.preventDefault();
        void document.exitFullscreen();
    }
});
if (!viewOnly) {
    clipboardToggle.hidden = false;
    clipboardToggle.addEventListener("click", () => {
        clipboardPanel.classList.toggle("open");
        if (clipboardPanel.classList.contains("open")) clipboardText.focus();
    });
    clipboardSend.addEventListener("click", () => {
        rfb.clipboardPasteFrom(clipboardText.value);
    });
    clipboardCopy.addEventListener("click", async () => {
        const text = clipboardText.value;
        try {
            await navigator.clipboard.writeText(text);
        } catch {
            clipboardText.focus();
            clipboardText.select();
            document.execCommand("copy");
        }
    });
    document.addEventListener("paste", (event) => {
        if (event.target === clipboardText) return;
        const text = event.clipboardData?.getData("text/plain");
        if (text) rfb.clipboardPasteFrom(text);
    });
}
rfb.addEventListener("clipboard", (event) => {
    clipboardText.value = event.detail?.text || "";
    if (!viewOnly) clipboardPanel.classList.add("open");
});
rfb.addEventListener("connect", () => { status.hidden = true; });
rfb.addEventListener("disconnect", () => {
    status.textContent = "连接已断开，请重新打开账号窗口。";
    status.hidden = false;
});
