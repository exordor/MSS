#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# YAML Configuration Loading
# =============================================================================

# Script directory
_logging_lib_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_logging_config_loader="${_logging_lib_dir}/load_logging_config.py"

# Load logging configuration from YAML file
# Usage: _load_logging_config REPO_ROOT [PROFILE_NAME]
_load_logging_config() {
  local repo_root="$1"
  local requested_profile="${2:-}"

  # Determine config file path
  local default_config="${repo_root}/config/logging/logging.yaml"
  local local_config="${repo_root}/config/logging/local.yaml"
  local active_config="${default_config}"

  # Check for custom config via LOGGING_CONFIG env var
  if [[ -n "${LOGGING_CONFIG:-}" && -f "${LOGGING_CONFIG}" ]]; then
    active_config="${LOGGING_CONFIG}"
  elif [[ -f "${local_config}" ]]; then
    active_config="${local_config}"
  fi

  # Load configuration using Python helper
  if [[ -x "${_logging_config_loader}" ]] || command -v python3 >/dev/null 2>&1; then
    if [[ -x "${_logging_config_loader}" ]]; then
      # Use the helper script
      # Only pass profile argument if it's not empty (let Python script use LOG_PROFILE env var)
      if [[ -n "${requested_profile}" ]]; then
        eval "$(python3 "${_logging_config_loader}" "${active_config}" "${requested_profile}" 2>/dev/null)" || true
      else
        eval "$(python3 "${_logging_config_loader}" "${active_config}" 2>/dev/null)" || true
      fi
    else
      # Fallback: try python3 with inline script
      if [[ -n "${requested_profile}" ]]; then
        python3 -c "
import sys
sys.path.insert(0, '${_logging_lib_dir}')
exec(open('${_logging_config_loader}').read())
" "${active_config}" "${requested_profile}" 2>/dev/null || true
      else
        python3 -c "
import sys
sys.path.insert(0, '${_logging_lib_dir}')
exec(open('${_logging_config_loader}').read())
" "${active_config}" 2>/dev/null || true
      fi
    fi
  fi

  # Set defaults for any unset values (backward compatibility)
  export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
  export RCUTILS_LOGGING_USE_STDOUT="${RCUTILS_LOGGING_USE_STDOUT:-1}"
  export RCUTILS_COLORIZED_OUTPUT="${RCUTILS_COLORIZED_OUTPUT:-0}"
  export RCUTILS_LOGGING_BUFFERED_STREAM="${RCUTILS_LOGGING_BUFFERED_STREAM:-0}"
  if [[ -z "${RCUTILS_CONSOLE_OUTPUT_FORMAT:-}" ]]; then
    export RCUTILS_CONSOLE_OUTPUT_FORMAT='[{time}] [{severity}] [{name}] {message}'
  fi
}

# Show current logging configuration
# Usage: show_logging_config
show_logging_config() {
  cat <<EOF
========================================
Logging Configuration
========================================
Profile:        ${LOGGING_ACTIVE_PROFILE:-default}
Config File:    ${LOGGING_CONFIG_FILE:-none}

Environment Variables:
  PYTHONUNBUFFERED              = ${PYTHONUNBUFFERED:-unset}
  RCUTILS_LOGGING_USE_STDOUT    = ${RCUTILS_LOGGING_USE_STDOUT:-unset}
  RCUTILS_COLORIZED_OUTPUT      = ${RCUTILS_COLORIZED_OUTPUT:-unset}
  RCUTILS_CONSOLE_OUTPUT_FORMAT = ${RCUTILS_CONSOLE_OUTPUT_FORMAT:-unset}
  RCUTILS_LOGGING_BUFFERED_STREAM = ${RCUTILS_LOGGING_BUFFERED_STREAM:-unset}
  RCUTILS_LOG_LEVEL             = ${RCUTILS_LOG_LEVEL:-unset}

Directories:
  LOG_ROOT    = ${LOG_ROOT:-unset}
  ROS_LOG_DIR = ${ROS_LOG_DIR:-unset}
  APP_LOG_DIR = ${APP_LOG_DIR:-unset}
========================================
EOF
}

# =============================================================================
# Logging Initialization
# =============================================================================

init_ros2_logging() {
  local repo_root="$1"
  local requested_profile="${2:-}"
  local run_id="${ROS2_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"

  LOG_ROOT="${repo_root}/logs/${run_id}"
  ROS_LOG_DIR="${LOG_ROOT}/ros"
  APP_LOG_DIR="${LOG_ROOT}/app"
  META_LOG_DIR="${LOG_ROOT}/meta"

  mkdir -p "${ROS_LOG_DIR}" "${APP_LOG_DIR}" "${META_LOG_DIR}"

  export RUN_ID="${run_id}"
  export LOG_ROOT
  export ROS_LOG_DIR
  export APP_LOG_DIR
  export META_LOG_DIR

  # Try to load YAML configuration
  local yaml_config="${repo_root}/config/logging/logging.yaml"
  if [[ -f "$yaml_config" ]] || [[ -n "${LOGGING_CONFIG:-}" ]]; then
    _load_logging_config "$repo_root" "$requested_profile"
  else
    # Fallback to original hardcoded defaults (backward compatibility)
    export PYTHONUNBUFFERED="${PYTHONUNBUFFERED:-1}"
    export RCUTILS_LOGGING_USE_STDOUT="${RCUTILS_LOGGING_USE_STDOUT:-1}"
    export RCUTILS_COLORIZED_OUTPUT="${RCUTILS_COLORIZED_OUTPUT:-0}"
    if [[ -z "${RCUTILS_CONSOLE_OUTPUT_FORMAT:-}" ]]; then
      export RCUTILS_CONSOLE_OUTPUT_FORMAT='[{time}] [{severity}] [{name}] {message}'
    fi
  fi
}

write_runtime_info() {
  local launcher="${1:-}"
  cat > "${META_LOG_DIR}/runtime.json" <<EOF
{
  "start_time": "$(date -Iseconds)",
  "run_id": "${RUN_ID}",
  "launcher": "${launcher}",
  "user": "$(whoami)",
  "hostname": "$(hostname)",
  "ros_distro": "${ROS_DISTRO:-humble}",
  "ros_domain_id": "${ROS_DOMAIN_ID:-}",
  "log_root": "${LOG_ROOT}",
  "ros_log_dir": "${ROS_LOG_DIR}"
}
EOF
}

start_ros2_healthcheck() {
  local label="${1:-run}"
  shift || true
  local nodes=("$@")

  (
    set +e
    sleep "${ROS2_HEALTHCHECK_DELAY:-5}"
    if ! command -v ros2 >/dev/null 2>&1; then
      echo "[WARN] [healthcheck:${label}] ros2 CLI not available; skipping node check."
      exit 0
    fi
    local node_list
    node_list="$(ros2 node list 2>/dev/null || true)"
    for node in "${nodes[@]}"; do
      if ! grep -qx "/${node}" <<<"${node_list}"; then
        echo "[WARN] [healthcheck:${label}] missing node: /${node}"
      fi
    done
    if [[ -n "${ROS_LOG_DIR:-}" ]]; then
      for node in "${nodes[@]}"; do
        local f size
        f="$(ls -t "${ROS_LOG_DIR}/${node}_"*.log 2>/dev/null | head -1)"
        if [[ -z "${f}" ]]; then
          echo "[WARN] [healthcheck:${label}] no log file for ${node} under ${ROS_LOG_DIR}"
          continue
        fi
        size="$(stat -c%s "${f}" 2>/dev/null || stat -f%z "${f}" 2>/dev/null || echo 0)"
        if [[ "${size}" -eq 0 ]]; then
          echo "[WARN] [healthcheck:${label}] log file empty for ${node}: ${f}"
        fi
      done
    fi
  ) &
}

# =============================================================================
# Node Log Verification
# =============================================================================

# Verify that a node's log file has been created and contains content
# Usage: verify_node_log NODE_NAME [TIMEOUT_SEC]
verify_node_log() {
  local node_name="$1"
  local timeout_sec="${2:-5}"

  local log_dir="${ROS_LOG_DIR}"
  local expected_file="${log_dir}/${node_name}/stdout.log"

  echo "[verify_node_log] Checking log file: ${expected_file}"

  # Wait for log file to be created
  local count=0
  while [[ ! -f "${expected_file}" ]] && [[ $count -lt $timeout_sec ]]; do
    sleep 1
    count=$((count + 1))
  done

  if [[ ! -f "${expected_file}" ]]; then
    echo "[WARNING] Log file not created: ${expected_file}"
    return 1
  fi

  # Check if file has content
  if [[ ! -s "${expected_file}" ]]; then
    echo "[WARNING] Log file is empty: ${expected_file}"
    return 1
  fi

  local size
  size=$(wc -c < "${expected_file}")
  echo "[INFO] Log file verified: ${expected_file} (${size} bytes)"

  # Show last few lines
  echo "Last 5 lines:"
  tail -5 "${expected_file}" | sed 's/^/  /'

  return 0
}

# =============================================================================
# Node Log Extraction (for nodes that use output='screen')
# =============================================================================

# Extract logs for a specific node from 00_master.log
# This is useful for nodes whose SDKs use printf() directly (bypassing ROS2 logging)
# Usage: extract_node_log NODE_NAME [MASTER_LOG_PATH]
# Returns the path to the extracted log file
extract_node_log() {
  local node_name="$1"
  local master_log="${2:-${APP_LOG_DIR}/00_master.log}"
  local extracted_log="${APP_LOG_DIR}/${node_name}.log"

  # Extract lines containing the node name prefix
  # Format: [node_name-N] or [node_name]
  grep -E "\[(${node_name}[-_][0-9]+|${node_name})\]" "${master_log}" > "${extracted_log}" 2>/dev/null || true

  # If no matches with node name, try executable name
  if [[ ! -s "${extracted_log}" ]]; then
    # Try to find logs by executable name patterns
    grep -E "\[(hesai_ros_driver_node|hesai|battery_monitor_node)" "${master_log}" > "${extracted_log}" 2>/dev/null || true
  fi

  echo "${extracted_log}"
}

# Start background log extraction for a node
# Continuously monitors 00_master.log and extracts relevant lines
# Usage: start_node_log_extractor NODE_NAME [LOG_PATTERN]
#   NODE_NAME: Name for the output log file
#   LOG_PATTERN: Optional grep pattern for matching log lines (default: matches node_name)
start_node_log_extractor() {
  local node_name="$1"
  local log_pattern="${2:-${node_name}}"
  local master_log="${APP_LOG_DIR}/00_master.log"
  local extracted_log="${APP_LOG_DIR}/${node_name}.log"

  # Special case for navi_lidar_driver - the actual executable is hesai_ros_driver_node
  if [[ "${node_name}" == "navi_lidar_driver" ]]; then
    log_pattern="hesai_ros_driver_node"
  fi

  # Special case for battery_monitor - the actual executable is battery_monitor_node
  if [[ "${node_name}" == "battery_monitor" ]]; then
    log_pattern="battery_monitor_node"
  fi

  # Start background process to monitor and extract
  (
    # Wait for master log to exist and have content
    while [[ ! -f "${master_log}" ]] || [[ ! -s "${master_log}" ]]; do
      sleep 0.5
    done

    # Extract matching lines using bash regex (more reliable than grep -E for this case)
    # Pattern matches lines starting with [log_pattern] or [log_pattern-N]
    local regex="^\\[${log_pattern}(-[0-9]+)?\\]"

    # Initial extraction with ANSI code stripping
    while IFS= read -r line; do
      if [[ "$line" =~ $regex ]]; then
        echo "$line" | sed 's/\x1b\[[0-9;]*m//g'
      fi
    done < "${master_log}" > "${extracted_log}" 2>/dev/null

    # Follow the master log and append new lines
    tail -f "${master_log}" 2>/dev/null | while IFS= read -r line; do
      if [[ "$line" =~ $regex ]]; then
        echo "$line" | sed 's/\x1b\[[0-9;]*m//g'
      fi
    done >> "${extracted_log}" 2>/dev/null
  ) &

  echo "$!"  # Return the background process PID
}
