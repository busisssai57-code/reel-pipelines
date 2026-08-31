"""The operator page: one self-contained HTML document.

No CDN and no build step — the studio is a local tool that has to come up on a
machine mid-broadcast, possibly offline, so everything it needs is inlined.

Every value that originates outside the operator's own machine (buyer handles
and order reasons come from live chat) is written with ``textContent``. Nothing
here builds markup from data by string concatenation.
"""

from __future__ import annotations

PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>BTA — Automation Studio</title>
<link rel="icon" href="data:,">
<style>
  :root {
    --bg: #0e1116; --panel: #161b22; --line: #262d36; --text: #e6edf3;
    --muted: #8b949e; --accent: #4493f8; --good: #3fb950; --warn: #d29922;
    --bad: #f85149; --hold: #a371f7;
  }
  * { box-sizing: border-box; }
  body {
    margin: 0; background: var(--bg); color: var(--text);
    font: 14px/1.5 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  }
  header {
    display: flex; align-items: baseline; gap: 16px; flex-wrap: wrap;
    padding: 14px 20px; border-bottom: 1px solid var(--line); background: var(--panel);
    position: sticky; top: 0; z-index: 5;
  }
  h1 { font-size: 15px; margin: 0; letter-spacing: .02em; }
  h1 span { color: var(--muted); font-weight: 400; }
  .meta { color: var(--muted); font-size: 12px; display: flex; gap: 14px; margin-left: auto; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 5px; }
  .dot.on { background: var(--good); } .dot.off { background: var(--bad); }
  main { padding: 20px; max-width: 1180px; margin: 0 auto; display: grid; gap: 18px; }
  .tiles { display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; }
  .tile { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px; }
  .tile .label { color: var(--muted); font-size: 11px; text-transform: uppercase; letter-spacing: .06em; }
  .tile .value { font-size: 24px; font-variant-numeric: tabular-nums; margin-top: 4px; }
  section { background: var(--panel); border: 1px solid var(--line); border-radius: 8px; overflow: hidden; }
  section > h2 {
    font-size: 12px; text-transform: uppercase; letter-spacing: .07em; color: var(--muted);
    margin: 0; padding: 11px 14px; border-bottom: 1px solid var(--line);
  }
  .scroll { overflow-x: auto; }
  table { width: 100%; border-collapse: collapse; font-size: 13px; }
  th { text-align: left; font-weight: 500; color: var(--muted); font-size: 11px;
       text-transform: uppercase; letter-spacing: .05em; padding: 8px 14px;
       border-bottom: 1px solid var(--line); white-space: nowrap; }
  td { padding: 9px 14px; border-bottom: 1px solid var(--line); vertical-align: middle; }
  tr:last-child td { border-bottom: 0; }
  .num { text-align: right; font-variant-numeric: tabular-nums; }
  .mono { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 12px; color: var(--muted); }
  .pill { display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 11px;
          border: 1px solid currentColor; white-space: nowrap; }
  .s-captured { color: var(--muted); } .s-reserved { color: var(--hold); }
  .s-fulfilled { color: var(--good); } .s-cancelled { color: var(--muted); }
  .s-failed { color: var(--bad); }
  button {
    font: inherit; font-size: 12px; padding: 3px 10px; margin-right: 5px; cursor: pointer;
    background: transparent; color: var(--accent); border: 1px solid var(--line);
    border-radius: 5px;
  }
  button:hover:not(:disabled) { border-color: var(--accent); }
  button:disabled { opacity: .4; cursor: not-allowed; }
  button.danger { color: var(--bad); }
  input {
    font: inherit; font-size: 12px; background: var(--bg); color: var(--text);
    border: 1px solid var(--line); border-radius: 5px; padding: 3px 7px; width: 68px;
  }
  .alert { padding: 9px 14px; border-radius: 6px; border: 1px solid; font-size: 13px; }
  .alert.warning { color: var(--warn); border-color: currentColor; }
  .alert.info { color: var(--muted); border-color: var(--line); }
  .alerts { display: grid; gap: 8px; }
  .empty { padding: 22px 14px; color: var(--muted); text-align: center; font-size: 13px; }
  .feed { max-height: 320px; overflow-y: auto; }
  #toast {
    position: fixed; right: 18px; bottom: 18px; background: var(--panel);
    border: 1px solid var(--line); border-left: 3px solid var(--bad);
    padding: 10px 14px; border-radius: 6px; max-width: 380px; font-size: 13px;
  }
  [hidden] { display: none !important; }
</style>
</head>
<body>
<header>
  <h1>BTA <span>&middot; Automation Studio</span></h1>
  <div class="meta">
    <span id="ro" class="pill" hidden>read-only</span>
    <span><span id="dot" class="dot off"></span><span id="conn">connecting</span></span>
    <span id="session"></span>
    <span id="uptime"></span>
  </div>
</header>

<main>
  <div class="alerts" id="alerts"></div>

  <div class="tiles">
    <div class="tile"><div class="label">Revenue</div><div class="value" id="t-rev">&mdash;</div></div>
    <div class="tile"><div class="label">Units fulfilled</div><div class="value" id="t-units">&mdash;</div></div>
    <div class="tile"><div class="label">Open orders</div><div class="value" id="t-open">&mdash;</div></div>
    <div class="tile"><div class="label">Orders</div><div class="value" id="t-orders">&mdash;</div></div>
  </div>

  <section>
    <h2>Inventory</h2>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Product</th><th>SKU</th><th class="num">On hand</th>
          <th class="num">Reserved</th><th class="num">Available</th><th>Restock</th>
        </tr></thead>
        <tbody id="inventory"></tbody>
      </table>
    </div>
    <div class="empty" id="inventory-empty" hidden>No products configured.</div>
  </section>

  <section>
    <h2>Orders</h2>
    <div class="scroll">
      <table>
        <thead><tr>
          <th>Buyer</th><th>Items</th><th>Status</th>
          <th class="num">Total</th><th>Placed</th><th>Actions</th>
        </tr></thead>
        <tbody id="orders"></tbody>
      </table>
    </div>
    <div class="empty" id="orders-empty" hidden>No orders in this session yet.</div>
  </section>

  <section>
    <h2>Activity</h2>
    <div class="feed scroll">
      <table><tbody id="activity"></tbody></table>
    </div>
    <div class="empty" id="activity-empty" hidden>Nothing has happened yet.</div>
  </section>
</main>

<div id="toast" hidden></div>

<script>
(function () {
  "use strict";
  var POLL_MS = 2000;
  var readOnly = false;
  var toastTimer = null;

  function el(tag, text, cls) {
    var n = document.createElement(tag);
    if (text !== undefined && text !== null) n.textContent = String(text);
    if (cls) n.className = cls;
    return n;
  }
  function money(cents) {
    return "$" + (Number(cents || 0) / 100).toFixed(2);
  }
  function clock(iso) {
    if (!iso) return "";
    var d = new Date(iso);
    return isNaN(d) ? String(iso) : d.toLocaleTimeString();
  }
  function duration(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60);
    return h ? h + "h " + m + "m" : m ? m + "m " + (s % 60) + "s" : s + "s";
  }
  function toast(text) {
    var box = document.getElementById("toast");
    box.textContent = text;
    box.hidden = false;
    clearTimeout(toastTimer);
    toastTimer = setTimeout(function () { box.hidden = true; }, 6000);
  }
  function fill(id, rows, build) {
    var body = document.getElementById(id);
    body.replaceChildren();
    rows.forEach(function (row) { body.appendChild(build(row)); });
    document.getElementById(id + "-empty").hidden = rows.length > 0;
  }

  function post(path, payload) {
    return fetch(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload || {})
    }).then(function (res) {
      return res.json().catch(function () { return {}; }).then(function (body) {
        if (!res.ok) throw new Error(body.error || ("request failed: " + res.status));
        return body;
      });
    }).then(refresh).catch(function (err) { toast(err.message); });
  }

  function inventoryRow(row) {
    var tr = el("tr");
    tr.appendChild(el("td", row.name));
    tr.appendChild(el("td", row.sku, "mono"));
    tr.appendChild(el("td", row.on_hand, "num"));
    tr.appendChild(el("td", row.reserved, "num"));
    tr.appendChild(el("td", row.available, "num"));

    var cell = el("td");
    var input = document.createElement("input");
    input.type = "number"; input.min = "1"; input.value = "10";
    input.setAttribute("aria-label", "Restock quantity for " + row.sku);
    var button = el("button", "Add");
    button.disabled = readOnly;
    button.addEventListener("click", function () {
      var qty = parseInt(input.value, 10);
      if (!(qty > 0)) { toast("Restock quantity must be a positive number."); return; }
      post("/api/inventory/restock", { sku: row.sku, quantity: qty });
    });
    cell.appendChild(input);
    cell.appendChild(document.createTextNode(" "));
    cell.appendChild(button);
    tr.appendChild(cell);
    return tr;
  }

  var ACTIONS = { fulfilled: ["fulfill", "Fulfil"], cancelled: ["cancel", "Cancel"], failed: ["fail", "Fail"] };

  function orderRow(row) {
    var tr = el("tr");
    tr.appendChild(el("td", row.buyer_handle || "\\u2014"));
    tr.appendChild(el("td", row.summary));

    var status = el("td");
    status.appendChild(el("span", row.status, "pill s-" + row.status));
    tr.appendChild(status);

    tr.appendChild(el("td", money(row.total_cents), "num"));
    tr.appendChild(el("td", clock(row.created_at), "mono"));

    var cell = el("td");
    (row.actions || []).forEach(function (target) {
      var spec = ACTIONS[target];
      if (!spec) return;
      var button = el("button", spec[1], target === "failed" ? "danger" : "");
      button.disabled = readOnly;
      button.addEventListener("click", function () {
        post("/api/orders/" + encodeURIComponent(row.id) + "/" + spec[0], {});
      });
      cell.appendChild(button);
    });
    if (!cell.childNodes.length) cell.appendChild(el("span", "\\u2014", "mono"));
    tr.appendChild(cell);
    return tr;
  }

  function activityRow(row) {
    var tr = el("tr");
    tr.appendChild(el("td", clock(row.at), "mono"));
    tr.appendChild(el("td", row.buyer_handle || "\\u2014"));
    tr.appendChild(el("td", row.summary));
    var status = el("td");
    status.appendChild(el("span", row.to_status, "pill s-" + row.to_status));
    tr.appendChild(status);
    tr.appendChild(el("td", row.reason || "", "mono"));
    return tr;
  }

  function connected(isUp) {
    document.getElementById("dot").className = "dot " + (isUp ? "on" : "off");
    document.getElementById("conn").textContent = isUp ? "live" : "disconnected";
  }

  function render(data) {
    readOnly = !!data.read_only;
    document.getElementById("ro").hidden = !readOnly;
    document.getElementById("session").textContent = "session: " + data.session_id;
    document.getElementById("uptime").textContent = "up " + duration(data.uptime_seconds);

    var summary = data.summary || {};
    document.getElementById("t-rev").textContent = money(summary.revenue_cents);
    document.getElementById("t-units").textContent = summary.units_fulfilled || 0;
    document.getElementById("t-open").textContent = summary.open_orders || 0;
    document.getElementById("t-orders").textContent = summary.orders || 0;

    var alerts = document.getElementById("alerts");
    alerts.replaceChildren();
    (data.alerts || []).forEach(function (alert) {
      alerts.appendChild(el("div", alert.text, "alert " + alert.level));
    });

    fill("inventory", data.inventory || [], inventoryRow);
    fill("orders", data.orders || [], orderRow);
    fill("activity", data.activity || [], activityRow);
  }

  function refresh() {
    return fetch("/api/snapshot")
      .then(function (res) {
        if (!res.ok) throw new Error("snapshot failed: " + res.status);
        return res.json();
      })
      .then(function (data) { connected(true); render(data); })
      .catch(function () { connected(false); });
  }

  refresh();
  setInterval(refresh, POLL_MS);
})();
</script>
</body>
</html>
"""
