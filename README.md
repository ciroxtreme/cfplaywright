# CFPlaywright 🛡️⚡
**Automated Cloudflare Turnstile Bypass for Playwright & Chrome via Native Extension & CFSolve Engine.**

### Fitur:
1. **CFSolve Engine Turbo (Sub-Second Rust):** Memecahkan tantangan Turnstile / Cloudflare Challenge dan mengambil `cf_clearance` tanpa render DOM.
2. **Chrome Extension Native Injector:** Memuat ekstensi internal Chrome untuk monitoring dan injeksi header/cookie.
3. **Patchright + Google Chrome Resmi:** Memastikan TLS handshake JA3/JA4 sah 100% dan tidak ada kebocoran CDP.

### 4. Google reCAPTCHA v3 Auto-Solver (PyPasser Integration)
- Mendeteksi form/skrip reCAPTCHA v3 di halaman web secara otomatis.
- Menghitung token valid tanpa browser visual dan menyuntikkannya langsung ke input `[name="g-recaptcha-response"]`.
