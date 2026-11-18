// Measures horizontal overflow in the built page via the Chrome DevTools Protocol.
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

await send("Page.enable");
await send("Runtime.enable");
await send("Emulation.setDeviceMetricsOverride", {
  width: 390,
  height: 844,
  deviceScaleFactor: 1,
  mobile: true,
});
await send("Page.navigate", { url });
await new Promise((resolve) => setTimeout(resolve, 2500));

const expression = `(() => {
  const doc = document.documentElement;
  const offenders = [];
  for (const node of document.querySelectorAll("*")) {
    const rect = node.getBoundingClientRect();
    if (rect.right > doc.clientWidth + 1) {
      offenders.push({
        tag: node.tagName.toLowerCase(),
        cls: node.className && node.className.toString().slice(0, 40),
        right: Math.round(rect.right),
        width: Math.round(rect.width),
      });
    }
  }
  return JSON.stringify({
    clientWidth: doc.clientWidth,
    scrollWidth: doc.scrollWidth,
    offenders: offenders.slice(0, 12),
  }, null, 1);
})()`;

const result = await send("Runtime.evaluate", { expression, returnByValue: true });
console.log(result.result?.result?.value ?? JSON.stringify(result));
ws.close();
