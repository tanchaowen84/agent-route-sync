#!/usr/bin/env bash
# Identical official Linux/amd64 tools for producing and independently validating a release.
set -euo pipefail
mkdir -p "${RUNNER_TEMP:?}/rule-tools"
cd "$RUNNER_TEMP/rule-tools"
curl --fail --location --retry 2 --max-time 120 --output mihomo.gz \
  https://github.com/MetaCubeX/mihomo/releases/download/v1.19.32/mihomo-linux-amd64-v1-v1.19.32.gz
echo '306f81e723e60ce6b828899a6fe83e1d00e9ecefb2dc8d4d849312a5bc00efdc  mihomo.gz' | sha256sum -c -
gzip -dc mihomo.gz > mihomo
chmod +x mihomo
curl --fail --location --retry 2 --max-time 120 --output sing-box.tar.gz \
  https://github.com/SagerNet/sing-box/releases/download/v1.14.4/sing-box-1.14.4-linux-amd64.tar.gz
echo '699a1b510aa4396b2176d32d1181920399ebf1e267835da6f3b598d0f7c24968  sing-box.tar.gz' | sha256sum -c -
tar -xzf sing-box.tar.gz --strip-components=1 sing-box-1.14.4-linux-amd64/sing-box
