#!/usr/bin/env bash
# Shared helpers for the Phase 2 orchestrator: logging, strict mode + error
# trapping, retries, and .env loading. Sourced by every other script.
#
# Nothing here is hardcoded to a service/port/model - callers read those from
# the loaded .env.

# ---------------------------------------------------------------------------
# Paths (resolved relative to this file, so scripts work from any CWD)
# ---------------------------------------------------------------------------
LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INFRA_DIR="$(cd "${LIB_DIR}/.." && pwd)"
REPO_ROOT="$(cd "${INFRA_DIR}/.." && pwd)"
LOG_DIR="${INFRA_DIR}/.logs"

# ---------------------------------------------------------------------------
# Colours (disabled when not a TTY or when NO_COLOR is set)
# ---------------------------------------------------------------------------
if [[ -t 1 && -z "${NO_COLOR:-}" ]]; then
    C_RESET="\033[0m"; C_RED="\033[31m"; C_GRN="\033[32m"
    C_YEL="\033[33m"; C_BLU="\033[34m"; C_DIM="\033[2m"
else
    C_RESET=""; C_RED=""; C_GRN=""; C_YEL=""; C_BLU=""; C_DIM=""
fi

_ts() { date "+%Y-%m-%dT%H:%M:%S%z"; }

log_info() { echo -e "${C_DIM}$(_ts)${C_RESET} ${C_BLU}INFO ${C_RESET} $*"; }
log_ok()   { echo -e "${C_DIM}$(_ts)${C_RESET} ${C_GRN}OK   ${C_RESET} $*"; }
log_warn() { echo -e "${C_DIM}$(_ts)${C_RESET} ${C_YEL}WARN ${C_RESET} $*" >&2; }
log_error(){ echo -e "${C_DIM}$(_ts)${C_RESET} ${C_RED}ERROR${C_RESET} $*" >&2; }
log_step() { echo -e "\n${C_BLU}==>${C_RESET} $*"; }

die() { log_error "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Strict mode + error trap. Call enable_strict_mode in the entrypoint.
# ---------------------------------------------------------------------------
enable_strict_mode() {
    set -Eeuo pipefail
    trap '_on_error $? $LINENO "${BASH_COMMAND}"' ERR
}

_on_error() {
    local code="$1" line="$2" cmd="$3"
    log_error "Failed (exit ${code}) at line ${line}: ${cmd}"
    log_error "See logs in ${LOG_DIR}/ for details."
    exit "${code}"
}

# ---------------------------------------------------------------------------
# require_cmd <binary> [hint]
# ---------------------------------------------------------------------------
require_cmd() {
    local bin="$1" hint="${2:-}"
    command -v "${bin}" >/dev/null 2>&1 || die "'${bin}' is required but not found. ${hint}"
}

# ---------------------------------------------------------------------------
# retry <max> <delay_seconds> <cmd...>   (exponential backoff)
# ---------------------------------------------------------------------------
retry() {
    local max="$1" delay="$2"; shift 2
    local attempt=1
    until "$@"; do
        if (( attempt >= max )); then
            return 1
        fi
        log_warn "attempt ${attempt}/${max} failed; retrying in ${delay}s: $*"
        sleep "${delay}"
        delay=$(( delay * 2 ))
        attempt=$(( attempt + 1 ))
    done
}

# ---------------------------------------------------------------------------
# load_env: bootstrap .env from .env.example if missing, then export all keys.
# ---------------------------------------------------------------------------
load_env() {
    local env_file="${REPO_ROOT}/.env"
    local example="${REPO_ROOT}/.env.example"
    if [[ ! -f "${env_file}" ]]; then
        [[ -f "${example}" ]] || die ".env and .env.example are both missing"
        cp "${example}" "${env_file}"
        log_warn "Created .env from .env.example (review before prod use)"
    fi
    # Parse line-by-line instead of `source` so values may contain spaces and
    # are never shell-evaluated. Same rules docker compose uses for env files.
    local line key val
    while IFS= read -r line || [[ -n "${line}" ]]; do
        line="${line%$'\r'}"
        [[ "${line}" =~ ^[[:space:]]*# ]] && continue
        [[ "${line}" != *=* ]] && continue
        key="${line%%=*}"
        val="${line#*=}"
        # Strip matching surrounding quotes if present.
        if [[ "${val}" == \"*\" || "${val}" == \'*\' ]]; then
            val="${val:1:${#val}-2}"
        fi
        export "${key}=${val}"
    done < "${env_file}"
    mkdir -p "${LOG_DIR}"
}

# ---------------------------------------------------------------------------
# compose <args...> : invoke docker compose with the right files for the mode.
# Requires DEPLOY_MODE to be set (dev|prod).
# ---------------------------------------------------------------------------
# shellcheck source=ec2.sh
source "${LIB_DIR}/ec2.sh"

compose() {
    local mode="${DEPLOY_MODE:-dev}"
    local -a files=(-f "${REPO_ROOT}/docker-compose.yml")
    if [[ "${mode}" == "prod" ]]; then
        files+=(-f "${REPO_ROOT}/docker-compose.prod.yml")
        ( cd "${REPO_ROOT}" && docker compose "${files[@]}" --profile gpu "$@" )
    else
        files+=(-f "${REPO_ROOT}/docker-compose.dev.yml")
        ( cd "${REPO_ROOT}" && docker compose "${files[@]}" "$@" )
    fi
}
