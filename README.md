# 邮箱监控系统

本项目是一个本机运行的邮件附件处理系统：每天定时连接网易企业邮箱，按规则匹配未读邮件，下载 Excel/CSV 附件，完成模板校验后执行你在规则里配置的命令。成功处理后标记邮件已读，失败邮件保持未读并记录日志。

## 快速开始

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -e '.[dev,packaging]'
cp config.example.json config.local.json
.venv/bin/email-monitor init-db
.venv/bin/email-monitor serve
```

打开 `http://127.0.0.1:5000` 使用管理台。

## 本地配置

敏感信息会保存到 `config.local.json`，不要提交这个文件。也可以直接在管理台的「系统状态」页编辑邮箱配置；如果当前从 `config.example.json` 启动，系统会自动把真实配置写入同目录的 `config.local.json`。

```json
{
  "imap": {
    "host": "imap.qiye.163.com",
    "port": 993,
    "username": "your-email@example.com",
    "password": "your-password",
    "mailbox": "INBOX",
    "use_ssl": true
  },
  "schedule_time": "17:00",
  "timezone": "Asia/Shanghai"
}
```

## 命令

```bash
.venv/bin/email-monitor init-db
.venv/bin/email-monitor run-once
.venv/bin/email-monitor serve
.venv/bin/email-monitor serve --no-scheduler
```

管理台「状态」页的手动触发会提交后台任务并进入「任务」页；每天自动触发的巡检也会出现在同一个任务列表中，可查看任务名称、执行开始时间和状态。

## 规则执行方式

规则支持两种执行方式：

- `执行命令`：系统下载附件后运行规则里填写的命令，并提供这些环境变量：

  - `EMAIL_MONITOR_ATTACHMENT`：本次下载的附件路径
  - `EMAIL_MONITOR_SAVE_DIR`：附件保存目录
  - `EMAIL_MONITOR_RULE_NAME`：规则名称

- `整理数据`：系统把原附件保存到规则里的保存路径，再从原附件识别手机号、姓名和身份证号，整理后的文件保存到输出地址；输出列为保单号、客户姓名、客户身份证号，其中保单号来自源文件手机号字段。

整理数据在写出前会核对必填字段、手机号和身份证号格式、重复数据、输出条数，并在临时文件回读确认一致后才替换成正式输出文件。规则列表可以单独运行某一条规则。模板删除前会检查是否被规则使用，正在使用的模板不能删除。

示例命令：

```bash
python scripts/sample_processor.py --output data/result.json
```

示例脚本见 `scripts/sample_processor.py`。

## 测试

```bash
.venv/bin/python -m pytest -q
```

## macOS 打包

```bash
.venv/bin/pyinstaller email-monitor.spec
./dist/email-monitor/email-monitor serve --no-scheduler
```

Windows/Linux 需要在对应系统上执行同样的 PyInstaller 命令生成本平台可执行文件。
