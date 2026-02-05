#!/bin/bash
# 安装 ros2-diagnostic 服务并设置开机自启

set -e

SERVICE_NAME="ros2-diagnostic"
SERVICE_FILE="/home/eagrumo/mss_lecture/config/${SERVICE_NAME}.service"
SYSTEMD_DIR="/etc/systemd/system"

echo "=== 安装 ${SERVICE_NAME} 服务 ==="

# 检查服务文件是否存在
if [ ! -f "$SERVICE_FILE" ]; then
    echo "错误: 服务文件不存在: $SERVICE_FILE"
    exit 1
fi

# 检查 Python 主程序是否存在
MAIN_PY="/home/eagrumo/mss_lecture/ros2_diagnostic/main.py"
if [ ! -f "$MAIN_PY" ]; then
    echo "错误: 主程序不存在: $MAIN_PY"
    exit 1
fi

# 停止已存在的服务（如果正在运行）
if systemctl is-active --quiet "$SERVICE_NAME"; then
    echo "停止正在运行的服务..."
    sudo systemctl stop "$SERVICE_NAME"
fi

# 复制服务文件到 systemd 目录
echo "安装服务文件到 $SYSTEMD_DIR..."
sudo cp "$SERVICE_FILE" "$SYSTEMD_DIR/"

# 重新加载 systemd 配置
echo "重新加载 systemd 配置..."
sudo systemctl daemon-reload

# 启用开机自启
echo "启用 ${SERVICE_NAME} 开机自启..."
sudo systemctl enable "$SERVICE_NAME"

# 启动服务
echo "启动 ${SERVICE_NAME} 服务..."
sudo systemctl start "$SERVICE_NAME"

# 等待一下让服务启动
sleep 2

# 显示服务状态
echo ""
echo "=== 服务状态 ==="
sudo systemctl status "$SERVICE_NAME" --no-pager

echo ""
echo "=== 安装完成 ==="
echo "服务已设置为开机自启"
echo ""
echo "常用命令："
echo "  查看状态: sudo systemctl status $SERVICE_NAME"
echo "  启动服务: sudo systemctl start $SERVICE_NAME"
echo "  停止服务: sudo systemctl stop $SERVICE_NAME"
echo "  重启服务: sudo systemctl restart $SERVICE_NAME"
echo "  查看日志: sudo journalctl -u $SERVICE_NAME -f"
