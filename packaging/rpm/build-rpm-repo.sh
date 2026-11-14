#!/usr/bin/env bash
# Build snipper.noarch.rpm, sign it, and create a signed dnf repository in <out>/rpm.
# Runs on Fedora (CI uses the fedora:41 container). Needs: rpm-build rpm-sign createrepo_c gnupg2 python3-devel
# Env: APT_SIGNING_KEY = fingerprint of the (already imported) signing key.
# Usage: packaging/rpm/build-rpm-repo.sh [out-dir]   (default: public-rpm)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
OUT="$(realpath -m "${1:-$ROOT/public-rpm}")"
KEY="${APT_SIGNING_KEY:?set APT_SIGNING_KEY to the signing key fingerprint}"
VERSION="$(python3 -c "import re;print(re.search(r'VERSION = \"(.+?)\"', open('$ROOT/snipper/settings.py').read()).group(1))")"

TOP="$(mktemp -d)"
trap 'rm -rf "$TOP"' EXIT
mkdir -p "$TOP/SOURCES"
tar -C "$ROOT" --exclude=__pycache__ --transform "s,^,snipper-$VERSION/," \
  -czf "$TOP/SOURCES/snipper-$VERSION.tar.gz" snipper data LICENSE
rpmbuild -bb --define "_topdir $TOP" --define "pkgversion $VERSION" "$ROOT/packaging/rpm/snipper.spec"

rm -rf "$OUT" && mkdir -p "$OUT/rpm/packages"
cp "$TOP"/RPMS/noarch/*.rpm "$OUT/rpm/packages/"

# sign packages (key has no passphrase; run gpg non-interactively)
rpmsign --addsign \
  --define "_gpg_name $KEY" \
  --define "_gpg_sign_cmd_extra_args --batch --pinentry-mode loopback" \
  "$OUT"/rpm/packages/*.rpm

# repository metadata + detached signature (repo_gpgcheck)
createrepo_c --quiet "$OUT/rpm"
gpg --batch --yes --pinentry-mode loopback --local-user "$KEY" \
  --armor --detach-sign "$OUT/rpm/repodata/repomd.xml"

# sanity check: the signature must verify with the published public key
rpmkeys --root "$TOP/verify" --initdb 2>/dev/null || mkdir -p "$TOP/verify"
gpg --batch --armor --export "$KEY" > "$TOP/key.asc"
rpmkeys --root "$TOP/verify" --import "$TOP/key.asc"
rpmkeys --root "$TOP/verify" --checksig "$OUT"/rpm/packages/*.rpm
echo "dnf repo written to $OUT/rpm"
