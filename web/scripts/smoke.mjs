// Drives the built page through a full battle and reports what happened.
const port = process.argv[2] ?? "9222";
const url = process.argv[3] ?? "http://127.0.0.1:4173/select-spire/";

const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
if (!page) throw new Error("no page target");

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  }
});
await new Promise((resolve) => ws.addEventListener("open", resolve));

function send(method, params = {}) {
  const messageId = ++id;
  return new Promise((resolve) => {
    pending.set(messageId, resolve);
    ws.send(JSON.stringify({ id: messageId, method, params }));
  });
}

async function evaluate(expression) {
  const result = await send("Runtime.evaluate", { expression, returnByValue: true, awaitPromise: true });
  if (result.result?.exceptionDetails) {
    throw new Error(JSON.stringify(result.result.exceptionDetails));
  }
  return result.result?.result?.value;
}

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1000, height: 900, deviceScaleFactor: 1, mobile: false });
await send("Page.navigate", { url });

// Wait until the app has actually rendered before clicking anything.
for (let attempt = 0; attempt < 40; attempt += 1) {
  const ready = await evaluate(`Boolean(document.querySelector("button.card"))`);
  if (ready) break;
  await new Promise((resolve) => setTimeout(resolve, 250));
}

const clickByText = (text) => `(() => {
  const nodes = [...document.querySelectorAll("button")];
  const target = nodes.find((node) => node.textContent.includes(${JSON.stringify(text)}));
  if (!target) return "missing:" + ${JSON.stringify(text)};
  target.click();
  return "clicked";
})()`;

const clickCard = (kind) => `(() => {
  const cards = [...document.querySelectorAll("button.card")];
  const target = cards.find((node) => node.textContent.includes(${JSON.stringify(kind)}));
  if (!target) return "missing-card:" + ${JSON.stringify(kind)};
  target.click();
  return "clicked";
})()`;

const readState = `(() => {
  const text = document.body.innerText;
  const hp = text.match(/あなたのHP (\\d+) \\/ 50/);
  const energy = text.match(/エネルギー (\\d+)/);
  const floor = text.match(/(\\d+) \\/ 9階/);
  const message = document.querySelector(".message")?.textContent ?? "";
  const enemies = [...document.querySelectorAll(".enemy")].map((node) => node.innerText.split("\\n")[0]);
  return JSON.stringify({ hp: hp?.[1], energy: energy?.[1], floor: floor?.[1], message, enemies });
})()`;

const log = [];
log.push(["initial", await evaluate(readState)]);

// Scout the first scout card, then attack with whatever is affordable.
log.push(["scout", await evaluate(clickCard("SCOUT"))]);
log.push(["after scout", await evaluate(readState)]);

log.push(["attack", await evaluate(clickByText("攻撃する"))]);
log.push(["after attack", await evaluate(readState)]);

log.push(["end", await evaluate(clickByText("ターン終了"))]);
log.push(["after end", await evaluate(readState)]);

// Play the whole run with a simple policy to prove the loop reaches an ending.
for (let step = 0; step < 600; step += 1) {
  const status = await evaluate(`(() => {
    if (document.querySelector(".finish")) return "finish";
    if (document.querySelector(".rewards")) return "reward";
    return "battle";
  })()`);
  if (status === "finish") break;
  if (status === "reward") {
    await evaluate(`(() => { const b = document.querySelector("button.reward"); if (b) b.click(); return "ok"; })()`);
    continue;
  }
  // Prefer a real attack: select every affordable clause, then attack.
  const attacked = await evaluate(`(() => {
    const cards = [...document.querySelectorAll("button.card")];
    const attack = [...document.querySelectorAll("button.action")].find((b) => b.textContent.includes("攻撃する"));
    if (!attack) return "no-attack";
    const picked = new Set();
    let energy = Number((document.body.innerText.match(/エネルギー (\\d+)/) ?? [])[1] ?? 0);
    for (const card of cards) {
      const meta = card.textContent;
      if (meta.includes("SCOUT")) continue;
      const kind = meta.match(/(WHERE|JOIN|GROUP|ORDER|LIMIT)/)?.[1];
      if (!kind || picked.has(kind)) continue;
      const cost = Number((meta.match(/コスト (\\d+)/) ?? [])[1] ?? 0);
      if (cost > energy) continue;
      card.click();
      picked.add(kind);
      energy -= cost;
    }
    const whereCard = [...document.querySelectorAll("button.card")].find((c) => c.textContent.includes("WHERE"));
    if (whereCard) {
      const chip = document.querySelector("button.column-chip");
      if (chip) chip.click();
    }
    const attackNow = [...document.querySelectorAll("button.action")].find((b) => b.textContent.includes("攻撃する"));
    if (!attackNow) return "no-attack";
    attackNow.click();
    return "clicked";
  })()`);
  if (attacked !== "clicked") {
    await evaluate(clickByText("ターン終了"));
    continue;
  }
  const stillBattle = await evaluate(`Boolean(document.querySelector("button.card"))`);
  if (stillBattle) await evaluate(clickByText("ターン終了"));
}

log.push(["final", await evaluate(`(() => {
  const text = document.body.innerText;
  const finish = document.querySelector(".finish")?.innerText ?? "";
  return JSON.stringify({ finish, tail: text.slice(-160) });
})()`)]);

for (const [label, value] of log) console.log(label, "=>", value);
ws.close();
