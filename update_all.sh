#!/bin/bash
# MindTask AI 更新部署脚本（本地运行）
set -e

SERVER="user@YOUR_SERVER_IP"

echo "📦 上传文件到服务器..."
scp ./app.py ${SERVER}:/tmp/app.py
scp ./requirements.txt ${SERVER}:/tmp/requirements.txt
scp ./templates/index.html ${SERVER}:/tmp/index.html
scp ./templates/login.html ${SERVER}:/tmp/login.html

echo "🔧 部署中..."
ssh ${SERVER} << 'ENDSSH'
cp /opt/mindtask/app.py /opt/mindtask/app.py.bak 2>/dev/null || true

cp /tmp/app.py /opt/mindtask/app.py
cp /tmp/requirements.txt /opt/mindtask/requirements.txt
cp /tmp/index.html /opt/mindtask/templates/index.html
cp /tmp/login.html /opt/mindtask/templates/login.html

cd /opt/mindtask
source venv/bin/activate
pip install -r requirements.txt -q

if ! grep -q "SECRET_KEY" /opt/mindtask/.env 2>/dev/null; then
    echo "" >> /opt/mindtask/.env
    echo "SECRET_KEY=$(python3 -c 'import secrets; print(secrets.token_hex(32))')" >> /opt/mindtask/.env
fi

systemctl restart mindtask
sleep 2

if systemctl is-active --quiet mindtask; then
    echo "✅ 服务启动成功！"
else
    echo "❌ 启动失败，查看日志："
    journalctl -u mindtask --no-pager -n 20
fi
ENDSSH

echo ""
echo "✅ 部署完成！"
echo "   访问 http://YOUR_SERVER_IP"
echo "   查看邀请码: ssh ${SERVER} 'journalctl -u mindtask --no-pager -n 30 | grep -A 20 邀请码'"
