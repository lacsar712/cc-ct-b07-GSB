import { createSignal, onCleanup, onMount, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  fetchSubmission,
  fetchSubmissions,
  fetchSlowdown,
  getUser,
  login,
  setSession,
  updateSlowdownConfig,
} from "./api";

const statusLabel = {
  pending: "待复核",
  processing: "复核中",
  done: "已完成",
};

const roleLabel = {
  machinist: "操作员",
  auditor: "复核员",
};

const priorityLabel = {
  normal: "普通",
  urgent: "急补",
};

function readHash() {
  const raw = (location.hash || "#/").replace(/^#/, "") || "/";
  let m = raw.match(/^\/detail\/(\d+)/);
  if (m) return { name: "detail", id: Number(m[1]) };
  if (raw === "/slowdown") return { name: "slowdown", id: null };
  return { name: "home", id: null };
}

function fmtTime(value) {
  return value ? new Date(value).toLocaleString() : "—";
}

function App() {
  const [user, setUser] = createSignal(getUser());
  const [rows, setRows] = createSignal([]);
  const [detail, setDetail] = createSignal(null);
  const [route, setRoute] = createSignal(readHash());
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const [loginUser, setLoginUser] = createSignal("machinist");
  const [loginPass, setLoginPass] = createSignal("machine123456");

  const [toolCode, setToolCode] = createSignal("");
  const [offsetUm, setOffsetUm] = createSignal("");
  const [priority, setPriority] = createSignal("normal");

  const [slowdown, setSlowdown] = createSignal(null);
  const [cfgThreshold, setCfgThreshold] = createSignal("2");
  const [cfgCooldown, setCfgCooldown] = createSignal("10");
  const [savingCfg, setSavingCfg] = createSignal(false);

  let timer = null;

  function goHome() {
    location.hash = "#/";
  }

  function goDetail(id) {
    location.hash = `#/detail/${id}`;
  }

  function goSlowdown() {
    location.hash = "#/slowdown";
  }

  async function loadRows(silent = false) {
    if (!silent) setLoading(true);
    setError("");
    try {
      setRows(await fetchSubmissions());
    } catch (e) {
      setError(e.message);
    } finally {
      if (!silent) setLoading(false);
    }
  }

  async function loadDetail(id) {
    setLoading(true);
    setError("");
    try {
      setDetail(await fetchSubmission(id));
    } catch (e) {
      setError(e.message);
      setDetail(null);
    } finally {
      setLoading(false);
    }
  }

  async function loadSlowdown(silent = true) {
    try {
      const data = await fetchSlowdown();
      setSlowdown(data);
      const el = document.activeElement;
      if (!silent || !el || el.tagName !== "INPUT") {
        setCfgThreshold(String(data.config.threshold));
        setCfgCooldown(String(data.config.cooldown_seconds));
      }
    } catch (e) {
      if (!silent) setError(e.message);
    }
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    if (user()) {
      if (route().name === "detail") loadDetail(route().id);
      else if (route().name === "slowdown") loadSlowdown(false);
      else {
        loadRows();
        loadSlowdown(true);
      }
    }
    timer = setInterval(() => {
      if (!user()) return;
      const r = route();
      if (r.name === "home") {
        loadRows(true);
        loadSlowdown(true);
      } else if (r.name === "slowdown") loadSlowdown(true);
    }, 2000);
    onCleanup(() => {
      window.removeEventListener("hashchange", onHash);
      if (timer) clearInterval(timer);
    });
  });

  createEffect(() => {
    const r = route();
    if (!user()) return;
    if (r.name === "detail" && r.id) loadDetail(r.id);
    if (r.name === "home") {
      loadRows();
      loadSlowdown(true);
    }
    if (r.name === "slowdown") loadSlowdown(false);
  });

  async function handleLogin(e) {
    e.preventDefault();
    setError("");
    try {
      const data = await login(loginUser(), loginPass());
      setSession(data.token, {
        username: data.username,
        role: data.role,
        can_write: data.can_write,
      });
      setUser(getUser());
      goHome();
      await loadRows();
    } catch (err) {
      setError(err.message);
    }
  }

  function handleLogout() {
    clearSession();
    setUser(null);
    setRows([]);
    setDetail(null);
    setSlowdown(null);
    goHome();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await createSubmission(toolCode(), offsetUm(), priority());
      setToolCode("");
      setOffsetUm("");
      await loadRows();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSaveConfig(e) {
    e.preventDefault();
    setError("");
    const threshold = Number(cfgThreshold());
    const cooldown = Number(cfgCooldown());
    if (!Number.isInteger(threshold) || threshold < 1) {
      setError("条数阈值须为不小于 1 的整数");
      return;
    }
    if (!Number.isInteger(cooldown) || cooldown < 1) {
      setError("缓领秒数须为不小于 1 的整数");
      return;
    }
    setSavingCfg(true);
    try {
      await updateSlowdownConfig({ threshold, cooldown_seconds: cooldown });
      await loadSlowdown(false);
    } catch (err) {
      setError(err.message);
    } finally {
      setSavingCfg(false);
    }
  }

  return (
    <div class="page">
      <header class="topbar">
        <div class="brand">
          <h1>数控刀补复核台</h1>
          <p class="hint">刀补绝对值不超过十二微米判合格，否则超差。连续超差达阈值触发缓领：缓领秒数内普通刀补暂停认领，急补仍可认领。</p>
        </div>
        <Show when={user()}>
          <nav class="topnav">
            <a
              href="#/"
              class={route().name === "home" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goHome();
              }}
            >
              复核总览
            </a>
            <a
              href="#/slowdown"
              class={route().name === "slowdown" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                goSlowdown();
              }}
            >
              缓领台
            </a>
          </nav>
        </Show>
      </header>

      <Show when={error()}>
        <div class="banner error">{error()}</div>
      </Show>

      <Show
        when={user()}
        fallback={
          <section class="card">
            <h2>登录</h2>
            <form onSubmit={handleLogin} class="form">
              <label>
                用户名
                <input
                  value={loginUser()}
                  onInput={(e) => setLoginUser(e.currentTarget.value)}
                />
              </label>
              <label>
                密码
                <input
                  type="password"
                  value={loginPass()}
                  onInput={(e) => setLoginPass(e.currentTarget.value)}
                />
              </label>
              <button type="submit">进入系统</button>
            </form>
            <p class="hint">操作员 machinist / machine123456；复核员 auditor / audit123456（只读）</p>
          </section>
        }
      >
        <section class="card toolbar">
          <div>
            当前用户：<strong>{user().username}</strong>（{roleLabel[user().role] || user().role}）
          </div>
          <button type="button" class="ghost" onClick={handleLogout}>
            退出
          </button>
        </section>

        <Show when={route().name === "home"}>
          <Show when={user().can_write}>
            <section class="card">
              <h2>提交刀补</h2>
              <form onSubmit={handleSubmit} class="form inline">
                <label>
                  刀具编号
                  <input
                    placeholder="如 T01"
                    value={toolCode()}
                    onInput={(e) => setToolCode(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  刀补（微米）
                  <input
                    type="number"
                    value={offsetUm()}
                    onInput={(e) => setOffsetUm(e.currentTarget.value)}
                    required
                  />
                </label>
                <label>
                  类型
                  <select value={priority()} onChange={(e) => setPriority(e.currentTarget.value)}>
                    <option value="normal">普通</option>
                    <option value="urgent">急补</option>
                  </select>
                </label>
                <button type="submit">提交待复核</button>
              </form>
            </section>
          </Show>

          <section class="card">
            <div class="toolbar">
              <h2>复核列表</h2>
              <button type="button" class="ghost" onClick={() => loadRows()} disabled={loading()}>
                {loading() ? "刷新中…" : "刷新"}
              </button>
            </div>
            <table>
              <thead>
                <tr>
                  <th>刀具</th>
                  <th>刀补 µm</th>
                  <th>类型</th>
                  <th>状态</th>
                  <th>结论</th>
                  <th>提交时间</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                <For each={rows()}>
                  {(row) => (
                    <tr class={row.status === "pending" && slowdown?.()?.active && row.priority === "normal" ? "held" : ""}>
                      <td>{row.tool_code}</td>
                      <td>{row.offset_um}</td>
                      <td class={row.priority === "urgent" ? "urgent" : ""}>
                        {priorityLabel[row.priority] || row.priority}
                      </td>
                      <td>{statusLabel[row.status] || row.status}</td>
                      <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                        {row.verdict || "—"}
                      </td>
                      <td>{new Date(row.created_at).toLocaleString()}</td>
                      <td>
                        <button type="button" class="ghost" onClick={() => goDetail(row.id)}>
                          详情
                        </button>
                      </td>
                    </tr>
                  )}
                </For>
              </tbody>
            </table>
            <Show when={!rows().length && !loading()}>
              <p class="hint">暂无记录</p>
            </Show>
          </section>
        </Show>

        <Show when={route().name === "detail"}>
          <section class="card">
            <div class="toolbar">
              <h2>刀补详情</h2>
              <button type="button" class="ghost" onClick={goHome}>
                返回总览
              </button>
            </div>
            <Show when={detail()} fallback={<p class="hint">{loading() ? "加载中…" : "未找到记录"}</p>}>
              {(d) => (
                <div class="detail-grid">
                  <p>编号：{d().id}</p>
                  <p>刀具：{d().tool_code}</p>
                  <p>刀补 µm：{d().offset_um}</p>
                  <p>类型：{priorityLabel[d().priority] || d().priority}</p>
                  <p>状态：{statusLabel[d().status] || d().status}</p>
                  <p class={d().verdict === "合格" ? "pass" : d().verdict === "超差" ? "fail" : ""}>
                    结论：{d().verdict || "—"}
                  </p>
                  <p>提交时间：{new Date(d().created_at).toLocaleString()}</p>
                  <p>
                    复核时间：
                    {d().reviewed_at ? new Date(d().reviewed_at).toLocaleString() : "—"}
                  </p>
                </div>
              )}
            </Show>
          </section>
        </Show>

        <Show when={route().name === "slowdown"}>
          <section class="card">
            <div class="toolbar">
              <h2>缓领台</h2>
              <button type="button" class="ghost" onClick={() => loadSlowdown(false)}>
                刷新
              </button>
            </div>

            <Show when={slowdown()} fallback={<p class="hint">{loading() ? "加载中…" : "暂无数据"}</p>}>
              {(sd) => (
                <div class="slowdown-body">
                  <div class="status-row">
                    <span class={"lamp " + (sd().active ? "lamp-on" : "lamp-off")} />
                    <strong>{sd().active ? "缓领中" : "未在缓"}</strong>
                    <Show when={sd().active}>
                      <span class="hint">
                        第 {sd().episode} 轮 · 剩余约 {sd().remaining_seconds} 秒 · 截至 {fmtTime(sd().until_at)}
                      </span>
                    </Show>
                  </div>

                  <section class="sub">
                    <h3>阈值与缓领秒数</h3>
                    <Show
                      when={user().can_write}
                      fallback={
                        <div class="readonly-box">
                          <p>连续超达条数阈值：<strong>{sd().config.threshold}</strong> 条</p>
                          <p>缓领秒数：<strong>{sd().config.cooldown_seconds}</strong> 秒</p>
                          <p class="hint">复核员只读，不能修改阈值与秒数。修改阈值不追溯旧流水。</p>
                        </div>
                      }
                    >
                      <form onSubmit={handleSaveConfig} class="form inline">
                        <label>
                          连续超差条数阈值
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={cfgThreshold()}
                            onInput={(e) => setCfgThreshold(e.currentTarget.value)}
                            required
                          />
                        </label>
                        <label>
                          缓领秒数
                          <input
                            type="number"
                            min="1"
                            step="1"
                            value={cfgCooldown()}
                            onInput={(e) => setCfgCooldown(e.currentTarget.value)}
                            required
                          />
                        </label>
                        <button type="submit" disabled={savingCfg()}>
                          {savingCfg() ? "保存中…" : "保存设置"}
                        </button>
                      </form>
                      <p class="hint">设置即时生效，不追溯已记录的缓领流水。</p>
                    </Show>
                  </section>

                  <section class="sub">
                    <h3>起止流水总览</h3>
                    <table>
                      <thead>
                        <tr>
                          <th>轮次</th>
                          <th>事件</th>
                          <th>时间</th>
                          <th>阈值快照(条)</th>
                          <th>秒数快照</th>
                          <th>缓至</th>
                          <th>触发记录</th>
                          <th>备注</th>
                        </tr>
                      </thead>
                      <tbody>
                        <For each={sd().events}>
                          {(ev) => (
                            <tr>
                              <td>#{ev.episode}</td>
                              <td class={ev.kind === "start" ? "fail" : "pass"}>
                                {ev.kind === "start" ? "开始" : "解除"}
                              </td>
                              <td>{fmtTime(ev.occurred_at)}</td>
                              <td>{ev.threshold_snapshot}</td>
                              <td>{ev.cooldown_seconds_snapshot}</td>
                              <td>{fmtTime(ev.until_at)}</td>
                              <td>
                                <Show when={ev.trigger_submissions?.length}>
                                  {ev.trigger_submissions
                                    .map((s) => `${s.tool_code}(${s.offset_um}µm)`)
                                    .join("、")}
                                </Show>
                              </td>
                              <td>{ev.note}</td>
                            </tr>
                          )}
                        </For>
                      </tbody>
                    </table>
                    <Show when={!sd().events.length}>
                      <p class="hint">暂无缓领流水</p>
                    </Show>
                  </section>
                </div>
              )}
            </Show>
          </section>
        </Show>
      </Show>
    </div>
  );
}

export default App;
