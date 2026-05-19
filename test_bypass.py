"""
测试极验 V4 Captcha bypass —— 注入 JS 伪造 Captcha 对象，跳过客户端验证码验证
"""
import os
import asyncio
from playwright.async_api import async_playwright

EMAIL = "philips25@163.com"
PASSWORD = "flzx3qc|"
DOMAIN = "ikuuu.win"
BASE_URL = f"https://{DOMAIN}"

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=False,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = await context.new_page()

        await page.route("**/*", lambda route: route.abort()
            if route.request.resource_type in ("image", "font", "media")
            else route.continue_())

        print(f"🌐 打开登录页: {BASE_URL}/auth/login")
        await page.goto(f"{BASE_URL}/auth/login", wait_until="domcontentloaded")
        print(f"✅ 页面加载完成: {await page.title()}")

        # 注入伪造的 Captcha 对象
        await page.evaluate("""
            window.Captcha = {
                isReady: () => true,
                getResponse: () => ({
                    lot_number: 'bypass_' + Date.now(),
                    captcha_output: 'bypass',
                    pass_token: 'bypass',
                    gen_time: Date.now()
                }),
                reset: () => {},
                getProvider: () => 'bypass'
            };
        """)
        print("✅ Captcha bypass 注入完成")

        # 填写表单
        await page.fill('#email', EMAIL)
        await page.fill('#password', PASSWORD)
        print("📝 表单已填写")

        # 监听 navigate 事件，防止 page 意外关闭
        async def on_close():
            print("⚠️ 页面被关闭")
        page.on("close", on_close)

        # 点击 Login
        login_btn = await page.query_selector('button[type="submit"]')
        if not login_btn:
            print("❌ 未找到登录按钮")
            await browser.close()
            return

        print("🖱️ 点击登录...")

        # 监听 AJAX 响应
        async def on_response(response):
            if "/auth/login" in response.url:
                try:
                    body = await response.json()
                    print(f"📡 登录接口返回: {body}")
                except:
                    text = await response.text()
                    print(f"📡 登录接口返回(非JSON): {text[:500]}")
        page.on("response", on_response)

        await login_btn.click()

        # 等跳转
        try:
            await page.wait_for_url(
                lambda url: "/user" in url or "/dashboard" in url or "checkin" in url,
                timeout=15000
            )
            print(f"✅ 登录成功，跳转到: {page.url}")
        except:
            print(f"⚠️ 未检测到跳转，当前 URL: {page.url}")
            try:
                content = await page.content()
                if "剩余流量" in content or "签到" in content:
                    print("✅ 但页面内容显示已登录")
                else:
                    print("❌ 登录失败，页面未显示登录状态")
            except Exception as e:
                print(f"❌ 页面已关闭，无法获取内容: {e}")

        try:
            cookies = await context.cookies()
            print(f"🍪 Cookies: {len(cookies)} 个")
        except:
            print("🍪 Context 已关闭")

        input("按 Enter 退出...")
        await browser.close()

asyncio.run(main())
