#!/usr/bin/env bash
# =============================================================================
# Phase 2 - single-command orchestrator for the Christianity AI assistant.
#
#   infrastructure/script/script.sh [command] [dev|prod]
#
# Commands:
#   up        preflight -> (prod: download models) -> build -> up -> health ->
#             ingest -> smoke test   (default command)
#   down      stop and remove the stack
#   build     build images only (with error detection)
#   models    download Juggernaut + (prod) pre-pull the LLM weights
#   ingest    run the Bible corpus ingestion (idempotent)
#   health    wait for health + probe HTTP endpoints
#   doctor    run preflight checks only
#   logs      tail logs (optionally a single service: ... logs backend)
#
# Everything is driven by .env (bootstrapped from .env.example). No hardcoded
# hosts, ports, models, or paths.
# =============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../lib/common.sh
source "${SCRIPT_DIR}/../lib/common.sh"
# shellcheck source=../lib/preflight.sh
source "${SCRIPT_DIR}/../lib/preflight.sh"
# shellcheck source=../lib/health.sh
source "${SCRIPT_DIR}/../lib/health.sh"
# shellcheck source=../lib/models.sh
source "${SCRIPT_DIR}/../lib/models.sh"

enable_strict_mode
load_env

# ---------------------------------------------------------------------------
# Resolve mode: explicit arg (dev|prod) wins, else DEPLOY_MODE from .env.
# ---------------------------------------------------------------------------
resolve_mode() {
    local arg="${1:-}"
    case "${arg}" in
        dev|prod) export DEPLOY_MODE="${arg}" ;;
        "")       export DEPLOY_MODE="${DEPLOY_MODE:-dev}" ;;
        *)        export DEPLOY_MODE="${DEPLOY_MODE:-dev}" ;;
    esac
}

do_build() {
    log_step "Building images (mode=${DEPLOY_MODE})"
    local logf="${LOG_DIR}/build-$(date +%Y%m%d-%H%M%S).log"
    if compose build 2>&1 | tee "${logf}"; then
        log_ok "build complete"
    else
        log_error "Build failed. Last lines of ${logf}:"
        tail -n 30 "${logf}" >&2 || true
        die "Resolve the build error above and retry."
    fi
}

do_up() {
    log_step "Starting stack (mode=${DEPLOY_MODE})"
    compose up -d
    log_ok "containers started"
}

do_down() {
    log_step "Stopping stack (mode=${DEPLOY_MODE})"
    compose down
    log_ok "stack stopped"
}

do_ingest() {
    log_step "Ingesting Bible corpus (idempotent)"
    # The ingest service is profile-gated, so `compose build` skips it; build
    # here (with --build) so the loader/manifest are never stale.
    if compose run --rm --build ingest; then
        log_ok "ingestion complete"
    else
        die "ingestion failed (see output above)"
    fi
}

do_smoke() {
    log_step "Smoke test"
    local base="http://localhost:${BACKEND_PORT:-8080}"
    local payload reply cites
    payload='{"message":"What does the Bible say about love?","generate_image":false}'
    local resp
    resp="$(curl -fsS --max-time 30 -X POST "${base}/api/v1/chat" \
        -H 'Content-Type: application/json' -d "${payload}")" \
        || die "smoke chat request failed"
    reply="$(printf '%s' "${resp}" | python3 -c 'import json,sys;print(json.load(sys.stdin).get("reply","")[:120])')"
    cites="$(printf '%s' "${resp}" | python3 -c 'import json,sys;print(len(json.load(sys.stdin).get("citations") or []))')"
    log_ok "chat replied (citations=${cites}): ${reply}"
}

print_urls() {
    local host="${PUBLIC_HOST:-localhost}"
    log_step "Stack is up (mode=${DEPLOY_MODE})"
    echo "  UI        : http://${host}:${UI_PORT:-3000}"
    echo "  Backend   : http://${host}:${BACKEND_PORT:-8080}"
    echo "  Readyz    : http://${host}:${BACKEND_PORT:-8080}/health/readyz"
    echo "  MCP       : http://${host}:${MCP_PORT:-8001}/mcp"
    echo "  Qdrant    : http://${host}:${QDRANT_PORT:-6333}/dashboard"
    if [[ "${DEPLOY_MODE}" == "prod" ]]; then
        echo "  vLLM      : http://${host}:${VLLM_PORT:-8000}/v1"
        echo "  ComfyUI   : http://${host}:${COMFYUI_PORT:-8188}"
        if [[ "${host}" == "localhost" ]]; then
            echo ""
            echo "  EC2: set PUBLIC_HOST and NEXT_PUBLIC_API_URL in .env, rebuild ui, open SG ports 3000+8080."
        fi
    fi
}

cmd_up() {
    preflight
    [[ "${DEPLOY_MODE}" == "prod" ]] && download_models
    do_build
    do_up
    wait_for_healthy
    probe_endpoints
    do_ingest
    do_smoke
    print_urls
}

main() {
    local command="${1:-up}"
    resolve_mode "${2:-}"

    case "${command}" in
        up)      cmd_up ;;
        down)    do_down ;;
        build)   preflight; do_build ;;
        models)  download_models ;;
        ingest)  do_ingest ;;
        health)  wait_for_healthy; probe_endpoints ;;
        doctor)  preflight ;;
        logs)    if [[ -n "${2:-}" ]]; then compose logs -f "${2}"; else compose logs -f; fi ;;
        *)       die "unknown command '${command}'. See header for usage." ;;
    esac
}

main "$@"
