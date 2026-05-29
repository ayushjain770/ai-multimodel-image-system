#!/usr/bin/env bash
# Model acquisition: the Juggernaut SDXL checkpoint for ComfyUI and an optional
# pre-pull of the vLLM (Qwen) weights. Every source/path comes from .env.
# Idempotent: existing, valid files are left untouched.

# Expects common.sh to be sourced first.

_sha256() {
    if command -v sha256sum >/dev/null 2>&1; then
        sha256sum "$1" | awk '{print $1}'
    else
        shasum -a 256 "$1" | awk '{print $1}'
    fi
}

_juggernaut_url() {
    if [[ -n "${JUGGERNAUT_URL:-}" ]]; then
        echo "${JUGGERNAUT_URL}"
    elif [[ -n "${JUGGERNAUT_HF_REPO:-}" && -n "${JUGGERNAUT_HF_FILE:-}" ]]; then
        echo "https://huggingface.co/${JUGGERNAUT_HF_REPO}/resolve/main/${JUGGERNAUT_HF_FILE}?download=true"
    else
        echo ""
    fi
}

download_juggernaut() {
    local models_dir dest_dir dest url
    models_dir="${MODELS_DIR:-./models}"
    [[ "${models_dir}" = /* ]] || models_dir="${REPO_ROOT}/${models_dir#./}"
    dest_dir="${models_dir}/checkpoints"
    dest="${dest_dir}/${JUGGERNAUT_LOCAL_FILE:-juggernautXL.safetensors}"
    mkdir -p "${dest_dir}"

    if [[ -f "${dest}" ]]; then
        if [[ -n "${JUGGERNAUT_SHA256:-}" ]]; then
            if [[ "$(_sha256 "${dest}")" == "${JUGGERNAUT_SHA256}" ]]; then
                log_ok "Juggernaut present and checksum matches; skipping"
                return 0
            fi
            log_warn "Juggernaut checksum mismatch; re-downloading"
        else
            log_ok "Juggernaut already present; skipping (set JUGGERNAUT_SHA256 to verify)"
            return 0
        fi
    fi

    url="$(_juggernaut_url)"
    [[ -n "${url}" ]] || die "No Juggernaut source: set JUGGERNAUT_HF_REPO+FILE or JUGGERNAUT_URL"

    log_step "Downloading Juggernaut checkpoint"
    log_info "source: ${url%%\?*}"
    local -a auth=()
    [[ -n "${HF_TOKEN:-}" ]] && auth=(-H "Authorization: Bearer ${HF_TOKEN}")

    retry 3 5 curl -fL "${auth[@]}" --progress-bar -o "${dest}.part" "${url}" \
        || die "Juggernaut download failed"
    mv "${dest}.part" "${dest}"

    if [[ -n "${JUGGERNAUT_SHA256:-}" ]]; then
        [[ "$(_sha256 "${dest}")" == "${JUGGERNAUT_SHA256}" ]] \
            || die "Downloaded Juggernaut checksum does not match JUGGERNAUT_SHA256"
        log_ok "checksum verified"
    fi
    log_ok "Juggernaut ready at ${dest}"
}

prepull_llm() {
    [[ "${PREPULL_LLM:-false}" == "true" ]] || { log_info "PREPULL_LLM not enabled; vLLM will download on first boot"; return 0; }

    local proj vol model
    proj="$(compose config --format json 2>/dev/null | python3 -c 'import json,sys;print(json.load(sys.stdin).get("name",""))')"
    [[ -n "${proj}" ]] || die "could not resolve compose project name for hf_cache volume"
    vol="${proj}_hf_cache"
    model="${VLLM_MODEL:-Qwen/Qwen2.5-VL-3B-Instruct}"

    log_step "Pre-pulling LLM weights (${model}) into volume ${vol}"
    docker run --rm \
        -e "HF_TOKEN=${HF_TOKEN:-}" \
        -e "HUGGING_FACE_HUB_TOKEN=${HF_TOKEN:-}" \
        -v "${vol}:/root/.cache/huggingface" \
        python:3.12-slim \
        bash -c "pip install -q 'huggingface_hub[cli]' && hf download '${model}'" \
        || die "LLM pre-pull failed"
    log_ok "LLM weights cached"
}

# Download whatever the current mode needs.
download_models() {
    download_juggernaut
    if [[ "${DEPLOY_MODE:-dev}" == "prod" ]]; then
        prepull_llm
    fi
}
