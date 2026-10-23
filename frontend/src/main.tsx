import {
  StrictMode,
  useEffect,
  useState,
  useRef,
  type FormEvent,
  type ReactNode,
} from "react";
import { createRoot } from "react-dom/client";
import { api, setCsrf, ApiError } from "./api";
import "./style.css";

type Account = {
  id: number;
  username: string;
  status: string;
  route_type: string;
  target_ids: number[];
  has_password: boolean;
  has_totp: boolean;
  has_mailbox: boolean;
};
type Target = {
  id: number;
  kind: string;
  name: string;
  verification: string;
  config?: { base_url?: string; allow_http?: boolean; compatibility?: string };
};
type Task = {
  id: number;
  account_id: number;
  account_username?: string;
  target_id: number;
  state: string;
  phase?: string;
  message?: string;
  created_at?: string;
  takeover_available?: boolean;
};
type Page = "accounts" | "targets" | "tasks" | "settings";
type TaskEvent = {
  event_id: string;
  task_id: number;
  state: string;
  phase?: string;
  message?: string;
  created_at?: string;
};
function restoredNavigation(): { page: Page; task: number | null } {
  const match = window.location.hash.match(
    /^#(accounts|targets|tasks|settings)(?:\/(\d+))?$/,
  );
  return {
    page: (match?.[1] as Page) || "accounts",
    task: match?.[1] === "tasks" && match[2] ? Number(match[2]) : null,
  };
}
const terminalStates = new Set([
  "succeeded",
  "failed",
  "cancelled",
  "interrupted",
]);
const labels: Record<string, string> = {
  queued: "排队中",
  running: "正在登录",
  waiting_human: "等待操作",
  browser: "浏览器已就绪",
  login: "正在打开登录页面",
  username: "正在提交账号",
  password: "正在提交密码",
  totp: "正在提交验证器代码",
  consent: "正在确认授权",
  token_exchange: "正在获取认证凭据",
  resuming: "正在检查浏览器",
  sync_failed: "同步失败",
  sync_unknown: "同步结果待确认",
  remote_outcome_unknown: "目标同步结果待确认",
  sync_pending: "等待同步",
  succeeded: "已完成",
  failed: "失败",
  cancelled: "已取消",
  interrupted: "已中断",
  unset: "未设置",
  direct: "直连",
  proxy: "代理",
  unverified: "未验证",
  verified: "已验证",
};
const label = (v: string) => labels[v] || v;
const message = (e: unknown) =>
  e instanceof Error ? e.message : "操作失败，请重试";
function Status({ value }: { value: string }) {
  return <span className={`badge ${value}`}>{label(value)}</span>;
}
function Field({ title, children }: { title: string; children: ReactNode }) {
  return (
    <label className="field">
      <span>{title}</span>
      {children}
    </label>
  );
}
function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return error ? (
    <div className="error" role="alert">
      {error}
      {retry && (
        <button type="button" onClick={retry}>
          重试
        </button>
      )}
    </div>
  ) : null;
}
function Modal({
  title,
  close,
  children,
}: {
  title: string;
  close: () => void;
  children: ReactNode;
}) {
  const dialog = useRef<HTMLElement>(null);
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null;
    const elements = () =>
      Array.from(
        dialog.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), input:not(:disabled), select:not(:disabled), textarea:not(:disabled), a[href]",
        ) || [],
      ).filter((el) => !el.closest("details:not([open])"));
    elements()[0]?.focus();
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") close();
      if (event.key === "Tab") {
        const items = elements();
        const first = items[0],
          last = items[items.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previous?.focus();
    };
  }, [close]);
  return (
    <div
      className="overlay"
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
    >
      <section
        ref={dialog}
        className="modal"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button aria-label="关闭" onClick={close}>
            ×
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
function useMutation() {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const inFlight = useRef(false);
  async function run(fn: () => Promise<void>) {
    if (inFlight.current) return;
    inFlight.current = true;
    setBusy(true);
    setError("");
    setSuccess("");
    try {
      await fn();
    } catch (e) {
      setError(message(e));
    } finally {
      inFlight.current = false;
      setBusy(false);
    }
  }
  return { busy, error, success, setSuccess, run };
}
function Login({ done }: { done: () => void }) {
  const [password, setPassword] = useState("");
  const m = useMutation();
  return (
    <main className="login">
      <div className="brand">AUTH BRIDGE</div>
      <h1>管理登录</h1>
      <p className="muted">登录以管理账号与同步任务</p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void m.run(async () => {
            const v = await api<{ csrf_token: string }>("/auth/login", "POST", {
              password,
            });
            setCsrf(v.csrf_token);
            setPassword("");
            done();
          });
        }}
      >
        <Field title="管理员密码">
          <input
            autoFocus
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <ErrorBox error={m.error} />
        <button className="primary" disabled={m.busy}>
          {m.busy ? "正在登录…" : "登录"}
        </button>
      </form>
    </main>
  );
}
export function App() {
  const [session, setSession] = useState<"loading" | "yes" | "no" | "error">(
    "loading",
  );
  const [sessionError, setSessionError] = useState("");
  const [page, setPage] = useState<Page>(() => restoredNavigation().page);
  const [accounts, setAccounts] = useState<Account[] | null>(null);
  const [targets, setTargets] = useState<Target[] | null>(null);
  const [tasks, setTasks] = useState<Task[] | null>(null);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);
  const [modal, setModal] = useState<ReactNode>(null);
  const [selectedTask, setSelectedTask] = useState<number | null>(
    () => restoredNavigation().task,
  );
  useEffect(() => {
    const hash = `#${page}${page === "tasks" && selectedTask !== null ? `/${selectedTask}` : ""}`;
    window.history.replaceState(null, "", hash);
  }, [page, selectedTask]);
  useEffect(() => {
    const restore = () => {
      const nav = restoredNavigation();
      setPage(nav.page);
      setSelectedTask(nav.task);
    };
    window.addEventListener("hashchange", restore);
    return () => window.removeEventListener("hashchange", restore);
  }, []);
  const m = useMutation();
  async function checkSession() {
    setSession("loading");
    try {
      const v = await api<{ csrf_token: string }>("/auth/session");
      setCsrf(v.csrf_token);
      setSession("yes");
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        setSessionError(message(e));
        setSession("no");
      } else {
        setSessionError(message(e));
        setSession("error");
      }
    }
  }
  useEffect(() => {
    void checkSession();
    const expired = () => {
      setCsrf("");
      setAccounts(null);
      setTargets(null);
      setTasks(null);
      setModal(null);
      setSelectedTask(null);
      setSession("no");
    };
    window.addEventListener("session-expired", expired);
    return () => window.removeEventListener("session-expired", expired);
  }, []);
  async function refresh() {
    setLoading(true);
    setError("");
    try {
      const [a, t, k] = await Promise.all([
        api<{ accounts: Account[] }>("/accounts"),
        api<{ targets: Target[] }>("/targets"),
        api<{ tasks: Task[] }>("/tasks"),
      ]);
      setAccounts(a.accounts);
      setTargets(t.targets);
      setTasks(k.tasks);
    } catch (e) {
      setError(message(e));
    } finally {
      setLoading(false);
    }
  }
  useEffect(() => {
    if (session === "yes") void refresh();
  }, [session]);
  const close = () => setModal(null);
  const saved = async () => {
    await refresh();
    close();
  };
  if (session === "loading")
    return (
      <main className="login" role="status">
        正在连接…
      </main>
    );
  if (session === "no") return <Login done={() => setSession("yes")} />;
  if (session === "error")
    return (
      <main>
        <ErrorBox error={sessionError} retry={() => void checkSession()} />
      </main>
    );
  const openTask = (id: number) => {
    setSelectedTask(id);
    setPage("tasks");
  };
  return (
    <div className="shell">
      <aside>
        <div className="brand">AUTH BRIDGE</div>
        <p className="aside-caption">账号认证与同步</p>
        <nav aria-label="主导航">
          {(
            [
              ["accounts", "账号"],
              ["targets", "目标"],
              ["tasks", "任务"],
              ["settings", "设置"],
            ] as [Page, string][]
          ).map(([key, name]) => (
            <button
              key={key}
              aria-current={page === key ? "page" : undefined}
              onClick={() => setPage(key)}
            >
              {name}
            </button>
          ))}
        </nav>
        <button
          className="logout"
          disabled={m.busy}
          onClick={() =>
            void m.run(async () => {
              await api("/auth/logout", "POST");
              setCsrf("");
              setSession("no");
            })
          }
        >
          退出登录
        </button>
      </aside>
      <main>
        <header className="page-header">
          <div>
            <div className="eyebrow">工作空间</div>
            <h1>
              {
                {
                  accounts: "账号",
                  targets: "目标",
                  tasks: "任务",
                  settings: "设置",
                }[page]
              }
            </h1>
          </div>
          <button disabled={loading} onClick={() => void refresh()}>
            {loading ? "更新中…" : "刷新"}
          </button>
        </header>
        <ErrorBox error={error || m.error} retry={() => void refresh()} />
        {page === "accounts" && (
          <>
            <div className="toolbar">
              <p className="muted">
                {accounts ? `${accounts.length} 个账号` : "正在加载账号…"}
              </p>
              <div className="actions">
                <button
                  onClick={() =>
                    setModal(<ImportAccounts close={close} saved={saved} />)
                  }
                >
                  导入账号
                </button>
                <button
                  className="primary"
                  onClick={() =>
                    setModal(
                      <AccountForm
                        targets={targets || []}
                        close={close}
                        saved={saved}
                      />,
                    )
                  }
                >
                  添加账号
                </button>
              </div>
            </div>
            {accounts &&
              (accounts.length ? (
                <div className="cards">
                  {accounts.map((a) => (
                    <article key={a.id} className="resource">
                      <div className="resource-heading">
                        <h2>{a.username}</h2>
                        <Status value={a.status} />
                      </div>
                      <p className="muted">
                        网络：{label(a.route_type)} · 已绑定{" "}
                        {a.target_ids.length} 个目标
                      </p>
                      <p className="secrets">
                        {a.has_password ? "密码已设置" : "未设置密码"} ·{" "}
                        {a.has_totp ? "验证器已设置" : "未设置验证器"} ·{" "}
                        {a.has_mailbox ? "邮箱已设置" : "未设置邮箱"}
                      </p>
                      <div className="actions">
                        <button
                          className="primary"
                          onClick={() =>
                            setModal(
                              <StartTask
                                account={a}
                                targets={targets || []}
                                close={close}
                                started={async (id) => {
                                  close();
                                  await refresh();
                                  openTask(id);
                                }}
                              />,
                            )
                          }
                        >
                          开始登录
                        </button>
                        <button
                          onClick={() =>
                            setModal(
                              <AccountForm
                                account={a}
                                targets={targets || []}
                                close={close}
                                saved={saved}
                              />,
                            )
                          }
                        >
                          编辑与绑定
                        </button>
                        <button
                          className="danger"
                          disabled={m.busy}
                          onClick={() => {
                            if (
                              confirm(
                                `删除账号 ${a.username}？此操作无法撤销。`,
                              )
                            )
                              void m.run(async () => {
                                await api(`/accounts/${a.id}`, "DELETE");
                                await refresh();
                              });
                          }}
                        >
                          删除账号
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty">还没有账号。请添加或导入账号。</div>
              ))}
          </>
        )}
        {page === "targets" && (
          <>
            <div className="toolbar">
              <p className="muted">
                {targets ? `${targets.length} 个目标` : "正在加载目标…"}
              </p>
              <button
                className="primary"
                onClick={() =>
                  setModal(<TargetForm close={close} saved={saved} />)
                }
              >
                添加目标
              </button>
            </div>
            {targets &&
              (targets.length ? (
                <div className="cards">
                  {targets.map((t) => (
                    <article className="resource" key={t.id}>
                      <div className="resource-heading">
                        <h2>{t.name}</h2>
                        <Status value={t.verification || "unverified"} />
                      </div>
                      <p className="muted">{t.kind}</p>
                      <div className="actions">
                        <button
                          disabled={m.busy}
                          onClick={() =>
                            void m.run(async () => {
                              const result = await api<{
                                reachable: boolean;
                                verification: string;
                              }>(`/targets/${t.id}/test`, "POST");
                              m.setSuccess(
                                result.reachable
                                  ? "目标可连接；真实账号同步仍需验证。"
                                  : "目标暂时无法连接。",
                              );
                              await refresh();
                            })
                          }
                        >
                          测试连接
                        </button>
                        <button
                          onClick={() =>
                            setModal(
                              <TargetForm
                                target={t}
                                close={close}
                                saved={saved}
                              />,
                            )
                          }
                        >
                          编辑目标
                        </button>
                        <button
                          className="danger"
                          disabled={m.busy}
                          onClick={() => {
                            if (confirm(`删除目标 ${t.name}？`))
                              void m.run(async () => {
                                await api(`/targets/${t.id}`, "DELETE");
                                await refresh();
                              });
                          }}
                        >
                          删除目标
                        </button>
                      </div>
                    </article>
                  ))}
                </div>
              ) : (
                <div className="empty">还没有目标。请添加目标。</div>
              ))}
            {m.success && (
              <p role="status" className="success">
                {m.success}
              </p>
            )}
          </>
        )}
        {page === "tasks" && (
          <div className="task-layout">
            <section>
              <div className="toolbar">
                <p className="muted">
                  {tasks ? `${tasks.length} 个任务` : "正在加载任务…"}
                </p>
              </div>
              {tasks &&
                (tasks.length ? (
                  <div className="task-list">
                    {tasks.map((t) => (
                      <button
                        className={`task-row ${selectedTask === t.id ? "selected" : ""}`}
                        key={t.id}
                        onClick={() => setSelectedTask(t.id)}
                      >
                        <span>
                          任务 #{t.id}
                          <small>
                            {accounts?.find((a) => a.id === t.account_id)
                              ?.username || `账号 #${t.account_id}`}
                          </small>
                        </span>
                        <Status value={t.state} />
                      </button>
                    ))}
                  </div>
                ) : (
                  <div className="empty">还没有任务。请从账号开始登录。</div>
                ))}
            </section>
            {selectedTask !== null ? (
              <TaskDetail
                key={selectedTask}
                id={selectedTask}
                updated={() => void refresh()}
              />
            ) : (
              <div className="empty detail-empty">选择任务查看进度</div>
            )}
          </div>
        )}
        {page === "settings" && <Settings />}
      </main>
      {modal}
    </div>
  );
}
function AccountForm({
  account,
  targets,
  close,
  saved,
}: {
  account?: Account;
  targets: Target[];
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [username, setUsername] = useState(account?.username || "");
  const [password, setPassword] = useState("");
  const [totp, setTotp] = useState("");
  const [mailbox, setMailbox] = useState("");
  const [allowHttp, setAllowHttp] = useState(false);
  const [route, setRoute] = useState(account?.route_type || "unset");
  const [server, setServer] = useState("");
  const [proxyUser, setProxyUser] = useState("");
  const [proxyPassword, setProxyPassword] = useState("");
  const [ids, setIds] = useState<number[]>(account?.target_ids || []);
  const [clearTotp, setClearTotp] = useState(false);
  const [clearMailbox, setClearMailbox] = useState(false);
  const m = useMutation();
  async function submit(e: FormEvent) {
    e.preventDefault();
    if (
      account &&
      (password || totp || mailbox || clearTotp || clearMailbox || server) &&
      !confirm("确认替换或清除所选凭据？留空的凭据会保留。")
    )
      return;
    await m.run(async () => {
      const body = {
        username,
        route_type: route,
        target_ids: ids,
        ...(password ? { password } : {}),
        ...(totp ? { totp } : clearTotp ? { totp: null } : {}),
        ...(mailbox
          ? { mailbox_url: mailbox, allow_http_mailbox: allowHttp }
          : clearMailbox
            ? { mailbox_url: null }
            : {}),
        ...(route === "proxy" && server
          ? {
              proxy: {
                server,
                ...(proxyUser ? { username: proxyUser } : {}),
                ...(proxyPassword ? { password: proxyPassword } : {}),
              },
            }
          : {}),
      };
      await api(
        account ? `/accounts/${account.id}` : "/accounts",
        account ? "PATCH" : "POST",
        body,
      );
      await saved();
    });
  }
  return (
    <Modal title={account ? "编辑账号" : "添加账号"} close={close}>
      <form onSubmit={(e) => void submit(e)}>
        <Field title="账号邮箱">
          <input
            type="email"
            required
            autoComplete="off"
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </Field>
        <Field title={account ? "新密码（留空保留）" : "密码"}>
          <input
            type="password"
            autoComplete="new-password"
            required={!account}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </Field>
        <details>
          <summary>验证与邮箱</summary>
          <Field title="验证器密钥（留空保留）">
            <input
              type="password"
              autoComplete="off"
              value={totp}
              onChange={(e) => setTotp(e.target.value)}
            />
          </Field>
          {account?.has_totp && (
            <label className="check">
              <input
                type="checkbox"
                checked={clearTotp}
                onChange={(e) => setClearTotp(e.target.checked)}
              />
              清除现有验证器密钥
            </label>
          )}
          <Field title="邮箱取码地址（留空保留）">
            <input
              type="password"
              autoComplete="off"
              value={mailbox}
              onChange={(e) => setMailbox(e.target.value)}
              placeholder="https://…"
            />
          </Field>
          <label className="check">
            <input
              type="checkbox"
              checked={allowHttp}
              onChange={(e) => setAllowHttp(e.target.checked)}
            />
            允许不加密的 HTTP 邮箱地址
          </label>
          {account?.has_mailbox && (
            <label className="check">
              <input
                type="checkbox"
                checked={clearMailbox}
                onChange={(e) => setClearMailbox(e.target.checked)}
              />
              清除现有邮箱地址
            </label>
          )}
        </details>
        <Field title="网络路由">
          <select value={route} onChange={(e) => setRoute(e.target.value)}>
            <option value="unset">未设置</option>
            <option value="direct">直连</option>
            <option value="proxy">代理</option>
          </select>
        </Field>
        {route === "proxy" && (
          <>
            <Field title={account ? "新代理地址（留空保留）" : "代理地址"}>
              <input
                type="password"
                autoComplete="off"
                required={!account}
                value={server}
                placeholder="http://host:port"
                onChange={(e) => setServer(e.target.value)}
              />
            </Field>
            <Field title="代理用户名">
              <input
                type="password"
                autoComplete="off"
                value={proxyUser}
                onChange={(e) => setProxyUser(e.target.value)}
              />
            </Field>
            <Field title="代理密码">
              <input
                type="password"
                autoComplete="new-password"
                value={proxyPassword}
                onChange={(e) => setProxyPassword(e.target.value)}
              />
            </Field>
          </>
        )}
        <fieldset>
          <legend>绑定目标</legend>
          {targets.length ? (
            targets.map((t) => (
              <label className="check" key={t.id}>
                <input
                  type="checkbox"
                  checked={ids.includes(t.id)}
                  onChange={(e) =>
                    setIds(
                      e.target.checked
                        ? [...ids, t.id]
                        : ids.filter((id) => id !== t.id),
                    )
                  }
                />
                {t.name}
              </label>
            ))
          ) : (
            <p className="muted">请先添加目标。</p>
          )}
        </fieldset>
        <ErrorBox error={m.error} />
        <div className="actions footer">
          <button type="button" onClick={close}>
            取消
          </button>
          <button className="primary" disabled={m.busy}>
            {m.busy ? "保存中…" : "保存账号"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
function ImportAccounts({
  close,
  saved,
}: {
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [text, setText] = useState("");
  const [records, setRecords] = useState<
    | { line: number; valid: boolean; duplicate?: boolean; error?: string }[]
    | null
  >(null);
  const m = useMutation();
  return (
    <Modal title="导入账号" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void m.run(async () => {
            const v = await api<{ records: typeof records }>(
              "/import/preview",
              "POST",
              { text },
            );
            setRecords(v.records);
          });
        }}
      >
        <Field title="账号文本">
          <textarea
            rows={8}
            required
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              setRecords(null);
            }}
            autoComplete="off"
            spellCheck={false}
            placeholder="每行一个账号；按项目支持的导入格式粘贴"
          />
        </Field>
        <ErrorBox error={m.error} />
        <button disabled={m.busy}>预览导入</button>
        {records && (
          <>
            <ul className="preview">
              {records.map((r) => (
                <li key={r.line}>
                  第 {r.line} 行：
                  {r.valid
                    ? r.duplicate
                      ? "已存在"
                      : "可导入"
                    : r.error || "格式有误"}
                </li>
              ))}
            </ul>
            <button
              type="button"
              className="primary"
              disabled={
                m.busy ||
                !records.some((r) => r.valid && !r.duplicate) ||
                records.some((r) => !r.valid)
              }
              onClick={() =>
                void m.run(async () => {
                  await api("/import/confirm", "POST", { text });
                  setText("");
                  await saved();
                })
              }
            >
              确认导入
            </button>
          </>
        )}
      </form>
    </Modal>
  );
}
function TargetForm({
  target,
  close,
  saved,
}: {
  target?: Target;
  close: () => void;
  saved: () => Promise<void>;
}) {
  const [kind, setKind] = useState(target?.kind || "cliproxyapi");
  const [name, setName] = useState(target?.name || "");
  const [url, setUrl] = useState(target?.config?.base_url || "");
  const [compatibility, setCompatibility] = useState(
    target?.config?.compatibility ||
      (target?.kind === "chatgpt-web-voice" ? "" : "cpa-auth-files-v1"),
  );
  const [key, setKey] = useState("");
  const [user, setUser] = useState("");
  const [password, setPassword] = useState("");
  const [allow, setAllow] = useState(target?.config?.allow_http || false);
  const m = useMutation();
  return (
    <Modal title={target ? "编辑目标" : "添加目标"} close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          if (target && (key || password) && !confirm("确认替换目标凭据？"))
            return;
          void m.run(async () => {
            await api(
              target ? `/targets/${target.id}` : "/targets",
              target ? "PATCH" : "POST",
              {
                name,
                kind,
                config: {
                  compatibility:
                    kind === "cliproxyapi"
                      ? "cpa-auth-files-v1"
                      : compatibility,
                  ...(url ? { base_url: url } : {}),
                  allow_http: allow,
                  ...(kind === "cliproxyapi"
                    ? key
                      ? { management_key: key }
                      : {}
                    : {
                        ...(user ? { admin_username: user } : {}),
                        ...(password ? { admin_password: password } : {}),
                      }),
                },
              },
            );
            await saved();
          });
        }}
      >
        <Field title="目标名称">
          <input
            required
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Field title="类型">
          <select
            disabled={!!target}
            value={kind}
            onChange={(e) => {
              setKind(e.target.value);
              setCompatibility(
                e.target.value === "cliproxyapi" ? "cpa-auth-files-v1" : "",
              );
            }}
          >
            <option value="cliproxyapi">CLIProxyAPI</option>
            <option value="chatgpt-web-voice">ChatGPT Web Voice</option>
          </select>
        </Field>
        <Field title={target ? "服务地址（留空保留）" : "服务地址"}>
          <input
            type="url"
            required={!target}
            placeholder="https://service.example"
            value={url}
            onChange={(e) => setUrl(e.target.value)}
          />
        </Field>
        {kind === "cliproxyapi" ? (
          <Field title={target ? "管理密钥（留空保留）" : "管理密钥"}>
            <input
              type="password"
              required={!target}
              autoComplete="new-password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
            />
          </Field>
        ) : (
          <>
            <Field title="管理员用户名（留空保留）">
              <input
                type="password"
                required={!target}
                autoComplete="off"
                value={user}
                onChange={(e) => setUser(e.target.value)}
              />
            </Field>
            <Field title="管理员密码（留空保留）">
              <input
                type="password"
                required={!target}
                autoComplete="new-password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>
          </>
        )}
        <label className="check">
          <input
            type="checkbox"
            checked={allow}
            onChange={(e) => setAllow(e.target.checked)}
          />
          允许不加密的 HTTP 连接
        </label>
        <p className="muted">真实账号同步能力尚未验证。</p>
        {kind === "chatgpt-web-voice" && (
          <Field title="同步接口兼容性">
            <select
              required
              value={compatibility}
              onChange={(e) => setCompatibility(e.target.value)}
            >
              <option value="">请选择</option>
              <option value="bridge-v1">服务端已实现 Bridge v1 接口</option>
            </select>
            <small>需由目标服务提供兼容接口。</small>
          </Field>
        )}
        <ErrorBox error={m.error} />
        <div className="actions footer">
          <button type="button" onClick={close}>
            取消
          </button>
          <button className="primary" disabled={m.busy}>
            {m.busy ? "保存中…" : "保存目标"}
          </button>
        </div>
      </form>
    </Modal>
  );
}
function StartTask({
  account,
  targets,
  close,
  started,
}: {
  account: Account;
  targets: Target[];
  close: () => void;
  started: (id: number) => Promise<void>;
}) {
  const available = targets.filter((t) => account.target_ids.includes(t.id));
  const [targetId, setTargetId] = useState(available[0]?.id || 0);
  const [key] = useState(() => crypto.randomUUID());
  const m = useMutation();
  return (
    <Modal title="开始登录" close={close}>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void m.run(async () => {
            const task = await api<Task & { task?: Task }>(
              `/accounts/${account.id}/tasks`,
              "POST",
              { target_id: targetId, idempotency_key: key },
            );
            await started(task.task?.id || task.id);
          });
        }}
      >
        <p>{account.username}</p>
        <Field title="同步目标">
          <select
            required
            value={targetId}
            onChange={(e) => setTargetId(Number(e.target.value))}
          >
            <option value="0" disabled>
              请选择目标
            </option>
            {available.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name}
              </option>
            ))}
          </select>
        </Field>
        {!available.length && (
          <p className="muted">请先在账号编辑中绑定目标。</p>
        )}
        {account.route_type === "unset" && (
          <p className="error">请先设置账号网络路由。</p>
        )}
        <ErrorBox error={m.error} />
        <button
          className="primary"
          disabled={m.busy || !targetId || account.route_type === "unset"}
        >
          {m.busy ? "提交中…" : "开始登录"}
        </button>
      </form>
    </Modal>
  );
}
function TaskDetail({ id, updated }: { id: number; updated: () => void }) {
  const [task, setTask] = useState<Task | null>(null);
  const [error, setError] = useState("");
  const [streamError, setStreamError] = useState("");
  const [history, setHistory] = useState<TaskEvent[]>([]);
  const [historyError, setHistoryError] = useState("");
  const [historyLoaded, setHistoryLoaded] = useState(false);
  const [code, setCode] = useState("");
  const [submission, setSubmission] = useState(() => crypto.randomUUID());
  const [takeover, setTakeover] = useState<string | null>(null);
  const m = useMutation();
  async function load() {
    try {
      const v = await api<Task & { task?: Task }>(`/tasks/${id}`);
      const current = v.task || v;
      setTask(current);
      setError("");
      return current;
    } catch (e) {
      setError(message(e));
    }
  }
  function mergeHistory(items: TaskEvent[]) {
    setHistory((old) =>
      Array.from(
        new Map(
          [...old, ...items].map((item) => [item.event_id, item]),
        ).values(),
      ).sort((a, b) => Number(a.event_id) - Number(b.event_id)),
    );
  }
  async function loadHistory() {
    try {
      const result = await api<{
        events: (Omit<TaskEvent, "event_id"> & { event_id: string | number })[];
      }>(`/tasks/${id}/history`);
      if (!Array.isArray(result.events)) throw new Error("无法读取执行记录");
      mergeHistory(
        result.events.map((item) => ({
          ...item,
          task_id: id,
          event_id: String(item.event_id),
        })),
      );
      setHistoryLoaded(true);
      setHistoryError("");
    } catch (e) {
      setHistoryError(message(e));
    }
  }
  useEffect(() => {
    void loadHistory();
    const events = new EventSource(`/api/v1/tasks/${id}/events`, {
      withCredentials: true,
    });
    let ended = false;
    void load().then((current) => {
      if (current && terminalStates.has(current.state)) {
        ended = true;
        events.close();
        setStreamError("");
      }
    });
    events.addEventListener("task", (e) => {
      try {
        const event = e as MessageEvent;
        const v = JSON.parse(event.data);
        if (v.task_id !== undefined && v.task_id !== id)
          throw new Error("Invalid task event");
        if (typeof v.state !== "string") throw new Error("Invalid task state");
        const item: TaskEvent = {
          event_id: String(v.event_id ?? event.lastEventId),
          task_id: id,
          state: v.state,
          phase: v.phase,
          message: v.message,
        };
        mergeHistory([item]);
        // Event IDs identify log rows, never the task itself.
        setTask(
          (old) =>
            ({
              ...old,
              id,
              state: v.state,
              phase: v.phase,
              message: v.message,
              ...(v.takeover_available !== undefined
                ? { takeover_available: !!v.takeover_available }
                : {}),
            }) as Task,
        );
        setStreamError("");
        if (terminalStates.has(v.state)) {
          ended = true;
          events.close();
        }
        void load();
        updated();
      } catch {
        setStreamError("无法读取任务更新，请刷新。");
      }
    });
    events.onopen = () => setStreamError("");
    events.onerror = () => {
      if (!ended) setStreamError("实时连接已断开，正在重连…");
    };
    return () => events.close();
  }, [id]);
  async function action(name: string, body?: unknown) {
    await m.run(async () => {
      const result = await api<Record<string, unknown>>(
        `/tasks/${id}/${name}`,
        "POST",
        body,
      );
      if (name === "takeover") {
        const url = result.url || result.takeover_url;
        if (typeof url === "string") {
          const parsed = new URL(url, window.location.origin);
          if (parsed.origin !== window.location.origin)
            throw new Error("接管地址必须与当前站点同源");
          setTakeover(parsed.href);
        } else
          setTakeover(
            `/novnc/vnc.html?autoconnect=true&resize=scale&path=api/v1/tasks/${id}/takeover`,
          );
      }
      if (name === "code") {
        setCode("");
        setSubmission(crypto.randomUUID());
      }
      await load();
      updated();
    });
  }
  const active =
    task && ["queued", "running", "waiting_human"].includes(task.state);
  return (
    <section className="task-detail">
      <header className="resource-heading">
        <h2>任务 #{id}</h2>
        {task && <Status value={task.state} />}
      </header>
      <ErrorBox error={error} retry={() => void load()} />
      {streamError && (
        <p className="muted" role="status">
          {streamError}
        </p>
      )}
      {task && (
        <>
          <p className="phase">{label(task.phase || task.state)}</p>
          {task.message && <p>{task.message}</p>}
          {task.state === "waiting_human" && (
            <>
              <form
                className="code-form"
                onSubmit={(e) => {
                  e.preventDefault();
                  void action("code", { code, submission_id: submission });
                }}
              >
                <Field title="验证码">
                  <input
                    value={code}
                    onChange={(e) => setCode(e.target.value)}
                    autoComplete="one-time-code"
                    required
                  />
                </Field>
                <button className="primary" disabled={m.busy}>
                  提交验证码
                </button>
              </form>
              <div className="actions">
                <button
                  disabled={m.busy || !task.takeover_available}
                  onClick={() => void action("takeover")}
                >
                  接管浏览器
                </button>
                <button
                  disabled={m.busy}
                  onClick={() => void action("continue")}
                >
                  继续任务
                </button>
              </div>
            </>
          )}
          {task.state === "running" && task.takeover_available && (
            <button
              disabled={m.busy || !!takeover}
              onClick={() => void action("takeover")}
            >
              接管浏览器
            </button>
          )}
          {task.state === "sync_pending" && (
            <button
              className="primary"
              disabled={m.busy}
              onClick={() => void action("retry-sync")}
            >
              重试同步
            </button>
          )}
          {task.state === "sync_pending" && task.phase === "sync_failed" && (
            <button
              className="danger discard-sync"
              disabled={m.busy || !task.account_username}
              onClick={() => {
                const confirmation = window.prompt(
                  `放弃账号 ${task.account_username} 的本地同步结果？目标服务可能已创建该账号，此操作不会删除目标服务中的账号。之后可以重新开始登录。请输入完整账号邮箱确认：`,
                );
                if (confirmation === null) return;
                if (confirmation !== task.account_username) {
                  void m.run(async () => {
                    throw new Error("账号邮箱不匹配，未放弃同步结果。");
                  });
                  return;
                }
                void action("discard-sync", { confirmation });
              }}
            >
              放弃本地同步结果
            </button>
          )}
          {active && (
            <button
              className="danger cancel"
              disabled={m.busy}
              onClick={() => {
                if (confirm("取消当前任务？正在进行的浏览器操作将终止。"))
                  void action("cancel");
              }}
            >
              取消任务
            </button>
          )}
          {takeover &&
            task.state === "waiting_human" &&
            task.takeover_available && (
              <Takeover url={takeover} close={() => setTakeover(null)} />
            )}
          {takeover && task.state === "running" && (
            <p role="status" className="muted">
              正在准备浏览器接管…
            </p>
          )}
          <ErrorBox error={m.error} />
          <section className="event-history" aria-label="执行记录">
            <h3>执行记录</h3>
            <ol role="log" aria-live="polite" aria-relevant="additions">
              {history.map((item) => (
                <li key={item.event_id}>
                  <span className="event-number">#{item.event_id}</span>
                  <div>
                    <Status value={item.state} />
                    <span className="event-phase">
                      {label(item.phase || item.state)}
                    </span>
                    {item.message && <p>{item.message}</p>}
                  </div>
                </li>
              ))}
            </ol>
            <ErrorBox error={historyError} retry={() => void loadHistory()} />
            {!history.length && !historyError && (
              <p className="muted">
                {historyLoaded ? "还没有执行记录。" : "正在读取执行记录…"}
              </p>
            )}
          </section>
        </>
      )}
    </section>
  );
}
function Takeover({ url, close }: { url: string; close: () => void }) {
  return (
    <div className="takeover">
      <h3>浏览器接管</h3>
      <p className="muted">完成浏览器操作后，返回此处点击“继续任务”。</p>
      <iframe title="接管浏览器" src={url} className="takeover-frame" />
      <a
        className="button"
        href={url}
        target="_blank"
        rel="noopener noreferrer"
      >
        打开接管窗口
      </a>
      <button onClick={close}>关闭接管面板</button>
    </div>
  );
}
function Settings() {
  const [settings, setSettings] = useState<{
    maintenance_enabled: boolean;
    retention_days: number;
  } | null>(null);
  const [runtime, setRuntime] = useState<{
    worker_alive: boolean;
    browser_available: boolean;
    maintenance_enabled: boolean;
    version: string;
  } | null>(null);
  const [error, setError] = useState("");
  const [current, setCurrent] = useState("");
  const [next, setNext] = useState("");
  const [repeat, setRepeat] = useState("");
  const m = useMutation();
  const p = useMutation();
  async function load() {
    try {
      const [s, r] = await Promise.all([
        api<NonNullable<typeof settings>>("/settings"),
        api<NonNullable<typeof runtime>>("/runtime"),
      ]);
      setSettings(s);
      setRuntime(r);
      setError("");
    } catch (e) {
      setError(message(e));
    }
  }
  useEffect(() => {
    void load();
  }, []);
  return (
    <div className="settings">
      <ErrorBox error={error} retry={() => void load()} />
      <section className="resource">
        <h2>运行状态</h2>
        {runtime && (
          <dl>
            <div>
              <dt>任务执行器</dt>
              <dd>{runtime.worker_alive ? "在线" : "离线"}</dd>
            </div>
            <div>
              <dt>浏览器</dt>
              <dd>{runtime.browser_available ? "可用" : "不可用"}</dd>
            </div>
            <div>
              <dt>版本</dt>
              <dd>{runtime.version}</dd>
            </div>
          </dl>
        )}
      </section>
      <section className="resource">
        <h2>系统设置</h2>
        {settings && (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void m.run(async () => {
                await api("/settings", "PATCH", settings);
                m.setSuccess("设置已保存");
                await load();
              });
            }}
          >
            <label className="check">
              <input
                type="checkbox"
                checked={settings.maintenance_enabled}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    maintenance_enabled: e.target.checked,
                  })
                }
              />
              自动维护网页会话
            </label>
            <Field title="任务记录保留天数">
              <input
                type="number"
                min="1"
                max="3650"
                required
                value={settings.retention_days}
                onChange={(e) =>
                  setSettings({
                    ...settings,
                    retention_days: Number(e.target.value),
                  })
                }
              />
            </Field>
            <ErrorBox error={m.error} />
            <button className="primary" disabled={m.busy}>
              保存设置
            </button>
            {m.success && (
              <p className="success" role="status">
                {m.success}
              </p>
            )}
          </form>
        )}
      </section>
      <section className="resource">
        <h2>修改管理员密码</h2>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void p.run(async () => {
              if (next !== repeat) throw new Error("两次输入的新密码不一致");
              await api("/auth/password", "POST", {
                current_password: current,
                new_password: next,
              });
              setCurrent("");
              setNext("");
              setRepeat("");
              p.setSuccess("密码已修改，请重新登录");
              window.dispatchEvent(new Event("session-expired"));
            });
          }}
        >
          <Field title="当前密码">
            <input
              type="password"
              autoComplete="current-password"
              required
              value={current}
              onChange={(e) => setCurrent(e.target.value)}
            />
          </Field>
          <Field title="新密码">
            <input
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
              value={next}
              onChange={(e) => setNext(e.target.value)}
            />
          </Field>
          <Field title="确认新密码">
            <input
              type="password"
              autoComplete="new-password"
              minLength={12}
              required
              value={repeat}
              onChange={(e) => setRepeat(e.target.value)}
            />
          </Field>
          <ErrorBox error={p.error} />
          <button disabled={p.busy}>修改密码</button>
          {p.success && <p role="status">{p.success}</p>}
        </form>
      </section>
    </div>
  );
}
const root = document.getElementById("root");
if (root)
  createRoot(root).render(
    <StrictMode>
      <App />
    </StrictMode>,
  );
