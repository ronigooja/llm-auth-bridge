import RFB from "/novnc/core/rfb.js";

// noVNC 1.3 suppresses desktop resize in view-only mode. Geometry is allowed
// by our bounded server filter; keyboard, pointer and clipboard remain blocked.
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
rfb.viewOnly = path.endsWith("/monitor");
rfb.scaleViewport = false;
rfb.clipViewport = false;
rfb.resizeSession = true;
const status = document.getElementById("status");
rfb.addEventListener("connect", () => { status.hidden = true; });
rfb.addEventListener("disconnect", () => {
    status.textContent = "连接已断开，请重新打开账号窗口。";
    status.hidden = false;
});
