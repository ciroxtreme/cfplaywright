"""
Test driver: login Claude sampai Arkose muncul, lalu coba solver.

Alur yang dites (sesuai yang Ciro jelasin): buka halaman login Claude, masukin
email, kirim kode verifikasi -- pas layar masukin kode mau muncul, di situlah
Arkose muncul. Tes ini BERHENTI di layar masukin kode: kalau layar itu muncul
tanpa puzzle, solver berhasil (sup=1). Tidak login penuh, tidak butuh kode.

Usage:
    python test_arkose_claude.py <email> [proxy]
    CLAUDE_EMAIL=<email> python test_arkose_claude.py
    ARKOSE_HEADLESS=1 python test_arkose_claude.py <email>

Email TIDAK boleh di-hardcode -- selalu lewat argv/env.
Hasil akhir dicetak sebagai: [ARKOSE-TEST] RESULT: <SUPPRESSED|CHALLENGED|NO-ARKOSE|UNKNOWN|ERROR>
"""

import os
import re
import sys
import time
import urllib.parse
from patchright.sync_api import sync_playwright

from arkose import solve_arkose_on_page, is_arkose_present

LOGIN_URL = "https://claude.ai/login"

try:
    from cfplaywright import send_telegram_photo
except ImportError:
    def send_telegram_photo(path, caption=""):
        print("[-] Telegram send tidak tersedia (cfplaywright tidak ke-import).")


def _first_visible(page, selectors, timeout=15000):
    """Return the first selector that matches a visible element, or None."""
    for sel in selectors:
        try:
            loc = page.locator(sel).first
            loc.wait_for(state="visible", timeout=timeout)
            return loc
        except Exception:
            continue
    return None


def assess_outcome(page):
    """SUPPRESSED / CHALLENGED / NO-ARKOSE / UNKNOWN after the solve attempt."""
    try:
        body = (page.content() or "").lower()
    except Exception:
        body = ""
    code_input = 0
    try:
        code_input = page.locator(
            'input[inputmode="numeric"], input[autocomplete="one-time-code"],'
            ' input[name*="code" i], input[aria-label*="code" i]').count()
    except Exception:
        pass
    code_text = bool(re.search(r"enter (the|your) code|check your email|verification code",
                               body))
    code_screen = code_input > 0 or code_text
    puzzle = False
    try:
        puzzle = bool(page.evaluate("""() => {
          const frames = [...document.querySelectorAll('iframe')].filter(
            f => f.src && f.src.toLowerCase().includes('arkose'));
          const visible = frames.some(f => f.offsetParent !== null);
          const txt = (document.body.innerText || '').toLowerCase();
          const challenge = /verify you are human|select all images|i am not a robot|press & hold/.test(txt);
          return visible && challenge;
        }"""))
    except Exception:
        puzzle = "arkose" in body and "verify" in body
    if puzzle:
        return "CHALLENGED"
    if code_screen:
        return "SUPPRESSED"
    return "UNKNOWN"


def main():
    email = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CLAUDE_EMAIL", "")
    proxy = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PROXY_URL", "")
    if not email or "@" not in email:
        print("Usage: python test_arkose_claude.py <email> [proxy]")
        print("  atau set env CLAUDE_EMAIL. Email tidak boleh di-hardcode.")
        return "ERROR"
    headless = os.environ.get("ARKOSE_HEADLESS", "") == "1"

    proxy_cfg = None
    if proxy:
        parsed = urllib.parse.urlparse(proxy)
        if parsed.username and parsed.password:
            proxy_cfg = {"server": f"{parsed.scheme}://{parsed.hostname}:{parsed.port}",
                         "username": parsed.username, "password": parsed.password}
        else:
            proxy_cfg = {"server": proxy}

    result = "ERROR"
    with sync_playwright() as p:
        browser = p.chromium.launch(
            channel="chrome", headless=headless, proxy=proxy_cfg,
            args=["--no-sandbox", "--disable-setuid-sandbox",
                  "--disable-dev-shm-usage", "--window-size=1280,800"])
        context = browser.new_context(
            viewport={"width": 1280, "height": 800},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
            locale="en-US")
        page = context.new_page()
        try:
            print(f"🌐 Membuka {LOGIN_URL} ...")
            page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000)
            time.sleep(3)
            if "claude.ai" in page.url and "/login" not in page.url:
                print(f"[*] Sudah login (redirect ke {page.url}). Tidak ada Arkose.")
                result = "NO-ARKOSE"
            else:
                email_box = _first_visible(page, [
                    'input[type="email"]', 'input[name="email"]',
                    'input[inputmode="email"]',
                    'input[placeholder*="email" i]'])
                if not email_box:
                    print("[-] Kolom email tidak ketemu. Judul:", page.title())
                    page.screenshot(path="arkose_no_email_field.png")
                    result = "UNKNOWN"
                else:
                    email_box.fill(email)
                    print(f"[*] Email diisi, klik lanjut...")
                    btn = _first_visible(page, [
                        'button[type="submit"]',
                        'button:has-text("Continue with email")',
                        'button:has-text("Continue")'], timeout=10000)
                    if btn:
                        btn.click()
                    else:
                        email_box.press("Enter")
                    # Tunggu layar berikutnya: kode / Arkose
                    for _ in range(10):
                        time.sleep(2)
                        if is_arkose_present(page):
                            print("🔍 [Arkose] Muncul di alur login.")
                            break
                        if "code" in (page.content() or "").lower():
                            break
                    print(f"[*] URL sekarang: {page.url} | Judul: {page.title()}")
                    token = solve_arkose_on_page(page, proxy=proxy or None)
                    time.sleep(5)
                    if token:
                        result = assess_outcome(page)
                        # sup=1 tanpa puzzle + layar kode = SUPPRESSED;
                        # assess_outcome sudah membedakan puzzle vs layar kode.
                        if result == "SUPPRESSED":
                            print("✓ [Arkose] Layar kode muncul TANPA puzzle.")
                    else:
                        if is_arkose_present(page):
                            result = "CHALLENGED"
                            print("[-] [Arkose] Solver tidak menghasilkan token, "
                                  "puzzle masih ada.")
                        else:
                            result = assess_outcome(page)
                            if result == "SUPPRESSED":
                                print("[*] Layar kode muncul tanpa Arkose sama sekali.")
                    page.screenshot(path="arkose_claude_result.png")
                    send_telegram_photo(
                        "arkose_claude_result.png",
                        caption=f"🧩 Arkose test Claude: {result} | {page.url}")
        except Exception as e:
            print(f"[-] [Arkose-Test Error]: {e}")
            result = "ERROR"
            try:
                page.screenshot(path="arkose_claude_error.png")
            except Exception:
                pass
        finally:
            time.sleep(1)
            browser.close()
    print(f"[ARKOSE-TEST] RESULT: {result}")
    return result


if __name__ == "__main__":
    sys.exit(0 if main() in ("SUPPRESSED", "NO-ARKOSE") else 1)
