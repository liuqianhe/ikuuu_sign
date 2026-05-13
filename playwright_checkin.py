"""
Playwright 方案：模拟点击 → 等它自动跳转 → 直接从浏览器拿 Cookie
"""
import os
import json
import time
import sys
import random
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from threading import Lock
from filelock import FileLock

try:
    from playwright.sync_api import sync_playwright, TimeoutError as PwTimeout
except ImportError as e:
    print(f"❌ Playwright 导入失败: {e}")
    print("请运行: pip install playwright==1.48.0")
    sys.exit(1)

import urllib.parse
from urllib.parse import urlparse
import requests

# ─────────────── 配置 ───────────────
COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ikuuu_cookies.json")
COOKIE_MAX_AGE_DAYS = 7
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"

DOMAINS = ["ikuuu.fyi", "ikuuu.win"]
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkin_result.json")

_cookie_store_lock = FileLock(COOKIE_FILE + ".lock")

# ─────────────── Cookie 存储（复用原逻辑） ───────────────
def get_cookie_key(email, base_url):
    host = urlparse(base_url).netloc.lower()
    return f"{email}@@{host}"

def load_cookie_store():
    with _cookie_store_lock:
        if not os.path.exists(COOKIE_FILE):
            return {}
        try:
            with open(COOKIE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception:
            return {}

def save_cookie_store(store):
    with _cookie_store_lock:
        try:
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(store, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"  ⚠️ 保存cookie失败: {e}")

def save_session_cookie(email, base_url, pw_cookies):
    key = get_cookie_key(email, base_url)
    store = load_cookie_store()
    cookie_dict = {}
    for c in pw_cookies:
        if c.get("sameSite") == "None":
            c["sameSite"] = "none"
        name = c.get("name")
        value = c.get("value")
        if name and value is not None:
            cookie_dict[name] = value
    store[key] = {
        "email": email,
        "base_url": base_url,
        "saved_at": int(time.time()),
        "cookies": cookie_dict,
        "source": "playwright",
    }
    save_cookie_store(store)

def load_session_cookie(email, base_url):
    key = get_cookie_key(email, base_url)
    store = load_cookie_store()
    item = store.get(key)
    if not item:
        return None
    saved_at = int(item.get("saved_at", 0))
    max_age = COOKIE_MAX_AGE_DAYS * 24 * 3600
    if not saved_at or time.time() - saved_at > max_age:
        return None
    cookies = item.get("cookies")
    if not isinstance(cookies, dict) or not cookies:
        return None
    return cookies

def clear_session_cookie(email, base_url):
    key = get_cookie_key(email, base_url)
    store = load_cookie_store()
    if key in store:
        del store[key]
        save_cookie_store(store)

# ─────────────── 邮箱脱敏 ───────────────
def mask_email(email):
    idx = email.find('@')
    if idx <= 0:
        return email
    return email[0] + '***' + email[idx:]


# ─────────────── 账号获取 ───────────────
def get_accounts():
    accounts = []
    account_str = os.getenv('ACCOUNTS')
    if account_str and account_str.strip():
        for line in account_str.strip().splitlines():
            line = line.strip()
            if line and ':' in line:
                email, pwd = line.split(':', 1)
                accounts.append((email.strip(), pwd.strip()))
    else:
        print("❌ 未配置 ACCOUNTS 环境变量")
        return None
    print(f"📋 找到 {len(accounts)} 个账户")
    return accounts

# ─────────────── 验证 Cookie ───────────────
def validate_cookie(session, base_url):
    """返回: True=有效, False=过期, None=网络异常（保留cookie）"""
    try:
        resp = session.get(
            base_url + "/user",
            headers={"User-Agent": USER_AGENT},
            timeout=15,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return False
        if "/auth/login" in resp.url.lower():
            return False
        if "var originBody" in resp.text or "剩余流量" in resp.text:
            return True
        return False
    except requests.exceptions.RequestException:
        return None

# ─────────────── 签到 ───────────────
def do_checkin(session, base_url):
    try:
        resp = session.post(
            base_url + '/user/checkin',
            headers={
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                "User-Agent": USER_AGENT,
            },
            timeout=20,
            allow_redirects=True,
        )
        if resp.status_code != 200:
            return False, f"签到失败(状态码{resp.status_code})"
        data = resp.json()
        if data.get('ret') == 1:
            return True, f"成功 | {data.get('msg', '')}"
        msg = str(data.get('msg', '未知'))
        if any(p in msg for p in ['已签到', '已经签到', '已簽到', 'already']):
            return True, f"成功 | {msg}"
        return False, f"签到失败: {msg}"
    except Exception as e:
        return False, f"签到异常: {e}"

# ─────────────── 模拟真人鼠标移动 ───────────────
def human_click(page, element):
    box = element.bounding_box()
    if not box:
        element.click()
        return
    viewport = page.viewport_size
    start_x = viewport["width"] * random.uniform(0.3, 0.7)
    start_y = viewport["height"] * random.uniform(0.3, 0.7)
    target_x = box["x"] + box["width"] / 2 + random.uniform(-5, 5)
    target_y = box["y"] + box["height"] / 2 + random.uniform(-5, 5)

    steps = random.randint(18, 35)
    for i in range(steps):
        t = i / steps
        ease = 1 - (1 - t) ** 2
        curr_x = start_x + (target_x - start_x) * ease
        curr_y = start_y + (target_y - start_y) * ease
        page.mouse.move(curr_x, curr_y)
        page.wait_for_timeout(random.randint(8, 18))

    page.wait_for_timeout(random.randint(80, 250))
    page.mouse.click(target_x, target_y)


# ─────────────── Playwright 登录（context 级别）───────────────
def login_in_context(context, email, password, base_url, timeout_ms=60000):
    """
    在已有 context 中完成登录流程，返回 cookies 或 None
    """
    page = context.new_page()

    # 拦截无用资源（图片/字体/媒体），不下载省时间
    page.route("**/*", lambda route: route.abort()
        if route.request.resource_type in ("image", "font", "media")
        else route.continue_())

    login_url = f"{base_url}/auth/login"

    try:
        print(f"  🌐 打开登录页: {login_url}")
        page.goto(login_url, wait_until="domcontentloaded", timeout=timeout_ms)
        print(f"  ✅ 页面加载完成: {page.title()}")

        page.wait_for_selector('#email', timeout=10000)
        print(f"  📝 填写账号密码...")

        page.fill('#email', email)
        page.fill('#password', password)

        page.wait_for_selector('.embed-captcha', timeout=10000)

        try:
            page.click('.geetest_btn_click', timeout=5000)
            print(f"  ✅ 已点击验证按钮")
        except:
            print(f"  ℹ️ 未找到验证按钮，可能无需点击")

        page.wait_for_function(
            "() => window.Captcha && window.Captcha.isReady()",
            timeout=20000
        )

        login_btn = page.query_selector('button[type="submit"]')
        if not login_btn:
            return None, "未找到登录按钮"

        print(f"  🖱️ 模拟真人移动并点击登录...")
        human_click(page, login_btn)

        try:
            page.wait_for_url(
                lambda url: "/user" in url or "/dashboard" in url or "checkin" in url,
                timeout=15000,
            )
            print(f"  ✅ 检测到跳转: {page.url}")
        except PwTimeout:
            current_url = page.url
            content = page.content()
            if "/auth/login" not in current_url or "签到" in content or "剩余流量" in content:
                print(f"  ⚠️ 未检测到跳转，但页面内容可能已成功: {current_url}")
            else:
                return None, "登录后未检测到期望的页面跳转"

        pw_cookies = context.cookies()
        if not pw_cookies:
            return None, "未获取到 Cookie"

        print(f"  🍪 获取到 {len(pw_cookies)} 个 Cookie 条目")
        return pw_cookies, None

    except PwTimeout as e:
        return None, f"操作超时: {e}"
    except Exception as e:
        return None, f"异常: {e}"
    finally:
        page.close()


# ─────────────── 并行登录一个账号 ───────────────
_print_lock = Lock()
_context_lock = Lock()


def tprint(*args, **kwargs):
    with _print_lock:
        print(*args, **kwargs)


def login_with_shared_browser(browser, email, password, domains, timeout_ms=60000):
    """共用 browser，每个账号独立 context 并行登录"""
    masked = mask_email(email)
    for domain in domains:
        base_url = f"https://{domain}"
        context = None
        try:
            with _context_lock:
                context = browser.new_context(
                    user_agent=USER_AGENT,
                    viewport={"width": 1280, "height": 800},
                    locale="zh-CN",
                )
                context.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                    Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                """)

            tprint(f"  [{masked}] 尝试 {domain}")
            pw_cookies, err = login_in_context(context, email, password, base_url, timeout_ms)

            if pw_cookies:
                return email, pw_cookies, None, domain
            tprint(f"  [{masked}] {domain} 失败: {err}")
        except Exception as e:
            tprint(f"  [{masked}] {domain} 异常: {e}")
        finally:
            if context:
                context.close()
    return email, None, f"所有域名登录失败", None


def login_account(email, password, domains, headless, timeout_ms=60000):
    """独立浏览器登录单个账号（备选方案）"""
    for domain in domains:
        base_url = f"https://{domain}"
        masked = mask_email(email)
        try:
            with sync_playwright() as p:
                browser = None
                context = None
                try:
                    browser = p.chromium.launch(
                        headless=headless,
                        args=[
                            "--no-sandbox",
                            "--disable-gpu",
                            "--disable-dev-shm-usage",
                            "--disable-blink-features=AutomationControlled",
                        ],
                    )
                    context = browser.new_context(
                        user_agent=USER_AGENT,
                        viewport={"width": 1280, "height": 800},
                        locale="zh-CN",
                    )
                    context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                    """)

                    tprint(f"  [{masked}] 尝试 {domain}")
                    pw_cookies, err = login_in_context(context, email, password, base_url, timeout_ms)

                    if pw_cookies:
                        return email, pw_cookies, None, domain
                    tprint(f"  [{masked}] {domain} 失败: {err}")
                finally:
                    if context:
                        context.close()
                    if browser:
                        browser.close()
        except Exception as e:
            tprint(f"  [{masked}] {domain} 异常: {e}")
    return email, None, f"所有域名登录失败", None


# ─────────────── 主流程 ───────────────
if __name__ == "__main__":
    print("🚀 iKuuu Playwright 签到脚本启动")
    print("=" * 50)

    headless = os.getenv("PLAYWRIGHT_HEADLESS", "1") != "0"
    print(f"{'🕶️ 无头模式' if headless else '🖥️  有头模式'}")

    accounts = get_accounts()
    if not accounts:
        sys.exit(1)

    results = []

    # ── 第一轮：并行试 cookie，网络异常保留cookie ──
    def cookie_checkin(email, password):
        """返回 (email, result_dict_or_None, need_login)"""
        for domain in DOMAINS:
            base_url = f"https://{domain}"
            cached = load_session_cookie(email, base_url)
            if not cached:
                continue
            sess = requests.session()
            sess.cookies = requests.utils.cookiejar_from_dict(cached)
            status = validate_cookie(sess, base_url)
            if status is None:
                tprint(f"  ⚠️ {mask_email(email)} [{domain}] 网络异常，保留 cookie 下次再试")
                return email, None, True
            if status is True:
                ok_s, msg = do_checkin(sess, base_url)
                masked = mask_email(email)
                r = {"email": masked, "success": ok_s, "message": msg, "domain": domain}
                tprint(f"  🍪 [{domain}] {masked} {'✅' if ok_s else '❌'} {msg}")
                return email, r, False
            # status is False → cookie 真正失效
            tprint(f"  🗑️ [{domain}] {mask_email(email)} cookie 已过期，清理")
            clear_session_cookie(email, base_url)
        return email, None, True

    def cookie_checkin_with_retry(email, password, max_retries=2):
        for attempt in range(max_retries):
            ret_email, result, need_login = cookie_checkin(email, password)
            if result or not need_login:
                return ret_email, result, need_login
            if attempt < max_retries - 1:
                tprint(f"  🔄 {mask_email(email)} 第{attempt+1}次失败，{attempt+1}s后重试")
                time.sleep(attempt + 1)
        return email, None, True

    need_login = []
    with ThreadPoolExecutor(max_workers=len(accounts)) as executor:
        fut_map = {executor.submit(cookie_checkin_with_retry, email, pwd): (idx, email, pwd) for idx, (email, pwd) in enumerate(accounts, 1)}
        for fut in as_completed(fut_map, timeout=120):
            idx, email, pwd = fut_map[fut]
            try:
                ret_email, result, should_login = fut.result(timeout=30)
            except TimeoutError:
                tprint(f"  ⚠️ {mask_email(email)} cookie 签到超时，转入浏览器登录")
                result = None
                should_login = True
            if result:
                results.append(result)
            if should_login:
                need_login.append((idx, email, pwd))

    # 第二轮：需要登录的，共用一个 browser，每个账号独立 context 并行
    if need_login:
        print(f"\n🎭 共用一个浏览器，并行登录 {len(need_login)} 个账号...")
        login_results = [None] * len(need_login)
        with sync_playwright() as p:
            browser = p.chromium.launch(
                headless=headless,
                args=[
                    "--no-sandbox",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-blink-features=AutomationControlled",
                ],
            )
            with ThreadPoolExecutor(max_workers=len(need_login)) as executor:
                fut_map = {}
                for idx, email, pwd in need_login:
                    fut = executor.submit(login_with_shared_browser, browser, email, pwd, DOMAINS)
                    fut_map[fut] = (idx, email)

                for fut in as_completed(fut_map, timeout=180):
                    idx, email = fut_map[fut]
                    try:
                        ret_email, pw_cookies, err, domain = fut.result(timeout=150)
                    except Exception as e:
                        ret_email, pw_cookies, err, domain = email, None, str(e), None
                    login_results[idx - 1] = (ret_email, pw_cookies, err, domain)
            browser.close()

        # 处理所有登录结果
        for idx, email, pwd in need_login:
            masked = mask_email(email)
            ret_email, pw_cookies, err, domain = login_results[idx - 1]
            base_url = f"https://{domain}" if domain else None

            if err or not pw_cookies:
                print(f"  ❌ {masked} 登录失败: {err}")
                results.append({"email": masked, "success": False, "message": f"登录失败: {err}", "domain": domain or "all"})
                continue

            if base_url:
                cookie_dict = {c["name"]: c["value"] for c in pw_cookies if c.get("name") and c.get("value") is not None}
                sess = requests.session()
                sess.cookies = requests.utils.cookiejar_from_dict(cookie_dict)
                ok_s, msg = do_checkin(sess, base_url)

                if ok_s:
                    save_session_cookie(email, base_url, pw_cookies)
                    print(f"  💾 {masked} Cookie 已保存 ({domain})")

                results.append({"email": masked, "success": ok_s, "message": msg, "domain": domain})
                icon = "✅" if ok_s else "❌"
                print(f"  {icon} {masked} {msg}")

    # 输出结果文件供 workflow 读取
    has_failure = any(not r["success"] for r in results)
    summary_lines = []
    print("\n📊 汇总:")
    print("=" * 50)
    for r in results:
        icon = "✅" if r["success"] else "❌"
        line = f"{icon} {r['email']} | {r['message']}"
        print(line)
        summary_lines.append(line)
    print("=" * 50)
    print("🏁 执行完成")

    try:
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump({"results": results, "summary": "\n".join(summary_lines), "has_failure": has_failure}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
