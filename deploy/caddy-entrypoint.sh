#!/bin/sh
# Production Caddy always uses automatic HTTPS. DOMAIN is not a secret.
# ACME_EMAIL is optional. An empty DOMAIN must not fall back to plain HTTP.
set -eu

if [ -z "${DOMAIN:-}" ]; then
  echo "DOMAIN is empty. Refusing to serve plain HTTP." >&2
  exit 1
fi

src=/etc/caddy/Caddyfile.https
dest=/tmp/Caddyfile

if [ -n "${ACME_EMAIL:-}" ]; then
  awk -v email="$ACME_EMAIL" '
    BEGIN { done = 0 }
    /^\{/ && done == 0 {
      print
      print "\temail " email
      done = 1
      next
    }
    { print }
  ' "$src" > "$dest"
else
  cp "$src" "$dest"
fi

exec caddy run --config "$dest" --adapter caddyfile
