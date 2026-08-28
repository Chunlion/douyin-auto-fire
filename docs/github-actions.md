# GitHub Actions 使用教程

本教程介绍如何使用 **GitHub Actions** 运行 `douyin-auto-fire`。

使用这种方式不需要自己准备服务器，也不需要电脑每天开机。配置完成后，GitHub Actions 会按照设定时间自动运行任务。

> 建议第一次只配置 **1 个抖音账号 + 1 个好友 + 1 条文字消息**。确认正常运行后，再添加其他好友、原生表情、随机消息或多账号。

---

## 1. Fork 项目

打开项目仓库：

**https://github.com/unmev/douyin-auto-fire**

点击右上角 **Fork**，将项目 Fork 到自己的 GitHub 账号。

![Fork 项目](https://img.908988.xyz/file/教程/douyin-auto-fire/DKPd0GVi.webp)

Fork 完成后，后面的所有操作都在 **你自己 Fork 出来的仓库** 中进行。

---

## 2. 启用 GitHub Actions

进入自己 Fork 后的仓库，点击顶部的 **Actions**。

如果 GitHub 提示 Fork 仓库的 Workflow 被禁用，点击启用工作流。

启用以后应该可以看到：

```text
Send Douyin Messages
```

这就是项目每天自动运行使用的工作流。

---

## 3. 获取抖音 Cookie

程序需要 Cookie 才能保持抖音登录状态。

### 3.1 登录抖音网页版

使用电脑浏览器打开：

**https://www.douyin.com/**

登录自己的抖音账号，并确认能够正常进入私信页面。

### 3.2 安装 Cookie-Editor

推荐使用浏览器扩展 **Cookie-Editor**：

**https://chromewebstore.google.com/detail/hlkenndednhfkekhgcdicdfddnkalmdm**

安装完成后，回到已经登录抖音的页面并打开 Cookie-Editor。

![打开 Cookie-Editor](https://img.908988.xyz/file/教程/douyin-auto-fire/STZqIxDn.webp)

### 3.3 导出 Cookie

点击 Cookie-Editor 的导出功能，导出格式选择 **JSON**。

![导出 Cookie](https://img.908988.xyz/file/教程/douyin-auto-fire/1rilVYmK.webp)

然后复制完整的 JSON 内容。

![复制 Cookie JSON](https://img.908988.xyz/file/教程/douyin-auto-fire/QKQHfndn.webp)

正确格式大致如下：

```json
[
  {
    "name": "xxx",
    "value": "xxx",
    "domain": ".douyin.com",
    "path": "/"
  }
]
```

请注意：

- 必须复制完整的 `[ ... ]` JSON 数组。
- 不要使用 `name=value; name=value;` 形式。
- 不要删除 Cookie 中的字段。
- 不要把 Cookie 提交到 GitHub 仓库。

> ⚠️ Cookie 相当于账号登录凭证，请不要发送给其他人，也不要公开到 Issue、日志或截图中。

---

## 4. 生成发送配置

除了 Cookie，程序还需要知道给谁发送、发送什么内容以及消息发送间隔。

如果不想自己写 JSON，可以直接使用配置生成器：

**https://douyin-config.pages.dev/**

生成完成后复制网站生成的完整 JSON。

一个最简单的配置例如：

```json
{
  "friends": ["好友昵称"],
  "messages": [
    {"type": "text", "value": "续火花 ✨"}
  ],
  "send_interval_seconds": {
    "min": 3,
    "max": 8
  },
  "prevent_duplicates": false
}
```

第一次使用建议先只配置：

```text
1 个好友 + 1 条文字消息
```

先把最基础的流程跑通，再增加其他功能。

---

## 5. 添加 GitHub Secrets

进入自己 Fork 的仓库，依次打开：

```text
Settings
↓
Secrets and variables
↓
Actions
↓
New repository secret
```

![进入 Secrets](https://img.908988.xyz/file/教程/douyin-auto-fire/aiPBHuxJ.webp)

![创建 Secret](https://img.908988.xyz/file/教程/douyin-auto-fire/BKtXckyQ.webp)

第一次使用需要添加发送配置，以及一种登录凭证。完整浏览器状态通常比单独 Cookie 更稳定。

| Secret | 内容 | 必须 |
| --- | --- | --- |
| `DOUYIN_STORAGE_STATE` | `scripts/login.py` 生成的完整 `storage-state.json` | 与 Cookie 二选一 |
| `DOUYIN_STORAGE_STATE_GZIP_BASE64` | gzip 压缩并 Base64 编码的 Storage State | 文件超过 48 KB 时使用 |
| `DOUYIN_COOKIE` | Cookie-Editor 导出的完整 Cookie JSON | 与 Storage State 二选一 |
| `DOUYIN_CONFIG` | 配置生成器生成的完整配置 JSON | ✅ |

### 5.1 添加登录凭证

点击 **New repository secret**。

推荐先在本地运行登录脚本：

```powershell
python scripts/login.py
```

扫码登录后，把生成的 `storage-state.json` 完整内容保存为：

```text
DOUYIN_STORAGE_STATE
```

如果文件超过 GitHub Secret 的 48 KB 上限，压缩并编码后保存为 `DOUYIN_STORAGE_STATE_GZIP_BASE64`。工作流会自动解压。

也可以继续使用 Cookie。此时 Name 填：

```text
DOUYIN_COOKIE
```

Secret 粘贴刚刚导出的完整 Cookie JSON，然后保存。

### 5.2 添加 `DOUYIN_CONFIG`

再次点击 **New repository secret**。

Name 填：

```text
DOUYIN_CONFIG
```

Secret 粘贴刚刚生成的完整配置 JSON，然后保存。

配置完成后应该存在 `DOUYIN_CONFIG`，以及一种登录凭证：

```text
DOUYIN_CONFIG
DOUYIN_STORAGE_STATE 或 DOUYIN_COOKIE
```

GitHub 保存 Secret 后不会再次显示具体内容，这是正常现象。

---

## 6. 第一次运行：Dry Run

配置完成后，不建议第一次就直接真实发送。

项目提供了 **Dry Run** 模式，用来检查：

- 登录凭证是否有效；
- 是否能够正常登录抖音；
- 是否能够找到目标好友；
- 配置是否正确。

Dry Run **不会真正发送消息**。

进入：

```text
Actions
↓
Send Douyin Messages
↓
Run workflow
```

第一次运行时，将 `dry_run` 开启（即 `true`），然后点击 **Run workflow**。

![运行 GitHub Actions](https://img.908988.xyz/file/教程/douyin-auto-fire/NLFF8g94.webp)

如果最后显示绿色的 `✓`，说明本次运行成功。

如果失败，点击本次 Workflow Run，进入：

```text
send
↓
Run
```

查看具体错误日志。不要只看最下面的 `Process completed with exit code 1`，真正的报错通常在它前面。

---

## 7. 测试真实发送

Dry Run 成功后，再手动运行一次工作流。

这一次关闭 `dry_run`，也就是：

```text
dry_run = false
```

然后运行。

这一次程序会真正向好友发送消息。

第一次真实发送仍建议只保留 **1 个测试好友**，确认好友、消息和发送结果都正确以后，再增加其他好友。

---

## 8. 每天自动运行

项目已经自带 GitHub Actions 定时任务。

工作流文件位于：

```text
.github/workflows/send.yml
```

默认每天北京时间 **05:24** 开始执行。工作流每 15 分钟检查一次；GitHub 延迟或丢失单次触发后，后续检查会自动补跑。当天成功后不再重复发送。

定时触发会直接进行真实发送，不会自动进入 Dry Run。

### 修改运行时间

打开仓库 `Settings` → `Secrets and variables` → `Actions` → `Variables`，设置：

- `DOUYIN_SCHEDULE_TIME`：`HH:MM`，例如 `08:30`
- `DOUYIN_SCHEDULE_TIMEZONE`：IANA 时区，默认 `Asia/Shanghai`

修改后无需编辑工作流。实际启动时间可能晚于设定时间，但后续检查会持续补偿。

---

## 9. Cookie 失效怎么办？

Cookie 并不是永久有效。

如果 Actions 日志提示登录失效、需要重新登录、安全验证或 Cookie 无效：

1. 使用浏览器重新登录抖音网页版；
2. 用 Cookie-Editor 重新导出 Cookie JSON；
3. 打开仓库 `Settings`；
4. 进入 `Secrets and variables` → `Actions`；
5. 更新 `DOUYIN_COOKIE`；
6. 保存后手动执行一次 `dry_run = true`。

Dry Run 成功后即可继续正常使用。

---

## 10. 任务通知（可选）

可以添加以下 Secret 接收任务结果：

| Secret | 内容 |
| --- | --- |
| `DINGTALK_WEBHOOK` | 钉钉机器人 Webhook |
| `DINGTALK_SECRET` | 钉钉机器人 Secret |
| `WECOM_WEBHOOK` | 企业微信群机器人 Webhook |

钉钉的两个 Secret 必须同时配置。企业微信只需配置 `WECOM_WEBHOOK`，两种通知可以同时启用。

Webhook 属于凭证，不要写入配置文件或公开内容。

---

## 11. 多账号（可选）

项目当前最多支持 **5 个抖音账号**。

第一次使用不建议直接配置多账号。先确保单账号模式下的：

```text
DOUYIN_COOKIE
DOUYIN_CONFIG
```

能够正常运行。

之后可以按照账号添加：

```text
DOUYIN_COOKIE_ACCOUNT1
DOUYIN_CONFIG_ACCOUNT1

DOUYIN_COOKIE_ACCOUNT2
DOUYIN_CONFIG_ACCOUNT2

DOUYIN_COOKIE_ACCOUNT3
DOUYIN_CONFIG_ACCOUNT3
```

以此类推，最多到 `ACCOUNT5`。

每个账号的 Cookie 和 Config 必须成对配置，不能只添加其中一个。

### 老用户增加第二个账号

如果以前一直使用：

```text
DOUYIN_COOKIE
DOUYIN_CONFIG
```

不需要删除原来的配置。

可以直接增加：

```text
DOUYIN_COOKIE_ACCOUNT2
DOUYIN_CONFIG_ACCOUNT2
```

原来的 `DOUYIN_COOKIE` / `DOUYIN_CONFIG` 会继续作为第一个账号使用。

---

## 12. 运行失败后的诊断文件

如果 GitHub Actions 运行失败，项目默认只上传已脱敏的诊断文件：

```text
run.log
result.json
```

进入失败的 Workflow 页面，在页面底部找到 **Artifacts** 即可下载。

失败诊断 Artifact 默认保留 **3 天**。

截图和 Playwright Trace 包含页面、DOM 和网络信息，公开仓库默认不上传。确需上传时，在仓库 **Settings → Secrets and variables → Actions → Variables** 中添加：

```text
UPLOAD_SENSITIVE_DIAGNOSTICS=true
```

启用后，失败任务还会上传：

```text
screenshots/
traces/
```

诊断文件可以帮助判断：

- Cookie 是否失效；
- 是否出现安全验证；
- 好友是否没有找到；
- 页面结构是否变化；
- Playwright 在哪一步失败。

> ⚠️ 截图和 Trace 可能包含聊天内容、登录状态或请求数据。仅在排错时临时开启，下载后删除对应 Artifact，并移除变量。

---

## 第一次使用推荐流程

```text
Fork 项目
    ↓
启用 Actions
    ↓
登录抖音
    ↓
导出 Cookie
    ↓
生成发送配置
    ↓
添加 DOUYIN_COOKIE
    ↓
添加 DOUYIN_CONFIG
    ↓
开启 Dry Run
    ↓
确认运行成功
    ↓
关闭 Dry Run
    ↓
测试真实发送
    ↓
确认成功
    ↓
等待每天自动运行
```

第一次不要同时配置多账号、多个好友、原生表情、随机消息和任务通知。

先把最基础的流程跑通，这样即使出现问题，也更容易判断是哪一步出了问题。

---

## 返回项目主页

👉 [返回 douyin-auto-fire](../README.md)
