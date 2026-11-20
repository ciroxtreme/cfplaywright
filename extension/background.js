// CFPlaywright Background Service Worker
console.log("[CFPlaywright] Extension active!");

chrome.webRequest.onHeadersReceived.addListener(
  function(details) {
    // Cek jika mendapat status 403 atau 503 dari Cloudflare
    if (details.statusCode === 403 || details.statusCode === 503) {
      console.log("[CFPlaywright] Cloudflare Challenge detected on:", details.url);
    }
  },
  { urls: ["<all_urls>"] },
  ["responseHeaders"]
);
