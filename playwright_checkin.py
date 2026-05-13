"""
Playwright 方案：模拟点击 → 等它自动跳转 → 直接从浏览器拿 Cookie
"""
import os
import json
import time
import base64
import datetime
import re
import sys
import random
from bs4 import BeautifulSoup

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

DOMAINS = ["ikuuu.fyi", "ikuuu.win", "ikuuu.org"]
RESULT_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "checkin_result.json")

# ─────────────── Cookie 存储（复用原逻辑） ───────────────
def get_cookie_key(email, base_url):
    host = urlparse(base_url).netloc.lower()
    return f"{email}@@{host}"

def load_cookie_store():
    if not os.path.exists(COOKIE_FILE):
        return {}
    try:
        with open(COOKIE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}

def save_cookie_store(store):
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
    except Exception:
        return False

# ─────────────── 获取剩余流量（复用原逻辑） ───────────────
def get_remaining_flow(cookies, base_url=None):
    user_url = f'{base_url or "https://ikuuu.fyi"}/user'
    try:
        user_page = requests.get(user_url, cookies=cookies, headers={"User-Agent": USER_AGENT}, timeout=20)
        if user_page.status_code != 200:
            return "获取失败", f"状态码: {user_page.status_code}"
        match = re.search(r'var originBody = "([^"]+)"', user_page.text)
        if not match:
            return "未找到", "Base64内容"
        decoded = base64.b64decode(match.group(1)).decode('utf-8')
        soup = BeautifulSoup(decoded, 'html.parser')
        for card in soup.find_all('div', class_='card card-statistic-2'):
            h4 = card.find('h4')
            if h4 and '剩余流量' in h4.text:
                counter = card.find('span', class_='counter')
                if counter:
                    val = counter.text.strip()
                    nxt = counter.next_sibling
                    unit = nxt.strip() if nxt else ""
                    return val, unit
        return "未找到", "流量信息"
    except Exception as e:
        return "异常", str(e)

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

    # 第一轮：所有账号先试本地 cookie（取第一个域名试）
    need_login = []
    for idx, (email, pwd) in enumerate(accounts, 1):
        masked = mask_email(email)
        print(f"\n👤 [{idx}/{len(accounts)}] {masked}")
        ok = False
        for domain in DOMAINS:
            base_url = f"https://{domain}"
            cached = load_session_cookie(email, base_url)
            if not cached:
                continue
            sess = requests.session()
            sess.cookies = requests.utils.cookiejar_from_dict(cached)
            if validate_cookie(sess, base_url):
                print(f"  🍪 [{domain}] Cookie 有效，直接签到")
                flow_val, flow_unit = get_remaining_flow(cached, base_url)
                ok_s, msg = do_checkin(sess, base_url)
                results.append({"email": masked, "success": ok_s, "message": msg, "flow_value": flow_val, "flow_unit": flow_unit, "domain": domain})
                icon = "✅" if ok_s else "❌"
                print(f"  {icon} {msg}")
                print(f"  📊 剩余流量: {flow_val} {flow_unit}")
                ok = True
                break
            else:
                print(f"  ⚠️ [{domain}] Cookie 已失效")
                clear_session_cookie(email, base_url)
        if not ok:
            need_login.append((idx, email, pwd))

    # 第二轮：需要登录的，遍历域名重试
    if need_login:
        print(f"\n🎭 启动浏览器，处理 {len(need_login)} 个需要登录的账号...")
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
            for idx, email, pwd in need_login:
                masked = mask_email(email)
                print(f"\n👤 [{idx}/{len(accounts)}] {masked}")
                done = False
                for domain in DOMAINS:
                    base_url = f"https://{domain}"
                    print(f"  尝试域名: {domain}")
                    context = browser.new_context(
                        user_agent=USER_AGENT,
                        viewport={"width": 1280, "height": 800},
                        locale="zh-CN",
                    )
                    context.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                        Object.defineProperty(navigator, 'plugins', { get: () => [1,2,3,4,5] });
                    """)

                    pw_cookies, err = login_in_context(context, email, pwd, base_url)
                    if err or not pw_cookies:
                        print(f"  ⚠️ [{domain}] 登录失败: {err}")
                        context.close()
                        continue

                    save_session_cookie(email, base_url, pw_cookies)
                    print(f"  💾 Cookie 已保存")

                    cookie_dict = {c["name"]: c["value"] for c in pw_cookies if c.get("name") and c.get("value") is not None}
                    flow_val, flow_unit = get_remaining_flow(cookie_dict, base_url)
                    sess = requests.session()
                    sess.cookies = requests.utils.cookiejar_from_dict(cookie_dict)
                    ok_s, msg = do_checkin(sess, base_url)

                    results.append({"email": masked, "success": ok_s, "message": msg, "flow_value": flow_val, "flow_unit": flow_unit, "domain": domain})
                    icon = "✅" if ok_s else "❌"
                    print(f"  {icon} {msg}")
                    print(f"  📊 剩余流量: {flow_val} {flow_unit}")

                    context.close()
                    done = True
                    break

                if not done:
                    results.append({"email": masked, "success": False, "message": f"所有域名登录失败", "flow_value": "-", "flow_unit": "-", "domain": "all"})

            browser.close()

    # 输出结果文件供 workflow 读取
    has_failure = any(not r["success"] for r in results)
    summary_lines = []
    print("\n📊 汇总:")
    print("=" * 50)
    for r in results:
        icon = "✅" if r["success"] else "❌"
        line = f"{icon} {r['email']} | {r['message']} | {r['flow_value']} {r['flow_unit']}"
        print(line)
        summary_lines.append(line)
    print("=" * 50)
    print("🏁 执行完成")

    try:
        with open(RESULT_FILE, "w", encoding="utf-8") as f:
            json.dump({"results": results, "summary": "\n".join(summary_lines), "has_failure": has_failure}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
