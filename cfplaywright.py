"""
CFPlaywright Engine (High-Performance Cloudflare Solver + Playwright Native Integration)
Author: Ciro & Antigravity
"""

import os
import sys
import time
import json
import shutil
import subprocess
import urllib.request
import urllib.parse
from patchright.sync_api import sync_playwright

BOT_TOKEN = os.environ.get("BOT_TOKEN", "8457231523:AAH-idCVWIRWRnzkIHKcm-24wvpjkCNAbuc")
CHAT_ID = os.environ.get("CHAT_ID", "1936436999")

def send_telegram_photo(photo_path: str, caption: str = ""):
    if not os.path.exists(photo_path):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto"
    try:
        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = []
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="chat_id"'.encode())
        body.append(''.encode())
        body.append(str(CHAT_ID).encode())
        
        if caption:
            body.append(f"--{boundary}".encode())
            body.append(f'Content-Disposition: form-data; name="caption"'.encode())
            body.append(''.encode())
            body.append(caption[:1024].encode())

        filename = os.path.basename(photo_path)
        body.append(f"--{boundary}".encode())
        body.append(f'Content-Disposition: form-data; name="photo"; filename="{filename}"'.encode())
        body.append('Content-Type: image/png'.encode())
        body.append(''.encode())
        with open(photo_path, "rb") as f:
            body.append(f.read())
        body.append(f"--{boundary}--".encode())
        body.append(''.encode())

        data = b"\r\n".join(body)
        headers = {
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Content-Length": str(len(data))
        }
        req = urllib.request.Request(url, data=data, headers=headers)
        urllib.request.urlopen(req, timeout=20)
        print(f"[✓] Foto screenshot berhasil dikirim ke Telegram Tuan Ciro: {photo_path}")
    except Exception as e:
        print(f"[-] Telegram Send Photo Error: {e}")

def solve_cloudflare_clearance(target_url: str, proxy: str = None) -> str:
    """
    Panggil binary Rust capture_cctv / cfsolve untuk menyelesaikan Cloudflare challenge
    dan mengembalikan token cf_clearance dalam hitungan milidetik.
    """
    out_dir = f"/tmp/cf_out_{int(time.time()*1000)}"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bin_path = os.path.abspath("bin/capture_cctv")
    fp_path = os.path.abspath("profiles/safari-26-ios.json")

    cmd = [
        bin_path,
        fp_path,
        out_dir,
        "1"
    ]

    env = os.environ.copy()
    if proxy:
        env["CF_PROXY"] = proxy

    print(f"⚡ [CFSolve Engine] Menembus Cloudflare Turnstile untuk {target_url}...")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=40)
        elapsed = time.time() - t0
        output = proc.stdout + proc.stderr

        import re
        m = re.search(r"cf_clearance:\s*([a-zA-Z0-9_\-\.]+)", output)
        if m:
            token = m.group(1).strip()
            print(f"✓ [CFSolve] Sukses ditembus dalam {elapsed:.2f}s! cf_clearance: {token[:30]}...")
            return token
        else:
            print(f"[-] [CFSolve] Token tidak ditemukan di output (Exit code {proc.returncode}):")
            print(output[:400])
    except Exception as e:
        print(f"[-] [CFSolve Error]: {e}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    return ""

def open_with_playwright(target_url: str, proxy_url: str = None):
    # 1. Selesaikan challenge Cloudflare via CFSolve Engine
    clearance_token = solve_cloudflare_clearance(target_url, proxy=proxy_url)

    # 2. Setup browser Playwright/Patchright
    ext_path = os.path.abspath("extension")

    proxy_cfg = None
    if proxy_url:
        parsed = urllib.parse.urlparse(proxy_url)
        if parsed.username and parsed.password:
            proxy_cfg = {
                "server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                "username": parsed.username,
                "password": parsed.password
            }
        else:
            proxy_cfg = {"server": proxy_url}

    with sync_playwright() as p:
        launch_args = [
            f"--disable-extensions-except={ext_path}",
            f"--load-extension={ext_path}",
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--window-size=1280,800"
        ]

        print("🚀 Membuka Google Chrome resmi via Playwright...")
        browser = p.chromium.launch(
            channel="chrome",
            headless=False,
            proxy=proxy_cfg,
            args=launch_args
        )

        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )

        parsed_url = urllib.parse.urlparse(target_url)
        domain = parsed_url.hostname

        # 3. Suntikkan cookie clearance jika didapatkan
        if clearance_token:
            print(f"💉 Menyuntikkan token cf_clearance ke domain .{domain}...")
            context.add_cookies([{
                "name": "cf_clearance",
                "value": clearance_token,
                "domain": f".{domain}",
                "path": "/",
                "secure": True,
                "sameSite": "None"
            }])

        page = context.new_page()

        print(f"🌐 Mengakses {target_url}...")
        t_nav = time.time()
        page.goto(target_url, wait_until="domcontentloaded", timeout=60000)
        time.sleep(5)

        title = page.title()
        curr_url = page.url
        print(f"📄 Berhasil dimuat dalam {time.time()-t_nav:.2f}s!")
        print(f"📄 Judul Halaman: {title}")
        print(f"📄 URL Saat Ini: {curr_url}")

        screenshot_path = "cctv_banyuasin_playwright.png"
        page.screenshot(path=screenshot_path)
        print(f"📸 Screenshot tersimpan ke '{screenshot_path}'!")

        # 4. Kirim hasil screenshot ke chat Telegram Tuan Ciro sesuai SOP
        caption = f"📹 Hasil Pembukaan CCTV Banyuasin via CFPlaywright (Chrome Extension + CFSolve Engine)\n📄 Judul: {title}\n🌐 URL: {curr_url}"
        send_telegram_photo(screenshot_path, caption=caption)

        time.sleep(2)
        browser.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://cctv.banyuasinkab.go.id/"
    proxy = os.environ.get("PROXY_URL", "http://hzvrsvul-rotate:je47prui48ga@p.webshare.io:80")
    open_with_playwright(target, proxy_url=proxy)
