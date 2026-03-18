#!/usr/bin/env node
// Retry a queued Bluesky post from pending_posts.json
// Usage: node retry_bluesky.js '{"text":"...", "image_path":"..."}'
const fs = require('fs');

async function main() {
  const argsJson = process.argv[2];
  if (!argsJson) { console.log("ERROR: no args"); process.exit(1); }

  const args = JSON.parse(argsJson);
  const handle = process.env.BLUESKY_HANDLE;
  const appPassword = process.env.BLUESKY_APP_PASSWORD;
  if (!handle || !appPassword) { console.log("ERROR: no BLUESKY creds in env"); process.exit(1); }

  // Auth
  const sessResp = await fetch("https://bsky.social/xrpc/com.atproto.server.createSession", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ identifier: handle, password: appPassword }),
  });
  if (!sessResp.ok) { console.log("AUTH_FAIL:" + sessResp.status); process.exit(1); }
  const { accessJwt, did } = await sessResp.json();

  // Build record
  const record = {
    $type: "app.bsky.feed.post",
    text: args.text,
    createdAt: new Date().toISOString(),
  };

  // Image embed if provided
  if (args.image_path && fs.existsSync(args.image_path)) {
    try {
      const imgData = fs.readFileSync(args.image_path);
      const mime = args.image_path.endsWith('.png') ? 'image/png' : 'image/jpeg';
      const uploadResp = await fetch("https://bsky.social/xrpc/com.atproto.repo.uploadBlob", {
        method: "POST",
        headers: { "Content-Type": mime, "Authorization": "Bearer " + accessJwt },
        body: imgData,
      });
      if (uploadResp.ok) {
        const blob = await uploadResp.json();
        record.embed = {
          $type: "app.bsky.embed.images",
          images: [{ alt: args.alt_text || "", image: blob.blob }],
        };
      }
    } catch (e) {
      console.log("IMG_WARN:" + e.message);
    }
  }

  // Post
  const postResp = await fetch("https://bsky.social/xrpc/com.atproto.repo.createRecord", {
    method: "POST",
    headers: { "Content-Type": "application/json", "Authorization": "Bearer " + accessJwt },
    body: JSON.stringify({ repo: did, collection: "app.bsky.feed.post", record }),
  });
  if (!postResp.ok) { console.log("POST_FAIL:" + postResp.status); process.exit(1); }
  const r = await postResp.json();
  console.log("POSTED:" + r.uri);
}

main().catch(e => { console.log("ERROR:" + e.message); process.exit(1); });
