# MindTask AI

> 边聊天，边整理待办。

MindTask AI 是一个基于 DeepSeek API 的智能待办管理应用。通过自然语言对话，AI 自动从你的描述中提取任务，按今天 / 本周 / 本月 / 今年四个时间维度分类管理。

![Python](https://img.shields.io/badge/Python-3.9+-blue?logo=python&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-3.x-lightgrey?logo=flask)
![License](https://img.shields.io/badge/License-MIT-green)

## 功能

- **自然语言任务提取** — 说"这周要改简历"，AI 自动创建"修改简历"并归入本周
- **多时间维度** — Today / Week / Month / Year 四维管理，任务自动分组
- **AI 智能判断** — 根据语义自动识别优先级和截止日期
- **用户系统** — 邀请码注册、密码登录、数据完全隔离
- **暗色模式** — 支持亮色 / 暗色主题，跟随系统或手动切换
- **移动端适配** — 响应式设计，手机上也能流畅使用
- **API 限流** — 每用户每分钟请求限制，防止滥用

## 技术栈

| 层 | 技术 |
|---|------|
| 后端 | Python · Flask · SQLite |
| 前端 | HTML · Tailwind CSS · Vanilla JS |
| AI | DeepSeek API (兼容 OpenAI 格式) |
| 部署 | Gunicorn · Nginx · systemd |

## 快速开始

**1. 克隆项目**

```bash
git clone https://github.com/your-username/MindTask-AI.git
cd MindTask-AI
```

**2. 创建虚拟环境**

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

**3. 配置环境变量**

```bash
cp .env.example .env
```

编辑 `.env`，填入你的 DeepSeek API Key：

```
DEEPSEEK_API_KEY=sk-xxxxxxxxxxxxxxxx
```

**4. 启动**

```bash
python app.py
```

访问 http://localhost:5000 。首次启动会自动生成邀请码，在终端日志中查看。

## 服务器部署

项目提供了部署脚本，适用于 Ubuntu 22.04：

```bash
# 在服务器上运行一键部署（配置环境 + Nginx + systemd）
sudo bash deploy.sh

# 在本地运行，将代码更新到服务器
bash update_all.sh
```

部署前请修改脚本中的 `YOUR_SERVER_IP` 为你的服务器地址。

## 项目结构

```
├── app.py              # 后端主程序
├── requirements.txt    # Python 依赖
├── .env.example        # 环境变量模板
├── templates/
│   ├── index.html      # 主页面（任务管理）
│   └── login.html      # 登录 / 注册页面
├── deploy.sh           # 服务器一键部署脚本
└── update_all.sh       # 代码更新部署脚本
```

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `DEEPSEEK_API_KEY` | DeepSeek API 密钥 | — (必填) |
| `DEEPSEEK_BASE_URL` | API 地址 | `https://api.deepseek.com/v1` |
| `DEEPSEEK_MODEL` | 模型名称 | `deepseek-chat` |
| `SECRET_KEY` | Flask Session 密钥 | 自动生成 |
| `AI_RATE_LIMIT` | 每用户每分钟 AI 调用上限 | `10` |

> 兼容所有 OpenAI 格式的 API 服务，修改 `DEEPSEEK_BASE_URL` 即可切换。

## 使用说明

> 前端页面样式：https://wxl77.github.io/

1. 第一个注册的用户自动成为**管理员**，拥有邀请码管理权限
2. 在底部输入框用自然语言描述任务，AI 会自动解析并添加到对应的时间维度
3. 支持通过 AI 对话完成和删除任务

