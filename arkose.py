"""
Arkose (FunCaptcha) solver module for CFPlaywright.

Uses the MIT-licensed `arkose-solver` PyPI package (buggerlogger/arkose-solver):
it builds a browser fingerprint blob (BDA), encrypts it with the site's RSA key
(derived from the served api.js on every solve), POSTs once to the Arkose
verify host, and returns a token. If the token carries sup=1, the challenge is
suppressed -- no puzzle appears.

No credentials are stored here. The Arkose public key + verify host are
extracted from the live page, the user agent comes from the running browser,
and the proxy (if any) comes from the caller / env. The package itself is an
optional dependency: if it is not installed, solving is skipped gracefully and
the main flow continues untouched.

NOTE: this file is intentionally named arkose.py, NOT arkose_solver.py, so it
never shadows the `arkose_solver` PyPI package on sys.path.
"""

import re
import time
import urllib.parse

_UUID_RE = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
_SRC_RE = re.compile(
    r"https?://([^/]+)/(?:fc/gt2/public_key|v2)/(" + _UUID_RE + r")",
    re.IGNORECASE,
)
_PK_PARAM_RE = re.compile(r"[?&]public_key=(" + _UUID_RE + r")", re.IGNORECASE)
_PK_JSON_RE = re.compile(r'"public_key"\s*:\s*("(' + _UUID_RE + r')")', re.IGNORECASE)

_EXTRACT_JS = """() => {
  const srcs = [];
  document.querySelectorAll('iframe').forEach(f => { if (f.src) srcs.push(f.src); });
  document.querySelectorAll('script[src]').forEach(s => { if (s.src) srcs.push(s.src); });
  const fcInputs = document.querySelectorAll('input[name="fc-token"]').length;
  return {srcs, fcInputs, url: location.href, ua: navigator.userAgent,
          lang: navigator.language || 'en-US'};
}"""

_INJECT_JS = """(tok) => {
  const hit = [];
  const inputs = document.querySelectorAll(
    'input[name="fc-token"], input[id*="fc-token"], textarea[name="fc-token"]');
  inputs.forEach(el => {
    try {
      const setter = Object.getOwnPropertyDescriptor(
        window.HTMLInputElement.prototype, 'value').set;
      setter.call(el, tok);
    } catch (e) { el.value = tok; }
    el.dispatchEvent(new Event('input', {bubbles: true}));
    el.dispatchEvent(new Event('change', {bubbles: true}));
    hit.push('fc-token-input');
  });
  window.__arkose_token = tok;
  if (typeof window.arkoseCallback === 'function') {
    try { window.arkoseCallback(tok); hit.push('arkoseCallback'); } catch (e) {}
  }
  if (typeof window.onArkoseComplete === 'function') {
    try { window.onArkoseComplete(tok); hit.push('onArkoseComplete'); } catch (e) {}
  }
  return hit;
}"""


def is_arkose_present(page) -> bool:
    """True if the page shows any Arkose / FunCaptcha marker."""
    try:
        html = page.content() or ""
        low = html.lower()
        if "arkose" in low or "funcaptcha" in low:
            return True
    except Exception:
        pass
    try:
        for frame in page.frames:
            if "arkose" in (frame.url or "").lower():
                return True
    except Exception:
        pass
    return False


def parse_arkose_params(srcs, page_url: str = "", user_agent: str = "",
                        language: str = "en-US"):
    """Pull (public_key, surl) out of Arkose iframe / api.js URLs.

    Returns a params dict, or None when nothing usable was found.
    `surl` is the verify host as a full origin, e.g.
    https://client-api.arkoselabs.com
    """
    public_key = ""
    surl = ""
    for src in srcs or []:
        m = _SRC_RE.search(src or "")
        if m:
            surl = "https://" + m.group(1)
            public_key = m.group(2).lower()
            break
        m = _PK_PARAM_RE.search(src or "")
        if m:
            public_key = m.group(1).lower()
    if not public_key:
        return None
    if not surl:
        # Public key known but no verify host seen: Arkose's default host.
        surl = "https://client-api.arkoselabs.com"
    site = ""
    if page_url:
        p = urllib.parse.urlparse(page_url)
        if p.scheme and p.netloc:
            site = "%s://%s" % (p.scheme, p.netloc)
    return {
        "public_key": public_key,
        "surl": surl,
        "site": site,
        "page_url": page_url,
        "user_agent": user_agent,
        "language": language,
    }


def extract_arkose_params(page):
    """Extract Arkose params from the live Playwright page, or None."""
    try:
        data = page.evaluate(_EXTRACT_JS)
    except Exception as e:
        print(f"[-] [Arkose] Gagal membaca halaman: {e}")
        return None
    params = parse_arkose_params(
        data.get("srcs"), page_url=data.get("url", ""),
        user_agent=data.get("ua", ""), language=data.get("lang", "en-US"))
    if params is None:
        # Last resort: a public key embedded in the page markup.
        try:
            html = page.content() or ""
        except Exception:
            html = ""
        m = _PK_JSON_RE.search(html)
        if m:
            params = parse_arkose_params([], page_url=data.get("url", ""),
                                         user_agent=data.get("ua", ""))
            params["public_key"] = m.group(2).lower()
    return params


def solve_arkose(params, proxy=None):
    """Solve once via the arkose-solver package.

    Returns (token, suppressed). Raises ImportError if the package is missing,
    RuntimeError if the verify host returns no token.
    """
    from arkose_solver import Solver  # lazy: package is optional

    solver = Solver(
        surl=params["surl"],
        public_key=params["public_key"],
        site=params.get("site") or params.get("surl"),
        proxy=proxy or None,
        user_agent=params.get("user_agent") or None,
        language=params.get("language", "en-US"),
    )
    res = solver.solve()
    return res.token, bool(res.suppressed)


def inject_arkose_token(page, token: str):
    """Push the token into the page. Returns the list of injection points hit."""
    try:
        return list(page.evaluate(_INJECT_JS, token))
    except Exception as e:
        print(f"[-] [Arkose] Gagal inject token: {e}")
        return []


def solve_arkose_on_page(page, proxy=None) -> str:
    """Detect Arkose on the page, solve it, inject the token.

    Returns the token on success, "" when there is no Arkose challenge or the
    solve fails. Never raises -- a solver failure must not kill the main flow.
    """
    try:
        if not is_arkose_present(page):
            return ""
        print("🔍 [Arkose] Widget terdeteksi, mengekstrak parameter...")
        params = extract_arkose_params(page)
        if not params:
            print("[-] [Arkose] Public key / verify host tidak ketemu di halaman.")
            return ""
        print(f"[*] [Arkose] pk={params['public_key'][:8]}... surl={params['surl']}")
        t0 = time.time()
        token, suppressed = solve_arkose(params, proxy=proxy)
        dt = time.time() - t0
        print(f"✓ [Arkose] Token didapat dalam {dt:.1f}s | sup=1: {suppressed} "
              f"| token: {token[:25]}...")
        hit = inject_arkose_token(page, token)
        if hit:
            print(f"💉 [Arkose] Token disuntikkan via: {', '.join(hit)}")
        else:
            print("[-] [Arkose] Tidak ada titik inject di halaman (token tetap dipegang).")
        return token
    except ImportError:
        print("[-] [Arkose] Paket 'arkose-solver' belum terinstall "
              "(pip install arkose-solver). Skip.")
        return ""
    except Exception as e:
        print(f"[-] [Arkose Notice]: {e}")
        return ""
