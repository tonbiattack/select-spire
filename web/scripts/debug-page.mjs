// Loads the page and reports console errors plus the rendered body text.
const port = process.argv[2] ?? "9222";
const url = process.argv[3] ?? "http://127.0.0.1:4173/select-spire/";

const targets = await (await fetch(`http://127.0.0.1:${port}/json/list`)).json();
const page = targets.find((t) => t.type === "page");
if (!page) throw new Error("no page target");

const ws = new WebSocket(page.webSocketDebuggerUrl);
let id = 0;
const pending = new Map();
const events = [];
ws.addEventListener("message", (event) => {
  const msg = JSON.parse(event.data);
  if (msg.id && pending.has(msg.id)) {
    pending.get(msg.id)(msg);
    pending.delete(msg.id);
  } else if (msg.method) {
    events.push(msg);
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
await send("Log.enable");
const nav = await send("Page.navigate", { url });
console.log("navigate:", JSON.stringify(nav.result ?? nav.error));
await new Promise((resolve) => setTimeout(resolve, 3000));

const info = await send("Runtime.evaluate", {
  expression: `JSON.stringify({ url: location.href, title: document.title, body: document.body.innerText.slice(0, 300), appHtml: document.querySelector("#app")?.innerHTML.slice(0, 200) })`,
  returnByValue: true,
});
console.log("page:", info.result?.result?.value);

for (const event of events) {
  if (event.method === "Runtime.exceptionThrown") {
    console.log("EXCEPTION:", JSON.stringify(event.params.exceptionDetails?.exception?.description ?? event.params));
  }
  if (event.method === "Runtime.consoleAPICalled") {
    console.log("CONSOLE:", event.params.args?.map((a) => a.value ?? a.description).join(" "));
  }
  if (event.method === "Log.entryAdded") {
    console.log("LOG:", event.params.entry.level, event.params.entry.text);
  }
}
ws.close();
