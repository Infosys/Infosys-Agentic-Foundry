#!/usr/bin/env sh
# entrypoint.sh for Nginx (static production hosting)
set -e

# Where Nginx serves static files
APP_ROOT="${APP_ROOT:-/usr/share/nginx/html}"
TEMPLATE="$APP_ROOT/runtime-config.js.template"
OUTPUT="$APP_ROOT/runtime-config.js"

echo "[entrypoint] Using APP_ROOT=$APP_ROOT (Nginx static)"

# Ensure envsubst is available
if ! command -v envsubst >/dev/null 2>&1; then
  echo "[entrypoint] ERROR: envsubst not found. Install 'gettext' in Dockerfile." >&2
  exit 1
fi

# Check that build exists
if [[ ! -d "$APP_ROOT" ]] || [[ ! -f "$APP_ROOT/index.html" ]]; then
  echo "[entrypoint] ERROR: No built app found at $APP_ROOT (index.html missing)" >&2
  exit 1
fi

# Check template presence
if [[ ! -f "$TEMPLATE" ]]; then
  echo "[entrypoint] ERROR: Template not found at: $TEMPLATE" >&2
  echo "[entrypoint] Ensure you copied public/runtime-config.js.template into the image." >&2
  exit 1
fi

# Generate runtime config
echo "[entrypoint] Generating $OUTPUT from template..."
envsubst < "$TEMPLATE" > "$OUTPUT"
chown nginx:nginx "$OUTPUT" || true
chmod 640 "$OUTPUT" || true
echo "[entrypoint] Generated $(wc -c < "$OUTPUT") bytes into $OUTPUT"

# Optional: light logging of key values (avoid secrets)
#echo "[entrypoint] API_URL=${REACT_APP_API_URL:-unset}"
#echo "[entrypoint] VERSION=${REACT_APP_VERSION:-unset}"

# Start Nginx (or whatever CMD is passed)
echo "[entrypoint] Starting: $*"
exec "$@"