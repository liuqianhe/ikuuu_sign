# iKuuu Checkin — Playwright 方案

真实浏览器模拟签到，绕过 GeeTest 验证码，无需付费的验证码服务。

- 并行登录，多账号无等待
- Cookie 缓存，有效期内秒签
- 失败时自动切换备用域名

## 环境变量

| 变量 | 说明 |
|------|------|
| `ACCOUNTS` | 账号密码，每行 `邮箱:密码`，多账户用换行分隔 |
| `PLAYWRIGHT_HEADLESS` | 默认 `1`（无头），设为 `0` 调试 |

## 本地运行

```bash
pip install -r requirements.txt
playwright install chromium

export ACCOUNTS="user@example.com:password"
python playwright_checkin.py
```

## GitHub Actions

Fork → Settings → Secrets → 添加 `ACCOUNTS` → 每天 UTC 16:10（北京时间 00:10）自动执行。

创建 Issue #1 可接收失败通知。

## 文件

- `playwright_checkin.py` — 主脚本
- `.github/workflows/checkin.yml` — GitHub Actions 配置
