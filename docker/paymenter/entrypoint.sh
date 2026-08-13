#!/bin/ash -e
cd /app

# ---------------------------------------------------------------------------
# Hardened entrypoint. Differences from the upstream Paymenter entrypoint:
#   * runs as the unprivileged `nginx` user (no chown, no root cron)
#   * storage permissions tightened from 777 -> 775 (Lab 5 secret-perms theme)
#   * supports *_FILE secret indirection so APP_KEY / DB_PASSWORD are read from
#     runtime-mounted files instead of being baked into the image or process
#     environment (fixes Lab 5 s3.1 / s3.4 secret-handling findings)
# ---------------------------------------------------------------------------

# Read a secret from a mounted file when VAR_FILE is provided.
load_secret_file() {
  var_name="$1"
  file_var="${var_name}_FILE"
  eval "file_path=\${$file_var:-}"
  if [ -n "$file_path" ] && [ -r "$file_path" ]; then
    val="$(cat "$file_path")"
    export "$var_name=$val"
  fi
}

load_secret_file APP_KEY
load_secret_file DB_PASSWORD
load_secret_file REDIS_PASSWORD

mkdir -p /var/log/supervisord/ /var/log/nginx/

## check for external .env file and generate app key if missing
if [ -f /app/var/.env ]; then
  echo "external vars exist."
  rm -rf /app/.env
  ln -s /app/var/.env /app/.env
else
  echo "external vars don't exist."
  rm -rf /app/.env
  touch /app/var/.env

  if [ -z "$APP_KEY" ]; then
    echo "Generating key."
    APP_KEY=$(cat /dev/urandom | tr -dc 'a-zA-Z0-9' | fold -w 32 | head -n 1)
  else
    echo "APP_KEY provided via environment/secret, using that."
  fi
  echo "APP_KEY=$APP_KEY" > /app/var/.env
  ln -s /app/var/.env /app/.env
fi

if [ -z "$DB_PORT" ]; then
  echo "DB_PORT not specified, defaulting to 3306"
  DB_PORT=3306
fi

## wait for the database
echo "Checking database status."
until nc -z -v -w30 "$DB_HOST" "$DB_PORT"; do
  echo "Waiting for database connection..."
  sleep 1
done

## storage symlink
if [ ! -L /app/public/storage ]; then
  echo "Creating storage symlink."
  rm -rf /app/public/storage
  ln -s /app/storage/app/public /app/public/storage
fi

## renew default themes and extensions unless PAYMENTER_SKIP_DEFAULT=true
if [ -z "$PAYMENTER_SKIP_DEFAULT" ] || [ "$PAYMENTER_SKIP_DEFAULT" != "true" ]; then
  echo "Renewing default themes and extensions..."
  if [ -d /app/themes_default ] && [ -d /app/themes ]; then
    for item in /app/themes_default/*; do
      [ -e "$item" ] || continue
      item_name=$(basename "$item")
      rm -rf "/app/themes/$item_name"
      cp -rp "$item" "/app/themes/"
    done
  fi
  if [ -d /app/extensions_default ] && [ -d /app/extensions ]; then
    for item in /app/extensions_default/*; do
      [ -e "$item" ] || continue
      item_name=$(basename "$item")
      if [ -d "/app/extensions/$item_name" ] && [ "$(ls -A "/app/extensions/$item_name" 2>/dev/null)" ]; then
        for ext_dir in "/app/extensions/$item_name"/*; do
          [ -d "$ext_dir" ] || continue
          ext_name=$(basename "$ext_dir")
          default_ext="/app/extensions_default/$item_name/$ext_name"
          if [ -d "$default_ext" ]; then
            rm -rf "$ext_dir"
            cp -rp "$default_ext" "$ext_dir"
          fi
        done
      fi
    done
  fi
fi

## seed themes/extensions if empty
if [ ! -d /app/themes ] || [ -z "$(ls -A /app/themes 2>/dev/null)" ]; then
  mkdir -p /app/themes
  [ -d /app/themes_default ] && cp -rp /app/themes_default/. /app/themes/
fi
if [ ! -d /app/extensions ] || [ -z "$(ls -A /app/extensions 2>/dev/null)" ]; then
  mkdir -p /app/extensions
  [ -d /app/extensions_default ] && cp -rp /app/extensions_default/. /app/extensions/
fi

## tighten storage perms (was 777 upstream)
echo "Setting storage permissions (775)."
chmod -R 775 /app/storage 2>/dev/null || true
chmod -R 775 /app/themes /app/extensions 2>/dev/null || true

## Passport signing keys (Lab 4 s2.1-s2.2 / Lab 5 s3.1). These live in
## /app/storage, outside every named volume, so they're recreated with the
## container. Generate them if absent, then force 600 — the blanket
## `chmod -R 775 /app/storage` above would otherwise leave the private key
## world-readable (found live: 775). Must come AFTER that chmod.
if [ ! -f /app/storage/oauth-private.key ]; then
  echo "Generating Passport signing keys."
  php artisan passport:keys --no-interaction || true
fi
chmod 600 /app/storage/oauth-private.key /app/storage/oauth-public.key 2>/dev/null || true

## migrate + seed
echo "Migrating and seeding database."
php artisan migrate --seed --force

## cache config/routes/views for production
php artisan config:cache || true
php artisan route:cache || true
php artisan view:cache || true

echo "Starting supervisord."
exec "$@"
