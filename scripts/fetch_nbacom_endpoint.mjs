#!/usr/bin/env node
/**
 * fetch_nbacom_endpoint.mjs — HTTP/2 transport for stats.nba.com
 *
 * Akamai Bot Manager inspects TLS Client Hello and HTTP/2 frames.
 * Node.js native fetch provides HTTP/2 + modern TLS handshake out-of-the-box
 * without requiring non-standard Python TLS packages (DECISIONS.md D7).
 */

const url = process.argv[2];
if (!url) {
  process.stderr.write("Usage: node fetch_nbacom_endpoint.mjs <url>\n");
  process.exit(1);
}

const headers = {
  "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
  "Accept": "application/json, text/plain, */*",
  "Accept-Language": "en-US,en;q=0.9",
  "Referer": "https://www.nba.com/",
  "Origin": "https://www.nba.com",
  "x-nba-stats-origin": "stats",
  "x-nba-stats-token": "true",
  "Connection": "keep-alive",
};

async function main() {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 25000);
  try {
    const res = await fetch(url, { headers, signal: controller.signal });
    const text = await res.text();
    let json = {};
    try {
      json = JSON.parse(text);
    } catch {
      // Non-JSON response
    }
    process.stdout.write(JSON.stringify({ status: res.status, body: json }));
  } catch (err) {
    process.stdout.write(JSON.stringify({ status: 500, error: err.message }));
  } finally {
    clearTimeout(timeout);
  }
}

main();
