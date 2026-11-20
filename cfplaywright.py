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
import urllib.parse
from patchright.sync_api import sync_playwright

def solve_cloudflare_clearance(target_url: str, proxy: str = None) -> str:
    """
    Panggil binary Rust cfsolve untuk menyelesaikan Cloudflare challenge
    dan mengembalikan token cf_clearance dalam hitungan milidetik.
    """
    out_dir = f"/tmp/cf_out_{int(time.time()*1000)}"
    if os.path.exists(out_dir):
        shutil.rmtree(out_dir)
    os.makedirs(out_dir, exist_ok=True)

    bin_path = os.path.abspath("bin/cfsolve")
    if not os.path.exists(bin_path):
        bin_path = "/home/container/.local/bin/cfsolve-v5-cli"

    fp_path = os.path.abspath("profiles/safari-26-ios.json")

    cmd = [
        bin_path,
        "--page", target_url,
        out_dir,
        "--solve",
        "--fingerprint", fp_path
    ]

    if proxy:
        cmd.extend(["--proxy", proxy])

    print(f"⚡ [CFSolve] Menembus Cloudflare Turnstile untuk {target_url}...")
    t0 = time.time()
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        elapsed = time.time() - t0
        output = proc.stdout + proc.stderr

        # Cari cf_clearance=<token>
        import re
        m = re.search(r"cf_clearance=([a-zA-Z0-9_\-\.]+)", output)
        if m:
            token = m.group(1)
            print(f"✓ [CFSolve] Sukses ditembus dalam {elapsed:.2f}s! cf_clearance: {token[:25]}...")
            return token
        else:
            print(f"[-] [CFSolve] Token tidak ditemukan di output (Exit code {proc.returncode}):")
            print(output[:300])
    except Exception as e:
        print(f"[-] [CFSolve Error]: {e}")
    finally:
        shutil.rmtree(out_dir, ignore_errors=True)

    return ""

def open_with_playwright(target_url: str, proxy_url: str = None):
    """
    Buka Playwright dengan Chrome resmi + CFSolve Injection + Extension.
    """
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
        time.sleep(4)

        title = page.title()
        curr_url = page.url
        print(f"📄 Berhasil dimuat dalam {time.time()-t_nav:.2f}s!")
        print(f"📄 Judul Halaman: {title}")
        print(f"📄 URL Saat Ini: {curr_url}")

        page.screenshot(path="cctv_banyuasin_playwright.png")
        print("📸 Screenshot tersimpan ke 'cctv_banyuasin_playwright.png'!")

        # Tunggu 3 detik sebelum selesai
        time.sleep(3)
        browser.close()

if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else "https://cctv.banyuasinkab.go.id/"
    proxy = os.environ.get("PROXY_URL", "http://hzvrsvul-rotate:je47prui48ga@p.webshare.io:80")
    open_with_playwright(target, proxy_url=proxy)
