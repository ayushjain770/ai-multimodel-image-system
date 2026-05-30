#!/usr/bin/env bash
# EC2 instance metadata helpers for public host resolution.
# Expects common.sh to be sourced first.

detect_ec2_public_ip() {
    local token ip
    token="$(curl -sf -X PUT \
        "http://169.254.169.254/latest/api/token" \
        -H "X-aws-ec2-metadata-token-ttl-seconds: 21600" \
        --connect-timeout 2 --max-time 3 2>/dev/null)" || true
    if [[ -n "${token}" ]]; then
        ip="$(curl -sf \
            "http://169.254.169.254/latest/meta-data/public-ipv4" \
            -H "X-aws-ec2-metadata-token: ${token}" \
            --connect-timeout 2 --max-time 3 2>/dev/null)" || true
        if [[ -n "${ip}" ]]; then
            echo "${ip}"
            return 0
        fi
    fi
    ip="$(curl -sf \
        "http://169.254.169.254/latest/meta-data/public-ipv4" \
        --connect-timeout 2 --max-time 3 2>/dev/null)" || true
    [[ -n "${ip}" ]] && echo "${ip}"
}

resolve_public_host() {
    local default_api="http://localhost:${BACKEND_PORT:-8080}"
    if [[ -z "${PUBLIC_HOST:-}" ]]; then
        PUBLIC_HOST="$(detect_ec2_public_ip || true)"
        if [[ -n "${PUBLIC_HOST}" ]]; then
            export PUBLIC_HOST
            log_ok "detected EC2 public IP: ${PUBLIC_HOST}"
        fi
    else
        log_ok "using PUBLIC_HOST from .env: ${PUBLIC_HOST}"
    fi

    if [[ -n "${PUBLIC_HOST:-}" ]]; then
        if [[ -z "${NEXT_PUBLIC_API_URL:-}" \
            || "${NEXT_PUBLIC_API_URL}" == "${default_api}" \
            || "${NEXT_PUBLIC_API_URL}" == "http://localhost:8080" ]]; then
            export NEXT_PUBLIC_API_URL="http://${PUBLIC_HOST}:${BACKEND_PORT:-8080}"
            log_ok "set NEXT_PUBLIC_API_URL=${NEXT_PUBLIC_API_URL}"
        fi
    fi
}
