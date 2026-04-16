# 当前方案说明（脱敏版）

这份文档描述的是当前这套方案的通用版本，不包含任何现网私密信息。

当前链路是：

**外部系统 -> 反向代理 -> 本机 FastAPI 服务 -> 落盘 JSON -> Feishu 双通道通知**

其中：

- `FEISHU_WEBHOOK`：合法请求摘要
- `FEISHU_REJECTED_WEBHOOK`：所有请求的原始日志

说明：

- 第二个变量保留了历史名字
- 但在当前设计里，它承担的是“原始日志通道”

## 1. 当前服务行为

服务收到请求后会：

1. 读取完整 query string 和请求体
2. 归一化 `sequence`、`target`、`reply_email`
3. 把请求完整写入本地 JSON
4. 对 `sequence` 和可选 token 做校验
5. 合法请求把摘要推送到 `FEISHU_WEBHOOK`
6. 所有请求把原始日志推送到 `FEISHU_REJECTED_WEBHOOK`
7. 向调用方返回成功或失败说明

## 2. 当前支持的请求格式

### 根路径 query

```text
https://your.example.com/?sequence=AFCDELMKDTKTW&email=submitter@example.org&target=ExampleTarget
```

### `/submit`

```text
https://your.example.com/submit?sequence=AFCDELMKDTKTW&email=submitter@example.org&target=ExampleTarget
```

### 大写参数

```text
https://your.example.com/?SEQUENCE=AFCDELMKDTKTW&REPLY_EMAIL=submitter@example.org&TARGET=ExampleTarget
```

### 表单 POST

```bash
curl -X POST "https://your.example.com/" \
  -d "SEQUENCE=AFCDELMKDTKTW" \
  -d "TARGET=ExampleTarget" \
  -d "REPLY_EMAIL=submitter@example.org"
```

### 历史错误片段

下面这种少写了 `=` 的旧格式也会兼容：

```text
https://your.example.com/?sequence=AFCIDELMKDTKTW&email=submitter@example.org&targetTargetName&
```

会被理解为：

```text
https://your.example.com/?sequence=AFCIDELMKDTKTW&email=submitter@example.org&target=TargetName
```

### FASTA 真换行

```text
>ExampleTarget|
GCCCGGAUAGCU...
```

### FASTA 字面量 `\n` / `\r\n`

以下这种历史输入现在也兼容：

```text
>ExampleTarget|\nGCCCGGAUAGCU...
```

以及：

```text
>ExampleTarget|\r\nGCCCGGAUAGCU...
```

服务会先把字面量换行转换成真实换行，再走 FASTA 归一化流程。

## 3. 当前返回格式

### `GET` 成功

```text
OK
Request accepted.
Received at (UTC): ...
Target: ...
Sequence length: ...
If there are any questions, contact: support@example.org
```

### `GET` 失败

```text
Request rejected.
Reason: Missing sequence.
Received at (UTC): ...
Target: ...
If there are any questions, contact: support@example.org
```

### `POST` 成功

返回结构化 JSON。

### `POST` 失败

返回结构化 JSON，并明确给出 `reason`。

## 4. 当前首页行为

在当前部署模型里：

- 干净访问 `/` 显示静态 landing page
- 带 query 的 `GET /?...` 交给 FastAPI
- `POST /` 交给 FastAPI
- `/submit` 交给 FastAPI

首页模板文件：

- `deploy/example-landing-page.html`

## 5. 当前关键文件

- `query_mailer/app.py`
- `query_mailer/core.py`
- `query_mailer/mailer.py`
- `query_mailer/replay_failed.py`
- `deploy/example-nginx.conf`
- `deploy/example-landing-page.html`

## 6. 一句话总结

当前这套方案的关键点是：

- 请求先落盘
- 合法摘要和原始日志分两条 webhook
- `GET`/`POST` 返回不同但清晰的结果
- 兼容单行序列、FASTA、字面量 `\n` / `\r\n` 和历史错误片段
