export type WebSession = {
  status: "unknown" | "valid" | "signed_out" | "error";
  checked_at: number | null;
  last_success_at: number | null;
  error_code: string | null;
  activity?: "idle" | "queued" | "checking";
  task_id?: number | null;
};
export type TargetSync = {
  target_id: number;
  kind: string;
  state: string;
  verified_at: number | null;
  next_check: number | null;
  pause_reason: null | "signed_out" | "identity_mismatch" | "maintenance_disabled";
  task_id: number | null;
};
const healthLabels = {
  unknown: "尚未检查", valid: "会话有效", signed_out: "已退出登录", error: "检查失败",
};
const syncLabels: Record<string, string> = {
  unknown: "尚未同步", verified: "已验证同步", ready: "历史同步成功", sync_pending: "等待同步",
  remote_outcome_unknown: "同步结果待确认", sync_unknown: "同步结果待确认", sync_failed: "同步失败",
  failed: "同步失败", unverified: "尚未验证", identity_mismatch: "账号身份不匹配",
};
const pauseLabels = {
  signed_out: "会话已退出，请重新登录", identity_mismatch: "账号身份不匹配", maintenance_disabled: "自动维护已关闭",
};
const errorLabels: Record<string, string> = {
  account_deleted: "账号已被 OpenAI 删除",
  account_deactivated: "账号已被 OpenAI 停用",
  account_suspended: "账号已被 OpenAI 暂停",
  account_rejected: "账号登录被 OpenAI 拒绝",
  identity_mismatch: "账号身份不匹配",
  check_failed: "检查失败",
};
function sessionMeta(session: WebSession | undefined, sep: ReactNode) {
  if (!session?.checked_at) return null;
  const checked = <>最近检查 <HealthTime value={session.checked_at} /></>;
  const reason = session.error_code && <>{sep}{errorLabels[session.error_code] || session.error_code}</>;
  if (session.error_code === "account_deleted") return <>{checked}{reason}</>;
  return <>{checked}{sep}{session.last_success_at != null ? <>最近成功 <HealthTime value={session.last_success_at} /></> : "尚无成功记录"}{reason}</>;
}
export function HealthTime({ value, now = Date.now() }: { value: number | null; now?: number }) {
  if (value === null) return <>暂无记录</>;
  const date = new Date(value * 1000);
  const delta = value * 1000 - now;
  const minutes = Math.max(1, Math.round(Math.abs(delta) / 60000));
  const amount = minutes < 60 ? `${minutes} 分钟` : minutes < 1440 ? `${Math.round(minutes / 60)} 小时` : `${Math.round(minutes / 1440)} 天`;
  return <time dateTime={date.toISOString()} title={date.toLocaleString("zh-CN", { timeZoneName: "short" })}>{Math.abs(delta) < 60000 ? "刚刚" : `${amount}${delta > 0 ? "后" : "前"}`}</time>;
}
export function SessionHealth({ session, syncs = [], targets, openTask }: {
  session?: WebSession;
  syncs?: TargetSync[];
  targets: { id: number; name: string }[];
  openTask: (id: number) => void;
}) {
  const active = session?.activity === "queued" || session?.activity === "checking";
  const sep = <span aria-hidden="true"> · </span>;
  return <section className="account-health" aria-label="会话与同步状态">
    <div className="health-row">
      <strong>网页会话</strong>
      <span className={`badge ${session?.status || "unknown"}`}>{healthLabels[session?.status || "unknown"]}</span>
      {active && <span className="badge running">{session?.activity === "queued" ? "检查排队中" : "正在检查会话"}</span>}
      {active && session?.task_id != null && <button className="health-task" onClick={() => openTask(session.task_id!)}>查看任务 #{session.task_id}</button>}
      <span className="muted">
        {sessionMeta(session, sep)}
      </span>
    </div>
    {syncs.map((sync) => <div key={sync.target_id} className="health-row target-health">
      <strong>{targets.find((target) => target.id === sync.target_id)?.name || `目标 #${sync.target_id}`}</strong>
      <span className={`badge ${sync.state}`}>{syncLabels[sync.state] || "同步状态待确认"}</span>
      {sync.task_id != null && <button className="health-task" onClick={() => openTask(sync.task_id!)}>查看任务 #{sync.task_id}</button>}
      <span className="muted">
        {sync.verified_at != null && <>验证于 <HealthTime value={sync.verified_at} />{sep}</>}
        {sync.pause_reason ? <>维护已暂停：{pauseLabels[sync.pause_reason]}</> : sync.next_check !== null ? <>{sync.next_check * 1000 <= Date.now() ? "维护已到期，等待检查" : "下次维护"} <HealthTime value={sync.next_check} /></> : "维护时间尚未安排"}
      </span>
    </div>)}
  </section>;
}
import type { ReactNode } from "react";
