#!/bin/bash
# MindTask AI 一键部署脚本（Ubuntu 22.04）
set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "  MindTask AI 一键部署"
echo "=========================================="

# 1. 系统更新和基础软件
echo -e "${GREEN}[1/6] 安装系统依赖...${NC}"
apt update && apt upgrade -y
apt install -y python3 python3-pip python3-venv git nginx ufw

# 2. 创建项目目录
echo -e "${GREEN}[2/6] 创建项目目录...${NC}"
mkdir -p /opt/mindtask/templates

# 3. 配置防火墙
echo -e "${GREEN}[3/6] 配置防火墙...${NC}"
ufw allow 22/tcp
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

# 4. Python 虚拟环境
echo -e "${GREEN}[4/6] 创建虚拟环境并安装依赖...${NC}"
cd /opt/mindtask
python3 -m venv venv
source venv/bin/activate
pip install flask requests python-dotenv gunicorn

# 5. 配置文件
echo -e "${GREEN}[5/6] 创建 .env 配置...${NC}"
if [ ! -f /opt/mindtask/.env ]; then
    cat > /opt/mindtask/.env << 'EOF'
DEEPSEEK_API_KEY=your-api-key-here
DEEPSEEK_BASE_URL=https://api.deepseek.com/v1
DEEPSEEK_MODEL=deepseek-chat
EOF
    echo -e "${YELLOW}⚠️  请编辑 /opt/mindtask/.env 填入你的 API Key${NC}"
fi

# 6. systemd 服务
echo -e "${GREEN}[6/6] 配置系统服务...${NC}"
cat > /etc/systemd/system/mindtask.service << 'EOF'
[Unit]
Description=MindTask AI Web Application
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/mindtask
Environment=PATH=/opt/mindtask/venv/bin:/usr/bin
ExecStart=/opt/mindtask/venv/bin/gunicorn -w 2 -b 127.0.0.1:5000 app:app
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

# Nginx 反向代理
cat > /etc/nginx/sites-available/mindtask << 'EOF'
server {
    listen 80;
    server_name _;

    location / {
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
        proxy_read_timeout 120s;
    }
}
EOF

ln -sf /etc/nginx/sites-available/mindtask /etc/nginx/sites-enabled/mindtask
rm -f /etc/nginx/sites-enabled/default
nginx -t

echo ""
echo "=========================================="
echo -e "${GREEN}✅ 环境配置完成！${NC}"
echo ""
echo "接下来："
echo "  1. 上传项目文件到 /opt/mindtask/"
echo "  2. 编辑 /opt/mindtask/.env 填入 API Key"
echo "  3. 启动服务："
echo "     systemctl daemon-reload"
echo "     systemctl enable mindtask"
echo "     systemctl start mindtask"
echo "     systemctl restart nginx"
echo ""
echo "  访问地址: http://YOUR_SERVER_IP"
echo "=========================================="
