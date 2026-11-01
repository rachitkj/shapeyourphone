#!/bin/sh
# One-time: create the launcher's release signing key and store it as GitHub
# Actions secrets, so tagged releases (git tag v0.1.0 && git push --tags)
# produce a signed shape-launcher.apk that phones can update in place.
#
# The keystore is also written to ~/.shape-release/ — BACK IT UP. If it is lost,
# future releases can't update existing installs (users would have to uninstall).
#
# Needs: keytool (any JDK), gh (logged in), openssl.
set -eu

DIR="$HOME/.shape-release"
KS="$DIR/shape-release.jks"
ALIAS="shape"
REPO="${1:-$(gh repo view --json nameWithOwner -q .nameWithOwner)}"

if [ -e "$KS" ]; then
  echo "A keystore already exists at $KS — refusing to overwrite it." >&2
  echo "To just upload it as secrets again, delete this check or set them by hand." >&2
  exit 1
fi

mkdir -p "$DIR"
chmod 700 "$DIR"
PASS="$(openssl rand -base64 30 | tr -d '/+=' | cut -c1-32)"

keytool -genkeypair -v -keystore "$KS" -alias "$ALIAS" -keyalg RSA -keysize 4096 \
  -validity 36500 -storepass "$PASS" -keypass "$PASS" \
  -dname "CN=shapeyourphone release" >/dev/null

printf '%s\n' "$PASS" > "$DIR/password.txt"
chmod 600 "$KS" "$DIR/password.txt"

base64 < "$KS" | tr -d '\n' | gh secret set SHAPE_KEYSTORE_B64 --repo "$REPO"
printf '%s' "$PASS" | gh secret set SHAPE_KEYSTORE_PASSWORD --repo "$REPO"
printf '%s' "$ALIAS" | gh secret set SHAPE_KEY_ALIAS --repo "$REPO"
printf '%s' "$PASS" | gh secret set SHAPE_KEY_PASSWORD --repo "$REPO"

echo "Done. Keystore and password are in $DIR — back them up somewhere safe."
echo "Release with: git tag v0.1.0 && git push origin v0.1.0"
