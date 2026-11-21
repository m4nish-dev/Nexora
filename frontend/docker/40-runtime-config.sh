#!/bin/sh
# Writes the browser runtime config from env at container start, so one image works in any environment.
set -eu
escaped=$(printf '%s' "${API_BASE_URL:-}" | sed 's/\\/\\\\/g; s/"/\\"/g')
printf 'window.__NEXORA_CONFIG__ = { API_BASE_URL: "%s" };\n' "$escaped" > /usr/share/nginx/html/config.js
echo "nexora: API_BASE_URL=${API_BASE_URL:-<unset>}"
