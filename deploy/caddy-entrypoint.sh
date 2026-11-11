#!/bin/sh
# Pick HTTP or automatic HTTPS from DOMAIN. DOMAIN is not a secret.
set -eu
if [ -n "${DOMAIN:-}" ]; then
  exec caddy run --config /etc/caddy/Caddyfile.https --adapter caddyfile
fi
exec caddy run --config /etc/caddy/Caddyfile --adapter caddyfile
