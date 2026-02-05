#!/bin/bash
#
# ROS2 System Diagnostic - Startup Script
#

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "==================================="
echo "ROS2 System Diagnostic"
echo "==================================="
echo ""

# Check Python version
PYTHON_CMD="python3"
if ! command -v $PYTHON_CMD &> /dev/null; then
    PYTHON_CMD="python"
fi

# Create logs directory
mkdir -p logs

# Check dependencies
echo "Checking dependencies..."
if ! $PYTHON_CMD -c "import fastapi, uvicorn" 2>/dev/null; then
    echo "Installing dependencies..."
    pip install -r requirements.txt
fi

echo ""
echo "Starting ROS2 Diagnostic Server..."
echo "Access the web interface at: http://localhost:5000"
echo ""
echo "Press Ctrl+C to stop"
echo ""

# Start the application (FastAPI with uvicorn)
$PYTHON_CMD -m uvicorn main:app --host 0.0.0.0 --port 5000 --reload
