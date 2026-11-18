// Captures a screenshot at a given viewport through the Chrome DevTools Protocol.
const port = process.argv[2] ?? "9222";
const url = process.argv[3] ?? "http://127.0.0.1:4173/select-spire/";
const width = Number(process.argv[4] ?? 390);
const height = Number(process.argv[5] ?? 900);
const out = process.argv[6] ?? "shot.png";
const mobile = process.argv[7] !== "desktop";

const { writeFile } = await import("node:fs/promises");

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
await send("Emulation.setDeviceMetricsOverride", {
  width,
  height,
  deviceScaleFactor: 1,
  mobile,
});
await send("Page.navigate", { url });
await new Promise((resolve) => setTimeout(resolve, 2500));

const shot = await send("Page.captureScreenshot", { format: "png", captureBeyondViewport: true });
await writeFile(out, Buffer.from(shot.result.data, "base64"));
console.log(`wrote ${out}`);
ws.close();
