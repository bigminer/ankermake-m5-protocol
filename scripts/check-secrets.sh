#!/usr/bin/env bash
#
# Fail if any tracked file contains secrets or personal/unique setup values.
# Runs in CI (.github/workflows/secret-sweep.yml) and is safe to run locally:
#
#     ./scripts/check-secrets.sh
#
# It scans the whole tracked tree with generic patterns (no real values are
# baked into this script). Placeholders from setup.local.conf.example are
# allow-listed. Real values belong only in the git-ignored setup.local.conf.
set -u

# Exclude this script and its workflow — they legitimately contain the patterns.
EXCLUDES=(':(exclude)scripts/check-secrets.sh' ':(exclude).github/workflows/secret-sweep.yml')

fail=0

# scan <label> <extended-regex> [allowlist-regex]
scan() {
    label=$1; regex=$2; allow=${3:-}
    # -e is required so patterns beginning with '-' (e.g. -----BEGIN KEY) are
    # treated as patterns, not options.
    hits=$(git grep -nIE -e "$regex" -- . "${EXCLUDES[@]}" 2>/dev/null)
    if [ -n "$allow" ]; then
        hits=$(printf '%s\n' "$hits" | grep -vE "$allow")
    fi
    hits=$(printf '%s\n' "$hits" | grep -v '^$')
    if [ -n "$hits" ]; then
        printf '\n  ✗ %s\n' "$label"
        printf '%s\n' "$hits" | sed 's/^/      /'
        fail=1
    fi
}

echo "Scanning tracked files for secrets and personal setup values..."

# --- Secrets -------------------------------------------------------------
scan "Private key material" '-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----'
scan "ankerctl token/secret with a value" \
     'ANKERCTL_(SECRET_KEY|TOKEN)[[:space:]]*=[[:space:]]*[^[:space:]#"'"'"']{5,}' \
     'your-|example|changeme|placeholder|xxxx|<|\$\{'
scan "Personal email address" \
     '[A-Za-z0-9._%+-]+@(gmail|googlemail|icloud|outlook|hotmail|yahoo|protonmail|proton)\.(com|me)'

# Real Anker account/printer config must never be committed.
if git ls-files | grep -qiE '(^|/)(default|login)\.json$'; then
    printf '\n  ✗ Real config file committed (default.json / login.json)\n'
    git ls-files | grep -iE '(^|/)(default|login)\.json$' | sed 's/^/      /'
    fail=1
fi

# --- Personal / unique setup values --------------------------------------
# NB: git grep here is POSIX ERE (no PCRE \b), so word boundaries are spelled
# out as (^|non-word) ... (non-word|$).
scan "Printer serial number" \
     '(^|[^0-9A-Za-z])AK[0-9A-Z]{14}([^0-9A-Za-z]|$)' 'AK00000000000000'
scan "Printer DUID" \
     '(^|[^0-9A-Za-z])[A-Z]{7}-[0-9]{6}-[A-Z0-9]{5}([^0-9A-Za-z]|$)' 'USPRAKM-000000-XXXXX'
scan "Tailscale hostname (*.ts.net)" '[A-Za-z0-9-]+\.ts\.net' 'your-tailnet\.ts\.net'
scan "Tailscale / CGNAT IP (100.64.0.0/10)" \
     '(^|[^0-9])100\.(6[4-9]|[7-9][0-9]|1[01][0-9]|12[0-7])\.[0-9]{1,3}\.[0-9]{1,3}([^0-9]|$)' \
     '100\.100\.100\.'
scan "Real home directory path" '/Users/[A-Za-z0-9._-]+' '/Users/you([^A-Za-z0-9]|$)'
scan "MAC address" '([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}' '00:11:22:33:44:55|11:22:33:44:55:66'

if [ "$fail" -ne 0 ]; then
    cat <<'EOF'

✗ Secret sweep FAILED — the above look like secrets or personal setup values.

  • Move real values into setup.local.conf (git-ignored); it is never committed.
  • Use the placeholders from setup.local.conf.example in tracked files.
  • If a hit is a false positive, extend the allow-list in scripts/check-secrets.sh.
EOF
    exit 1
fi

echo "✓ Secret sweep passed — no secrets or personal setup values found."
