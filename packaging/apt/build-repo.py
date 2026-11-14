#!/usr/bin/env python3
"""Build a signed APT repository (for GitHub Pages or any static host) from .deb files.

Usage:
  REPO_URL=https://<user>.github.io/<repo> python3 packaging/apt/build-repo.py [--out public] [deb ...]

Signing: uses the GPG key in $GNUPGHOME (or the default keyring); pick one with $APT_SIGNING_KEY.
Only needs python3, dpkg-deb and gpg (no reprepro/apt-ftparchive).

Layout produced:
  public/
    install.sh                       one-time setup: adds the repo + key, then installs snipper
    snipper-archive-keyring.gpg      binary keyring (for Signed-By)
    snipper-archive-keyring.asc      same key, armored
    snipper.sources                  deb822 source entry
    pool/main/s/snipper/*.deb
    dists/stable/{Release,InRelease,Release.gpg}
    dists/stable/main/binary-{amd64,arm64}/Packages(.gz)
    index.html
"""
from __future__ import annotations

import argparse
import email.utils
import glob
import gzip
import hashlib
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
SUITE = "stable"
COMPONENT = "main"
ARCHES = ("amd64", "arm64")  # Architecture: all packages are listed for each


def control_fields(deb):
    out = subprocess.check_output(["dpkg-deb", "-f", deb], text=True)
    return out.rstrip("\n")


def hashes(path):
    data = open(path, "rb").read()
    return {
        "MD5sum": hashlib.md5(data).hexdigest(),
        "SHA1": hashlib.sha1(data).hexdigest(),
        "SHA256": hashlib.sha256(data).hexdigest(),
        "Size": str(len(data)),
    }


def gpg(*args):
    cmd = ["gpg", "--batch", "--yes", "--pinentry-mode", "loopback"]
    key = os.environ.get("APT_SIGNING_KEY")
    if key:
        cmd += ["--local-user", key]
    subprocess.check_call(cmd + list(args))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=os.path.join(ROOT, "public"))
    ap.add_argument("debs", nargs="*")
    args = ap.parse_args()

    repo_url = os.environ.get("REPO_URL", "").rstrip("/")
    if not repo_url:
        sys.exit("Set REPO_URL, e.g. REPO_URL=https://<user>.github.io/<repo>")
    debs = args.debs or sorted(glob.glob(os.path.join(ROOT, "dist", "*.deb")))
    if not debs:
        sys.exit("No .deb found; run packaging/deb/build-deb.sh first")

    out = args.out
    if os.path.isdir(out):
        shutil.rmtree(out)
    pool = os.path.join(out, "pool", COMPONENT, "s", "snipper")
    os.makedirs(pool)

    entries = []
    for deb in debs:
        name = os.path.basename(deb)
        dest = os.path.join(pool, name)
        shutil.copy2(deb, dest)
        h = hashes(dest)
        rel = os.path.relpath(dest, out)
        entry = control_fields(dest) + f"\nFilename: {rel}\nSize: {h['Size']}\n"
        entry += f"MD5sum: {h['MD5sum']}\nSHA1: {h['SHA1']}\nSHA256: {h['SHA256']}\n"
        entries.append(entry)
    packages = "\n".join(entries)

    dist = os.path.join(out, "dists", SUITE)
    index_files = []
    for arch in ARCHES:
        d = os.path.join(dist, COMPONENT, f"binary-{arch}")
        os.makedirs(d)
        p = os.path.join(d, "Packages")
        with open(p, "w") as f:
            f.write(packages)
        with open(p, "rb") as src, gzip.GzipFile(p + ".gz", "wb", mtime=0) as dst:
            dst.write(src.read())
        index_files += [p, p + ".gz"]

    release = [
        "Origin: Snipper",
        "Label: Snipper",
        f"Suite: {SUITE}",
        f"Codename: {SUITE}",
        f"Date: {email.utils.formatdate(usegmt=True)}",
        f"Architectures: {' '.join(ARCHES)}",
        f"Components: {COMPONENT}",
        "Description: Snipper - screenshot & annotation tool for Ubuntu",
    ]
    for algo, field in (("MD5Sum", "MD5sum"), ("SHA1", "SHA1"), ("SHA256", "SHA256")):
        release.append(f"{algo}:")
        for f in index_files:
            h = hashes(f)
            release.append(f" {h[field]} {int(h['Size']):>8} {os.path.relpath(f, dist)}")
    rel_path = os.path.join(dist, "Release")
    with open(rel_path, "w") as f:
        f.write("\n".join(release) + "\n")
    gpg("--clearsign", "-o", os.path.join(dist, "InRelease"), rel_path)
    gpg("--armor", "--detach-sign", "-o", os.path.join(dist, "Release.gpg"), rel_path)

    # keys: export exactly the signing key
    key = os.environ.get("APT_SIGNING_KEY")
    export = ["gpg", "--batch", "--export"] + ([key] if key else [])
    keyring = subprocess.check_output(export)
    if not keyring:
        sys.exit("Signing key not found in the GPG keyring")
    open(os.path.join(out, "snipper-archive-keyring.gpg"), "wb").write(keyring)
    armored = subprocess.check_output(["gpg", "--batch", "--armor", "--export"] + ([key] if key else []))
    open(os.path.join(out, "snipper-archive-keyring.asc"), "wb").write(armored)

    sources = (
        "Types: deb\n"
        f"URIs: {repo_url}\n"
        f"Suites: {SUITE}\n"
        f"Components: {COMPONENT}\n"
        "Signed-By: /usr/share/keyrings/snipper-archive-keyring.gpg\n"
    )
    open(os.path.join(out, "snipper.sources"), "w").write(sources)

    template = open(os.path.join(HERE, "setup.sh.in")).read()
    setup = os.path.join(out, "install.sh")
    open(setup, "w").write(template.replace("@REPO_URL@", repo_url))
    os.chmod(setup, 0o755)

    html = open(os.path.join(HERE, "index.html.in")).read().replace("@REPO_URL@", repo_url)
    open(os.path.join(out, "index.html"), "w").write(html)
    open(os.path.join(out, ".nojekyll"), "w").close()  # serve files as-is on GitHub Pages
    print(f"APT repo written to {out} ({len(debs)} package(s)) for {repo_url}")


if __name__ == "__main__":
    main()
