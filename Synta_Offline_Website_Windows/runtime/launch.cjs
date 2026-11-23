const { randomBytes } = require("node:crypto");
const fs = require("node:fs");
const path = require("node:path");
const os = require("node:os");
const net = require("node:net");
const { spawn } = require("node:child_process");
process.chdir(__dirname);
const data =
  process.env.SYNTA_DATA_DIR ||
  path.join(process.env.APPDATA || os.homedir(), "Synta");
fs.mkdirSync(data, { recursive: true });
const locator = path.join(data, "running.json");
const secret = randomBytes(32).toString("hex");
if (process.argv.includes("--small"))
  process.env.SYNTA_MODEL = "qwen2.5-coder:3b";
const server = net.createServer();
server.listen(0, "127.0.0.1", () => {
  const port = server.address().port;
  server.close(async () => {
    process.env.PORT = String(port);
    process.env.HOSTNAME = "127.0.0.1";
    process.env.NODE_ENV = "production";
    process.env.NEXT_TELEMETRY_DISABLED = "1";
    process.env.SYNTA_BRIDGE = secret;
    const url = "http://127.0.0.1:" + port;
    require("./server.js");
    let ready = false;
    for (let i = 0; i < 120; i++) {
      try {
        if ((await fetch(url + "/api/auth")).ok) {
          ready = true;
          break;
        }
      } catch {}
      await new Promise((r) => setTimeout(r, 250));
    }
    if (!ready) {
      console.error("Synta could not open its local account database. Check the server error above.");
      process.exit(1);
    }
    const tmp = locator + "." + process.pid;
    fs.writeFileSync(tmp, JSON.stringify({ port, secret }));
    fs.renameSync(tmp, locator);
    console.log(
      "Synta website: " +
        url +
        "\nKeep this window open. Press Ctrl+C to stop.",
    );
    if (!process.argv.includes("--no-browser"))
      spawn("rundll32.exe", ["url.dll,FileProtocolHandler", url], {
        windowsHide: true,
        stdio: "ignore",
      }).unref();
  });
});
process.on("exit", () => {
  try {
    if (JSON.parse(fs.readFileSync(locator)).secret === secret)
      fs.unlinkSync(locator);
  } catch {}
});
