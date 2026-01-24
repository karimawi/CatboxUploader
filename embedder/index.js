const express = require('express');
const LZString = require('lz-string');
require("dotenv").config();
const PORT = process.env.PORT || 3006;
const app = express();

app.get('/*', (req, res) => {
  if (req.path === "/"){
    res.send(`<!DOCTYPE html>
    <html lang="en">
      <head>
        <title>video.karimawi.me</title>
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>
          body { background-color: #121212; color: #e0e0e0; font-family: sans-serif; text-align: center; display: flex; flex-direction: column; align-items: center; justify-content: center; height: 100vh; margin: 0; }
          a { color: #bb86fc; }
        </style>
      </head>
      <body>
        <h1>video.karimawi.me</h1>
        <p>Catbox Embedder</p>
      </body>
    </html>`);
    return;
  }

  try {
    const encoded = req.path.substring(1); // Remove leading slash
    // Try FromEncodedURIComponent first as it's URL safe
    let jsonStr = LZString.decompressFromEncodedURIComponent(encoded);
    
    if (!jsonStr) {
        // Attempt base64 just in case
        jsonStr = LZString.decompressFromBase64(encoded);
    }
    
    if (!jsonStr) {
        // Try strict URI component since some clients might just encodeURI the compressed string differently
        // But usually LZString.decompressFromEncodedURIComponent matches compressToEncodedURIComponent
    }

    let decoded;
    // Special handling if decompression fails or returns garbage
    if (!jsonStr) {
       // If decoding fails, check if the user just passed a filename directly (legacy support or accident)
       // The user strictly asked for LZString.
       throw new Error("Decompression failed");
    }

    try {
        decoded = JSON.parse(jsonStr);
    } catch (e) {
        throw new Error("Invalid JSON");
    }

    if (!Array.isArray(decoded) || decoded.length === 0) {
       throw new Error("Invalid payload structure");
    }

    let filename = decoded[0];
    const title = decoded[1] || "";

    // Check for Litterbox prefix
    let isLitterbox = false;
    if (filename.startsWith('*')) {
        isLitterbox = true;
        filename = filename.substring(1);
    }
    
    // Simple extension check
    const parts = filename.split('.');
    if (parts.length < 2) throw new Error("Filename has no extension");
    const ext = parts.pop().toLowerCase();
    
    const domain = isLitterbox ? 'litter.catbox.moe' : 'files.catbox.moe';
    const fileUrl = `https://${domain}/${filename}`;
    const pageUrl = `https://${req.headers.host}${req.path}`; 

    const isVideo = ['mp4', 'webm', 'mov', 'mkv'].includes(ext);

    let mimeType = 'video/mp4';
    if (ext === 'webm') mimeType = 'video/webm';
    if (ext === 'mov') mimeType = 'video/quicktime';

    // Construct HTML
    
    let metaTags = `
        <meta name="theme-color" content="#687C9B" />
        <meta property="og:site_name" content="karimawi.me" />
        <meta property="og:title" content="${title.replace(/"/g, '&quot;') || 'Video'}" />
        <meta property="og:type" content="video.other" />
        <meta property="og:url" content="${pageUrl}" />
    `;

    if (isVideo) {
        metaTags += `
        <meta property="og:video" content="${fileUrl}" />
        <meta property="og:video:url" content="${fileUrl}" />
        <meta property="og:video:secure_url" content="${fileUrl}" />
        <meta property="og:video:type" content="${mimeType}" />
        <meta property="og:video:width" content="1280">
        <meta property="og:video:height" content="720">
        <meta name="twitter:card" content="player">
        <meta name="twitter:player" content="${fileUrl}">
        <meta name="twitter:player:width" content="1280">
        <meta name="twitter:player:height" content="720">
        <meta name="twitter:player:stream" content="${fileUrl}">
        `;
    }

    const accessLink = `<a href="${fileUrl}">${fileUrl}</a>`;

    const html = `<!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1">
        ${metaTags}
        <title>${title}</title>
        <style>
          body {
            background-color: #121212;
            color: white;
            text-align: center;
            font-family: sans-serif;
            display: flex;
            flex-direction: column;
            align-items: center;
            padding: 20px;
          }
          .content-container {
            width: 90%;
            max-width: 1000px;
          }
          video {
            width: 100%;
            max-width: 1000px;
            margin-top: 20px;
            border-radius: 8px;
            background: #000;
          }
          a { color: #00FFFF; text-decoration: none; }
          h2 { margin-top: 0; }
        </style>
      </head>
      <body>
        <div class="content-container">
            <h2>${title}</h2>
            <p>Direct Link: ${accessLink}</p>
            ${isVideo ? `<video controls preload="auto" src="${fileUrl}"></video>` : ''}
        </div>
      </body>
    </html>`;

    res.send(html);

  } catch (err) {
    console.error(err);
    // Simple error page
    res.status(400).send(`<!DOCTYPE html><html><body><h2>Error</h2><p>${err.message}</p></body></html>`);
  }
});

app.listen(PORT, () => {
  console.log(`Server is listening on port ${PORT}`);
});
