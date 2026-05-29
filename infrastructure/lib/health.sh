#!/usr/bin/env bash
# Wait until every compose service is healthy, then probe HTTP endpoints.
# Timeouts and ports come from the loaded .env.

# Expects common.sh to be sourced first.

# Parse `docker compose ps --format json` (array or newline-delimited) into
# "name<TAB>state<TAB>health" rows using python3 (present on the host).
_compose_status_rows() {
    compose ps --format json 2>/dev/null | python3 -c '
import json, sys
raw = sys.stdin.read().strip()
if not raw:
    sys.exit(0)
items = []
try:
    parsed = json.loads(raw)
    items = parsed if isinstance(parsed, list) else [parsed]
except json.JSONDecodeError:
    for line in raw.splitlines():
        line = line.strip()
        if line:
            items.append(json.loads(line))
for it in items:
    name = it.get("Service") or it.get("Name", "?")
    state = it.get("State", "?")
    health = it.get("Health", "")
    print(f"{name}\t{state}\t{health}")
'
}

wait_for_healthy() {
    local timeout="${HEALTH_TIMEOUT:-300}" interval="${HEALTH_INTERVAL:-5}"
    local deadline=$(( SECONDS + timeout ))
    log_step "Waiting for services to become healthy (timeout=${timeout}s)"

    while (( SECONDS < deadline )); do
        local all_ok=1 any=0
        while IFS=$'\t' read -r name state health; do
            any=1
            if [[ -n "${health}" ]]; then
                # Service declares a healthcheck.
                [[ "${health}" == "healthy" ]] || all_ok=0
            else
                # No healthcheck: running is good enough.
                [[ "${state}" == "running" ]] || all_ok=0
            fi
        done < <(_compose_status_rows)

        if (( any == 1 && all_ok == 1 )); then
            log_ok "all services healthy"
            return 0
        fi
        sleep "${interval}"
    done

    log_error "Timed out waiting for services to become healthy. Current status:"
    compose ps || true
    return 1
}

# http_probe <name> <url>  (retried)
http_probe() {
    local name="$1" url="$2"
    if retry 10 2 curl -fsS -o /dev/null --max-time 5 "${url}"; then
        log_ok "${name} reachable (${url})"
    else
        die "${name} probe failed: ${url}"
    fi
}

# Probe the HTTP surfaces that should be live after startup.
probe_endpoints() {
    log_step "Probing HTTP endpoints"
    http_probe "backend /health/readyz" "http://localhost:${BACKEND_PORT:-8080}/health/readyz"
    http_probe "qdrant /readyz"         "http://localhost:${QDRANT_PORT:-6333}/readyz"
    if [[ "${DEPLOY_MODE:-dev}" == "prod" ]]; then
        http_probe "vllm /health"          "http://localhost:${VLLM_PORT:-8000}/health"
        http_probe "comfyui /system_stats" "http://localhost:${COMFYUI_PORT:-8188}/system_stats"
    fi
}
