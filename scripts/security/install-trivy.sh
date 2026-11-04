#!/usr/bin/env bash
# Official release asset, pinned version and digest. No get.trivy.dev dependency.
set -euo pipefail
version=0.70.0
sha256=8b4376d5d6befe5c24d503f10ff136d9e0c49f9127a4279fd110b727929a5aa9
install_dir=${1:?usage: install-trivy.sh INSTALL_DIR}
case "$(uname -s):$(uname -m)" in
  Linux:x86_64) ;;
  *) echo 'Only the pinned Ubuntu x86_64 CI runner is supported' >&2; exit 1 ;;
esac
work=$(mktemp -d)
trap 'rm -rf "$work"' EXIT
archive=trivy_${version}_Linux-64bit.tar.gz
curl --fail --show-error --location --retry 3 \
  "https://github.com/aquasecurity/trivy/releases/download/v${version}/${archive}" \
  --output "$work/$archive"
printf '%s  %s\n' "$sha256" "$work/$archive" | sha256sum --check --status
mkdir -p "$install_dir"
tar -xzf "$work/$archive" -C "$work" trivy
install -m 0755 "$work/trivy" "$install_dir/trivy"
"$install_dir/trivy" --version
