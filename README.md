# iKuuu Checkin — Playwright 方案

真实浏览器模拟签到，绕过 GeeTest 验证码，无需付费的验证码服务。

## 原理

Playwright 启动 Chromium → 打开登录页 → 填账号密码 → 触发极验(真实浏览器环境) → 等自动跳转 → 从浏览器提取 Cookie → 用 Cookie 签到。

## 环境变量

| 变量 | 说明 |
|------|------|
| `ACCOUNTS` | 账号密码，每行 `邮箱:密码`，多账户用换行分隔 |
| `PLAYWRIGHT_HEADLESS` | 默认 `1`（无头），设为 `0` 可看浏览器窗口（调试用） |

## 本地运行

```bash
pip install -r requirements.txt
playwright install chromium

export ACCOUNTS="user@example.com:password"
python playwright_checkin.py
```

## GitHub Actions

Fork 本仓库 → Settings → Secrets → 添加 `ACCOUNTS` 变量 → 每天 UTC 0:00 自动执行。

## 文件

- `playwright_checkin.py` — 主脚本
- `.github/workflows/checkin.yml` — GitHub Actions 配置
