#!/usr/bin/env bash
# Single entrypoint for the Christianity AI Assistant (one project, two deploy modes).
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SCRIPT="${ROOT}/infrastructure/script/script.sh"

CMD="${1:-}"
shift || true

case "${CMD}" in
  ""|up|dev)
    MODE="${1:-${DEPLOY_MODE:-dev}}"
    exec "${SCRIPT}" up "${MODE}"
    ;;
  prod)
    exec "${SCRIPT}" up prod
    ;;
  down)
    MODE="${1:-dev}"
    exec "${SCRIPT}" down "${MODE}"
    ;;
  doctor|build|models|ingest|health|logs)
    exec "${SCRIPT}" "${CMD}" "$@"
    ;;
  *)
    # ./startup.sh prod  or  ./startup.sh down prod
    exec "${SCRIPT}" up "${CMD}"
    ;;
esac
