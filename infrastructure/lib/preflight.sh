#!/usr/bin/env bash
# Preflight checks run before any build/up. All thresholds and ports come from
# the loaded .env - nothing is hardcoded.

# Expects common.sh to be sourced first.

_check_docker() {
    require_cmd docker "Install Docker Desktop / Docker Engine."
    if ! docker info >/dev/null 2>&1; then
        die "Docker daemon is not running. Start Docker and retry."
    fi
    log_ok "docker daemon reachable"
}

_check_compose() {
    if ! docker compose version >/dev/null 2>&1; then
        die "Docker Compose v2 is required (the 'docker compose' subcommand)."
    fi
    log_ok "docker compose v2 present"
}

_check_disk() {
    local min_gb="${DISK_MIN_GB:-10}"
    # Portable: available kilobytes for the repo's filesystem -> GB.
    local avail_kb avail_gb
    avail_kb="$(df -Pk "${REPO_ROOT}" | awk 'NR==2 {print $4}')"
    avail_gb=$(( avail_kb / 1024 / 1024 ))
    if (( avail_gb < min_gb )); then
        die "Only ${avail_gb}GB free; need >= ${min_gb}GB (DISK_MIN_GB). Free space and retry."
    fi
    log_ok "disk space ok (${avail_gb}GB free, need ${min_gb}GB)"
}

_port_in_use() {
    local port="$1"
    if command -v nc >/dev/null 2>&1; then
        nc -z localhost "${port}" >/dev/null 2>&1
    else
        (exec 3<>"/dev/tcp/localhost/${port}") >/dev/null 2>&1
    fi
}

_check_ports() {
    # Host ports we are about to bind; prod adds the GPU service ports.
    local -a ports=("${UI_PORT:-3000}" "${BACKEND_PORT:-8080}" "${MCP_PORT:-8001}" "${QDRANT_PORT:-6333}")
    if [[ "${DEPLOY_MODE:-dev}" == "prod" ]]; then
        ports+=("${VLLM_PORT:-8000}" "${COMFYUI_PORT:-8188}")
    fi
    local busy=0
    for p in "${ports[@]}"; do
        if _port_in_use "${p}"; then
            log_warn "port ${p} is already in use (ok if it's this stack restarting)"
            busy=1
        fi
    done
    if (( busy == 0 )); then
        log_ok "required host ports are free"
    fi
    return 0
}

_check_required_env() {
    local -a required=(DEPLOY_MODE QDRANT_COLLECTION EMBEDDING_MODEL)
    local missing=()
    for var in "${required[@]}"; do
        [[ -n "${!var:-}" ]] || missing+=("${var}")
    done
    (( ${#missing[@]} == 0 )) || die "missing required env vars: ${missing[*]}"
    log_ok "required env vars present"
}

_check_gpu() {
    if [[ "${DEPLOY_MODE:-dev}" != "prod" ]]; then
        return 0
    fi
    require_cmd nvidia-smi "prod mode needs an NVIDIA GPU host + NVIDIA Container Toolkit."
    nvidia-smi >/dev/null 2>&1 || die "nvidia-smi failed; GPU not available for prod mode."
    log_ok "nvidia gpu detected"
}

preflight() {
    log_step "Preflight checks (mode=${DEPLOY_MODE:-dev})"
    _check_docker
    _check_compose
    _check_required_env
    _check_disk
    _check_ports
    _check_gpu
    log_ok "preflight passed"
}
