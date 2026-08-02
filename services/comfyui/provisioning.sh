#!/bin/bash

# Harbor provisioning for the yanwk/comfyui-boot image.
#
# Mounted as /root/user-scripts/pre-start.sh — the image's entrypoint
# sources it on every container start, after ComfyUI is unpacked to
# /root/ComfyUI and before it launches. Downloads the Flux.1-schnell
# model set expected by Harbor's Open WebUI image-generation integration.
#
# NOTE: sourced under `set -e` — every step must tolerate failure so a
# flaky download never prevents ComfyUI from starting.

harbor_provisioning() {
    local models_dir="/root/ComfyUI/models"

    if [[ "${HARBOR_COMFYUI_PROVISIONING,,}" != "true" ]]; then
        echo "[Harbor] Provisioning disabled (HARBOR_COMFYUI_PROVISIONING != true), skipping."
        return 0
    fi

    echo "[Harbor] Provisioning ComfyUI models (idempotent, skips existing files)..."

    harbor_download "${models_dir}/clip" \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors" \
        "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors"

    harbor_download "${models_dir}/diffusion_models" \
        "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/flux1-schnell.safetensors"

    harbor_download "${models_dir}/vae" \
        "https://huggingface.co/black-forest-labs/FLUX.1-schnell/resolve/main/ae.safetensors"

    harbor_download "${models_dir}/upscale_models" \
        "https://huggingface.co/ai-forever/Real-ESRGAN/resolve/main/RealESRGAN_x4.pth" \
        "https://huggingface.co/FacehugmanIII/4x_foolhardy_Remacri/resolve/main/4x_foolhardy_Remacri.pth" \
        "https://huggingface.co/Akumetsu971/SD_Anime_Futuristic_Armor/resolve/main/4x_NMKD-Siax_200k.pth"

    # Make Harbor's starter Flux workflow available in the UI
    # (Workflows sidebar -> browse workflows)
    if [[ -f /opt/harbor/default-workflow.json ]]; then
        mkdir -p /root/ComfyUI/user/default/workflows || true
        cp -n /opt/harbor/default-workflow.json \
            /root/ComfyUI/user/default/workflows/harbor-flux.json 2>/dev/null || true
    fi

    echo "[Harbor] Provisioning complete."
}

# Download each URL into a directory; auth via HF/Civitai tokens when the
# URL matches; `wget -nc` keeps re-runs idempotent.
harbor_download() {
    local dir="$1"
    shift
    mkdir -p "$dir" || return 0

    local url auth_token
    for url in "$@"; do
        auth_token=""
        if [[ -n $HF_TOKEN && $url =~ ^https://([a-zA-Z0-9_-]+\.)?huggingface\.co(/|$|\?) ]]; then
            auth_token="$HF_TOKEN"
        elif [[ -n $CIVITAI_TOKEN && $url =~ ^https://([a-zA-Z0-9_-]+\.)?civitai\.com(/|$|\?) ]]; then
            auth_token="$CIVITAI_TOKEN"
        fi

        echo "[Harbor] Downloading: $url"
        if ! command -v wget >/dev/null 2>&1; then
            # Some slim variants may lack wget — fall back to python
            python3 - "$url" "$dir" "$auth_token" <<'PYEOF' || echo "[Harbor] WARN: failed to download $url"
import os, sys, urllib.request
url, dir_, token = sys.argv[1], sys.argv[2], sys.argv[3]
dest = os.path.join(dir_, url.rsplit("/", 1)[-1].split("?")[0])
if not os.path.exists(dest):
    req = urllib.request.Request(url)
    if token:
        req.add_header("Authorization", "Bearer " + token)
    tmp = dest + ".part"
    with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.rename(tmp, dest)
PYEOF
        elif [[ -n $auth_token ]]; then
            wget --header="Authorization: Bearer $auth_token" \
                -qnc --content-disposition --show-progress -P "$dir" "$url" ||
                echo "[Harbor] WARN: failed to download $url"
        else
            wget -qnc --content-disposition --show-progress -P "$dir" "$url" ||
                echo "[Harbor] WARN: failed to download $url"
        fi
    done
}

harbor_provisioning || echo "[Harbor] WARN: provisioning encountered errors, continuing startup."
