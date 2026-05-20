# iKuuu Checkin

iKuuu VPN 每日自动签到，GitHub Actions 定时执行。

## 工作流程

**两阶段设计：**

1. **Cookie 预检** — 用缓存的 cookie 直接 requests 签到（快，不启动浏览器）
   - 多账号线程池并行执行
   - 网络异常时自动重试 1 次
   - Cookie 过期自动清理

2. **Playwright 浏览器登录**（cookie 无效时）— 共享浏览器，async 并行登录
   - 极验 Geetest V4 验证码处理
   - 支持多个故障域名切换
   - 登录成功自动保存 cookie，下次跳过浏览器登录
   - 登录失败自动切换备用域名

## 环境变量

| 变量 | 说明 |
|------|------|
| `ACCOUNTS` | 账号密码，每行 `邮箱:密码`，多账户换行分隔 |
| `PLAYWRIGHT_HEADLESS` | 默认 `1`（无头），设为 `0` 调试 |

## GitHub Actions

每天 UTC 16:00（北京时间 00:00）自动执行。

需配置 Secrets：`ACCOUNTS`

创建 Issue #1 可在全部签到失败时接收通知。

## 本地运行

```bash
pip install -r requirements.txt
playwright install chromium

$env:ACCOUNTS="user@example.com:password"
python playwright_checkin.py
```

## 文件

- `playwright_checkin.py` — 主脚本
- `.github/workflows/checkin.yml` — GitHub Actions 配置
- `requirements.txt` — Python 依赖
- `ikuuu_cookies.json` — Cookie 缓存（自动维护）
