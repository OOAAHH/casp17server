# Query Mailer 部署文档（脱敏版）

这份文档用于把 `query-mailer` 部署到另一台服务器。

本文档是通用示例，不包含现网目录、现网端口、现网域名或现网证书路径。

## 1. 推荐链路

```text
外部请求 -> https://your.example.com/ -> nginx -> __APP_BIND_HOST__:__APP_PORT__ -> FastAPI -> JSON 落盘 -> Feishu 摘要/原始日志双通道
```

其中：

- `FEISHU_WEBHOOK`：合法请求摘要
- `FEISHU_REJECTED_WEBHOOK`：所有请求的原始日志

## 2. 建议目录

```text
__APP_ROOT__/
  app/
    query_mailer/
    deploy/
    requirements.txt
    README.md
    CURRENT_SETUP_zh.md
    DEPLOY_ANOTHER_SERVER_zh.md
    PROBLEMS_AND_FIXES_zh.md
  venv/
```

请求记录目录：

```text
__DATA_DIR__
```

## 3. 环境变量示例

`__ENV_FILE__`

```env
FEISHU_WEBHOOK=https://hooks.example.invalid/accepted-summary
FEISHU_REJECTED_WEBHOOK=https://hooks.example.invalid/raw-request-log
FEISHU_KEYWORD=
SECRET_TOKEN=
SUPPORT_CONTACT_EMAIL=support@example.org
DATA_DIR=__DATA_DIR__
MAX_SEQUENCE_LENGTH=10000
WEBHOOK_TIMEOUT_SECONDS=10
```

## 4. systemd 示例

`deploy/example-query-mailer.service`

```ini
[Unit]
Description=Query Mailer FastAPI Service
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=__SERVICE_USER__
Group=__SERVICE_GROUP__
WorkingDirectory=__APP_ROOT__/app
EnvironmentFile=__ENV_FILE__
UMask=0077
ExecStart=__VENV_DIR__/bin/uvicorn query_mailer.app:app --host __APP_BIND_HOST__ --port __APP_PORT__
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

`deploy/example-query-mailer-replay.service`

```ini
[Unit]
Description=Replay failed query-mailer notifications
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=__SERVICE_USER__
Group=__SERVICE_GROUP__
WorkingDirectory=__APP_ROOT__/app
EnvironmentFile=__ENV_FILE__
UMask=0077
ExecStart=__VENV_DIR__/bin/python -m query_mailer.replay_failed --limit 100
```

`deploy/example-query-mailer-replay.timer`

```ini
[Unit]
Description=Replay failed query-mailer notifications every 5 minutes

[Timer]
OnBootSec=2min
OnUnitActiveSec=5min
Unit=example-query-mailer-replay.service

[Install]
WantedBy=timers.target
```

## 5. nginx 反代示例

示例文件：

- `deploy/example-nginx.conf`
- `deploy/nginx-query-mailer-location.conf`

核心思路是：

- 干净访问 `/` 返回静态首页
- `/submit` 直接转发给 FastAPI
- 带 query 的 `GET /?...` 也转发给 FastAPI
- `POST /` 转发给 FastAPI
- 反向代理始终指向 `__APP_BIND_HOST__:__APP_PORT__`

## 6. 验证项

- `curl http://localhost:__DEV_PORT__/healthz` 返回 `{"status":"ok"}`
- 合法请求后：
  - `summary_status=sent`
  - `raw_status=sent`
- 非法请求后：
  - `summary_status=skipped`
  - `raw_status=sent`

## 7. 当前兼容行为

当前服务兼容：

- 单行序列
- FASTA 真换行
- FASTA 字面量 `\n`
- FASTA 字面量 `\r\n`
- 大写参数名
- 历史错误片段 `targetTargetName`

## 8. 当前首页模板

如果要保留 landing page，可以使用：

- `deploy/example-landing-page.html`

它保留了这些前端结构：

- 玻璃风格首页
- 轻微鼠标/滚动视差
- 资源按钮 hover 强调
- 同域延迟显示

## 9. 一句话总结

通用部署方式就是：

- `nginx + __APP_BIND_HOST__:__APP_PORT__`
- 同一域名同时承载静态首页和提交接口
- 合法摘要与原始日志分走两条 Feishu webhook
