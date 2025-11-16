#!/bin/bash
set -e

echo "=========================================="
echo "   Updating all submodules (recursive)"
echo "=========================================="
echo ""

# Step 1 — Sync .gitmodules with local submodule config
echo "[1/4] Syncing .gitmodules ..."
git submodule sync --recursive

echo ""
echo "[2/4] Fetching latest submodule changes ..."
git submodule update --init --recursive --remote

echo ""
echo "[3/4] Showing submodule status ..."
git submodule status --recursive

echo ""
echo "[4/4] Checking if any submodule pointer changed ..."
CHANGED=$(git status --porcelain | grep '^ M ' || true)

if [ -n "$CHANGED" ]; then
    echo ""
    echo "=========================================="
    echo " Submodule pointer(s) changed!"
    echo " You likely need to commit them:"
    echo ""
    echo "   git add <submodule_path>"
    echo "   git commit -m \"Update submodule pointers\""
    echo "   git push"
    echo "=========================================="
else
    echo "No submodule pointer changes detected."
fi

echo ""
echo "Done."
#!/bin/bash
set -e

echo "=========================================="
echo "   Updating all submodules (recursive)"
echo "=========================================="
echo ""

# Step 1 — Sync .gitmodules with local submodule config
echo "[1/4] Syncing .gitmodules ..."
git submodule sync --recursive

echo ""
echo "[2/4] Fetching latest submodule changes ..."
git submodule update --init --recursive --remote

echo ""
echo "[3/4] Showing submodule status ..."
git submodule status --recursive

echo ""
echo "[4/4] Checking if any submodule pointer changed ..."
CHANGED=$(git status --porcelain | grep '^ M ' || true)

if [ -n "$CHANGED" ]; then
    echo ""
    echo "=========================================="
    echo " Submodule pointer(s) changed!"
    echo " You likely need to commit them:"
    echo ""
    echo "   git add <submodule_path>"
    echo "   git commit -m \"Update submodule pointers\""
    echo "   git push"
    echo "=========================================="
else
    echo "No submodule pointer changes detected."
fi

echo ""
echo "Done."
