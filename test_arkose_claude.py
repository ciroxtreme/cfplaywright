"""
Test driver: login penuh Claude via login (bukan cookie), dengan Arkose solver.

Alur yang dites: buka halaman login Claude, masukin email, kirim kode
verifikasi -- pas layar masukin kode mau muncul, di situlah Arkose muncul.
Solver dicoba di titik itu; kalau layar kode muncul tanpa puzzle, lanjut
masukin kode verifikasi sampai login penuh berhasil.

Kode verifikasi diambil dari env CLAUDE_CODE, atau dari file yang ditunggu
driver (default /tmp/claude_code.txt, bisa diubah via env CLAUDE_CODE_FILE).
File cukup berisi 6 digit kode saja.

Usage:
    python test_arkose_claude.py <email> [proxy]
    CLAUDE_EMAIL=<email> ARKOSE_HEADLESS=1 python test_arkose_claude.py

Email dan kode TIDAK boleh di-hardcode -- selalu lewat argv/env/file.
Hasil akhir dicetak sebagai:
[ARKOSE-TEST] RESULT: <LOGIN-SUCCESS|LOGIN-FAILED|CODE-TIMEOUT|SUPPRESSED|CHALLENGED|NO-ARKOSE|UNKNOWN|ERROR>
"""

import os
import re
import sys
import time
import urllib.parse
from patchright.sync_api import sync_playwright

from arkose import solve_arkose_on_page, is_arkose_present

LOGIN_URL = "https://claude.ai/login"
CODE_FILE = os.environ.get("CLAUDE_CODE_FILE", "/tmp/claude_code.txt")
CODE_WAIT_SECONDS = int(os.environ.get("CLAUDE_CODE_WAIT", "300"))


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


def _code_screen_present(page) -> bool:
    try:
        n = page.locator(
            'input[inputmode="numeric"], input[autocomplete="one-time-code"],'
            ' input[name*="code" i], input[aria-label*="code" i]').count()
        if n > 0:
            return True
        return bool(re.search(r"enter (the|your) code|check your email|verification code",
                              (page.content() or "").lower()))
    except Exception:
        return False


def assess_outcome(page):
    """SUPPRESSED / CHALLENGED / UNKNOWN after the solve attempt."""
    try:
        body = (page.content() or "").lower()
    except Exception:
        body = ""
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
    if _code_screen_present(page):
        return "SUPPRESSED"
    return "UNKNOWN"


def _wait_for_code(timeout=CODE_WAIT_SECONDS):
    """6-digit code from env, else poll CODE_FILE. Returns '' on timeout."""
    env_code = os.environ.get("CLAUDE_CODE", "").strip()
    if re.fullmatch(r"\d{6}", env_code):
        return env_code
    print(f"[*] [Arkose-Test] WAITING-FOR-CODE (file {CODE_FILE}, max {timeout}s)...",
          flush=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with open(CODE_FILE) as f:
                m = re.search(r"\d{6}", f.read())
            if m:
                return m.group(0)
        except FileNotFoundError:
            pass
        except Exception:
            pass
        time.sleep(5)
    return ""


def _fill_code(page, code: str) -> bool:
    """Fill the 6-digit code: single input first, else 6 one-char boxes."""
    try:
        single = page.locator(
            'input[autocomplete="one-time-code"], input[inputmode="numeric"]').first
        if single.count() > 0:
            single.click()
            single.fill(code)
            return True
    except Exception:
        pass
    try:
        boxes = page.locator('input[maxlength="1"]')
        if boxes.count() >= 6:
            for i, ch in enumerate(code[:6]):
                boxes.nth(i).click()
                boxes.nth(i).fill(ch)
            return True
    except Exception:
        pass
    return False


def main():
    email = sys.argv[1] if len(sys.argv) > 1 else os.environ.get("CLAUDE_EMAIL", "")
    proxy = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("PROXY_URL", "")
    if not email or "@" not in email:
        print("Usage: python test_arkose_claude.py <email> [proxy]")
        print("  atau set env CLAUDE_EMAIL. Email tidak boleh di-hardcode.")
        return "ERROR"
    headless = os.environ.get("ARKOSE_HEADLESS", "") == "1"
    # Channel Chrome default; kosongkan (ARKOSE_CHROME_CHANNEL="") untuk
    # memakai Chromium bawaan patchright (berguna buat tes lokal tanpa Chrome).
    channel = os.environ.get("ARKOSE_CHROME_CHANNEL", "chrome") or None

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
            channel=channel, headless=headless, proxy=proxy_cfg,
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
                    print("[*] Email diisi, klik lanjut...")
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
                        arkose_result = assess_outcome(page)
                        if arkose_result == "SUPPRESSED":
                            print("✓ [Arkose] Layar kode muncul TANPA puzzle.")
                        result = arkose_result
                    else:
                        if is_arkose_present(page):
                            result = "CHALLENGED"
                            print("[-] [Arkose] Solver tidak menghasilkan token, "
                                  "puzzle masih ada.")
                        else:
                            result = assess_outcome(page)
                            if result == "SUPPRESSED":
                                print("[*] Layar kode muncul tanpa Arkose sama sekali.")
                    # --- login penuh: masukin kode verifikasi ---
                    if result == "SUPPRESSED" and _code_screen_present(page):
                        code = _wait_for_code()
                        if not code:
                            print("[-] Kode verifikasi tidak datang tepat waktu.")
                            result = "CODE-TIMEOUT"
                        elif _fill_code(page, code):
                            print("[*] Kode diisi, submit...")
                            submit = _first_visible(page, [
                                'button[type="submit"]',
                                'button:has-text("Verify")',
                                'button:has-text("Continue")'], timeout=10000)
                            if submit:
                                submit.click()
                            else:
                                page.keyboard.press("Enter")
                            logged_in = False
                            for _ in range(10):
                                time.sleep(2)
                                if "/login" not in page.url:
                                    logged_in = True
                                    break
                            if logged_in:
                                print(f"✓ [Arkose-Test] LOGIN PENUH BERHASIL: {page.url}")
                                result = "LOGIN-SUCCESS"
                            else:
                                print("[-] Masih di halaman login setelah submit kode.")
                                result = "LOGIN-FAILED"
                        else:
                            print("[-] Kolom kode tidak ketemu buat diisi.")
                            result = "LOGIN-FAILED"
                    page.screenshot(path="arkose_claude_result.png")
                    try:
                        from cfplaywright import send_telegram_photo
                        send_telegram_photo(
                            "arkose_claude_result.png",
                            caption=f"🧩 Arkose test Claude: {result} | {page.url}")
                    except Exception as e:
                        print(f"[-] Telegram send skip: {e}")
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
    sys.exit(0 if main() in ("LOGIN-SUCCESS", "SUPPRESSED", "NO-ARKOSE") else 1)
