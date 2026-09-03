// NotePad Texts server
//
// Zero-dependency Node server: serves the static app and exposes
// POST /api/send, which delivers a note as a real SMS through Twilio's
// REST API when credentials are configured. Without credentials it
// responds in "simulated" mode so the app still works out of the box.
//
// Configure via environment variables (see .env.example):
//   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_FROM_NUMBER
//
// Run:  node server.js   then open http://localhost:8000

const http = require("http");
const fs = require("fs");
const path = require("path");

const PORT = process.env.PORT || 8000;
const ROOT = __dirname;

// Load .env if present (no dotenv dependency needed).
const envPath = path.join(ROOT, ".env");
if (fs.existsSync(envPath)) {
  for (const line of fs.readFileSync(envPath, "utf8").split("\n")) {
    const match = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)\s*$/);
    if (match && !(match[1] in process.env)) {
      process.env[match[1]] = match[2].replace(/^["']|["']$/g, "");
    }
  }
}

const TWILIO_SID = process.env.TWILIO_ACCOUNT_SID;
const TWILIO_TOKEN = process.env.TWILIO_AUTH_TOKEN;
const TWILIO_FROM = process.env.TWILIO_FROM_NUMBER;
const twilioConfigured = Boolean(TWILIO_SID && TWILIO_TOKEN && TWILIO_FROM);

const MIME_TYPES = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".png": "image/png",
  ".ico": "image/x-icon",
  ".json": "application/json",
};

function sendJson(res, status, payload) {
  const body = JSON.stringify(payload);
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(body);
}

async function sendViaTwilio(to, body) {
  const url = `https://api.twilio.com/2010-04-01/Accounts/${TWILIO_SID}/Messages.json`;
  const auth = Buffer.from(`${TWILIO_SID}:${TWILIO_TOKEN}`).toString("base64");
  const response = await fetch(url, {
    method: "POST",
    headers: {
      Authorization: `Basic ${auth}`,
      "Content-Type": "application/x-www-form-urlencoded",
    },
    body: new URLSearchParams({ To: to, From: TWILIO_FROM, Body: body }),
  });
  const data = await response.json();
  if (!response.ok) {
    throw new Error(data.message || `Twilio error ${response.status}`);
  }
  return data.sid;
}

async function handleSend(req, res) {
  let raw = "";
  for await (const chunk of req) {
    raw += chunk;
    if (raw.length > 10_000) {
      sendJson(res, 413, { error: "Request too large" });
      return;
    }
  }

  let payload;
  try {
    payload = JSON.parse(raw);
  } catch {
    sendJson(res, 400, { error: "Invalid JSON" });
    return;
  }

  const to = String(payload.to || "").trim();
  const body = String(payload.body || "").trim();
  if (!/^\+?\d{7,15}$/.test(to.replace(/[\s().-]/g, ""))) {
    sendJson(res, 400, { error: "Invalid phone number" });
    return;
  }
  if (!body || body.length > 500) {
    sendJson(res, 400, { error: "Message must be 1-500 characters" });
    return;
  }

  if (!twilioConfigured) {
    sendJson(res, 200, { delivered: false, simulated: true });
    return;
  }

  try {
    const sid = await sendViaTwilio(to, body);
    sendJson(res, 200, { delivered: true, sid });
  } catch (err) {
    sendJson(res, 502, { error: err.message });
  }
}

function serveStatic(req, res) {
  const urlPath = decodeURIComponent(new URL(req.url, "http://localhost").pathname);
  const relative = urlPath === "/" ? "index.html" : urlPath.slice(1);
  const filePath = path.join(ROOT, relative);

  // Keep requests inside the project directory and away from secrets.
  if (!filePath.startsWith(ROOT + path.sep) || path.basename(filePath) === ".env") {
    res.writeHead(403);
    res.end("Forbidden");
    return;
  }

  fs.readFile(filePath, (err, data) => {
    if (err) {
      res.writeHead(404);
      res.end("Not found");
      return;
    }
    const type = MIME_TYPES[path.extname(filePath)] || "application/octet-stream";
    res.writeHead(200, { "Content-Type": type });
    res.end(data);
  });
}

http
  .createServer((req, res) => {
    if (req.method === "POST" && req.url === "/api/send") {
      handleSend(req, res).catch(() => sendJson(res, 500, { error: "Server error" }));
    } else if (req.method === "GET") {
      serveStatic(req, res);
    } else {
      res.writeHead(405);
      res.end("Method not allowed");
    }
  })
  .listen(PORT, () => {
    console.log(`NotePad Texts running at http://localhost:${PORT}`);
    console.log(
      twilioConfigured
        ? "Twilio configured — notes will be sent as real SMS."
        : "Twilio not configured — running in simulated mode (see .env.example)."
    );
  });
