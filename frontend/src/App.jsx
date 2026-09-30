import { createSignal, onMount, onCleanup, Show, For, createEffect } from "solid-js";
import {
  clearSession,
  createSubmission,
  fetchHold,
  fetchSubmission,
  fetchSubmissions,
  getUser,
  login,
  setSession,
  updateHoldConfig,
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
  if (raw === "/hold") return { name: "hold", id: null };
  return { name: "home", id: null };
}

function fmtTime(v) {
  return v ? new Date(v).toLocaleString() : "—";
}

function App() {
  const [user, setUser] = createSignal(getUser());
  const [rows, setRows] = createSignal([]);
  const [detail, setDetail] = createSignal(null);
  const [hold, setHold] = createSignal(null);
  const [route, setRoute] = createSignal(readHash());
  const [error, setError] = createSignal("");
  const [loading, setLoading] = createSignal(false);

  const [loginUser, setLoginUser] = createSignal("machinist");
  const [loginPass, setLoginPass] = createSignal("machine123456");

  const [toolCode, setToolCode] = createSignal("");
  const [offsetUm, setOffsetUm] = createSignal("");
  const [priority, setPriority] = createSignal("normal");

  const [threshold, setThreshold] = createSignal("2");
  const [seconds, setSeconds] = createSignal("30");
  const [savingCfg, setSavingCfg] = createSignal(false);

  function goHome() {
    location.hash = "#/";
  }

  function goDetail(id) {
    location.hash = `#/detail/${id}`;
  }

  async function loadRows() {
    try {
      setRows(await fetchSubmissions());
    } catch (e) {
      setError(e.message);
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

  async function loadHold() {
    try {
      const data = await fetchHold();
      setHold(data);
      // 仅在输入框未聚焦时回填，避免打断操作员编辑
      const activeEl = document.activeElement;
      if (activeEl?.dataset?.holdField !== "threshold") {
        setThreshold(String(data.fail_threshold));
      }
      if (activeEl?.dataset?.holdField !== "seconds") {
        setSeconds(String(data.hold_seconds));
      }
    } catch (e) {
      setError(e.message);
    }
  }

  function refreshCurrent() {
    const r = route();
    if (!user()) return;
    if (r.name === "home") loadRows();
    else if (r.name === "hold") loadHold();
    else if (r.name === "detail" && r.id) loadDetailSilent(r.id);
  }

  async function loadDetailSilent(id) {
    try {
      setDetail(await fetchSubmission(id));
    } catch {
      // 轮询静默失败，保留上一次数据
    }
  }

  onMount(() => {
    const onHash = () => setRoute(readHash());
    window.addEventListener("hashchange", onHash);
    if (user()) refreshCurrent();
    const timer = setInterval(refreshCurrent, 1500);
    onCleanup(() => {
      window.removeEventListener("hashchange", onHash);
      clearInterval(timer);
    });
  });

  createEffect(() => {
    const r = route();
    if (!user()) return;
    if (r.name === "detail" && r.id) loadDetail(r.id);
    else if (r.name === "home") loadRows();
    else if (r.name === "hold") loadHold();
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
    setHold(null);
    goHome();
  }

  async function handleSubmit(e) {
    e.preventDefault();
    setError("");
    try {
      await createSubmission(toolCode(), offsetUm(), priority());
      setToolCode("");
      setOffsetUm("");
      setPriority("normal");
      await loadRows();
    } catch (err) {
      setError(err.message);
    }
  }

  async function handleSaveConfig(e) {
    e.preventDefault();
    setError("");
    setSavingCfg(true);
    try {
      const data = await updateHoldConfig(threshold(), seconds());
      setHold(data);
      setThreshold(String(data.fail_threshold));
      setSeconds(String(data.hold_seconds));
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
          <p class="hint">刀补绝对值不超过十二微米判合格，否则超差。连续超差达阈值进入缓领，缓领中普通停领、急补仍可领。</p>
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
              href="#/hold"
              class={route().name === "hold" ? "active" : ""}
              onClick={(e) => {
                e.preventDefault();
                location.hash = "#/hold";
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
              <button type="button" class="ghost" onClick={loadRows} disabled={loading()}>
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
                    <tr>
                      <td>{row.tool_code}</td>
                      <td>{row.offset_um}</td>
                      <td>
                        <span class={row.priority === "urgent" ? "tag urgent" : "tag normal"}>
                          {priorityLabel[row.priority] || row.priority}
                        </span>
                      </td>
                      <td>{statusLabel[row.status] || row.status}</td>
                      <td class={row.verdict === "合格" ? "pass" : row.verdict === "超差" ? "fail" : ""}>
                        {row.verdict || "—"}
                      </td>
                      <td>{fmtTime(row.created_at)}</td>
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
                  <p>
                    类型：
                    <span class={d().priority === "urgent" ? "tag urgent" : "tag normal"}>
                      {priorityLabel[d().priority] || d().priority}
                    </span>
                  </p>
                  <p>状态：{statusLabel[d().status] || d().status}</p>
                  <p class={d().verdict === "合格" ? "pass" : d().verdict === "超差" ? "fail" : ""}>
                    结论：{d().verdict || "—"}
                  </p>
                  <p>提交时间：{fmtTime(d().created_at)}</p>
                  <p>复核时间：{fmtTime(d().reviewed_at)}</p>
                </div>
              )}
            </Show>
          </section>
        </Show>

        <Show when={route().name === "hold"}>
          <section class="card">
            <div class="toolbar">
              <h2>缓领台</h2>
              <button type="button" class="ghost" onClick={loadHold}>
                刷新
              </button>
            </div>
            <Show when={hold()} fallback={<p class="hint">加载中…</p>}>
              {(h) => (
                <div>
                  <div class="hold-status">
                    <span class={h().active ? "lamp on" : "lamp off"} />
                    <Show
                      when={h().active}
                      fallback={<strong class="lamp-text off">未在缓 · 普通刀补正常认领</strong>}
                    >
                      <strong class="lamp-text on">
                        在缓中 · 普通停领、急补仍可领（剩余 {h().remain_seconds} 秒）
                      </strong>
                    </Show>
                  </div>
                  <div class="detail-grid">
                    <p>当前连续超差：<strong>{h().streak}</strong> 条</p>
                    <Show when={h().active}>
                      <p>缓领开始：{fmtTime(h().started_at)}</p>
                      <p>计划解除：{fmtTime(h().planned_end_at)}</p>
                    </Show>
                  </div>

                  <h3>阈值与秒数</h3>
                  <Show
                    when={user().can_write}
                    fallback={
                      <div class="readonly-cfg">
                        <p>连续超差阈值：<strong>{h().fail_threshold}</strong> 条</p>
                        <p>缓领秒数：<strong>{h().hold_seconds}</strong> 秒</p>
                        <p class="hint">复核员仅可查看，不能修改阈值或秒数。</p>
                      </div>
                    }
                  >
                    <form onSubmit={handleSaveConfig} class="form inline">
                      <label>
                        连续超差阈值（条）
                        <input
                          type="number"
                          min="1"
                          step="1"
                          data-hold-field="threshold"
                          value={threshold()}
                          onInput={(e) => setThreshold(e.currentTarget.value)}
                          required
                        />
                      </label>
                      <label>
                        缓领秒数（秒）
                        <input
                          type="number"
                          min="1"
                          step="1"
                          data-hold-field="seconds"
                          value={seconds()}
                          onInput={(e) => setSeconds(e.currentTarget.value)}
                          required
                        />
                      </label>
                      <button type="submit" disabled={savingCfg()}>
                        {savingCfg() ? "保存中…" : "保存配置"}
                      </button>
                    </form>
                    <p class="hint">改阈值或秒数即时生效，但不追溯已写的起止流水（流水保留当时快照）。</p>
                  </Show>

                  <h3>起止流水</h3>
                  <table>
                    <thead>
                      <tr>
                        <th>类型</th>
                        <th>时间</th>
                        <th>阈值</th>
                        <th>秒数</th>
                        <th>连续超差</th>
                        <th>触发刀具</th>
                        <th>计划解除</th>
                      </tr>
                    </thead>
                    <tbody>
                      <For each={h().journals}>
                        {(j) => (
                          <tr>
                            <td>
                              <span class={j.kind === "start" ? "tag hold-start" : "tag hold-end"}>
                                {j.kind_label}
                              </span>
                            </td>
                            <td>{fmtTime(j.created_at)}</td>
                            <td>{j.threshold_snapshot} 条</td>
                            <td>{j.hold_seconds_snapshot} 秒</td>
                            <td>{j.streak_snapshot}</td>
                            <td>{j.trigger_tool_code || "—"}</td>
                            <td>{fmtTime(j.planned_end_at)}</td>
                          </tr>
                        )}
                      </For>
                    </tbody>
                  </table>
                  <Show when={!h().journals.length}>
                    <p class="hint">暂无缓领起止流水。</p>
                  </Show>
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
