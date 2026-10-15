"""Package Drape into an installable extension zip.

Usage:  python build_drape.py
Output: dist/drape-<version>.zip

Extension zips must contain the manifest at the zip root (no wrapping
folder), unlike legacy addon zips.
"""

import os
import re
import sys
import zipfile

ADDON_DIR = "drape"
DIST_DIR = "dist"

EXCLUDE = ("__pycache__", ".pyc", ".pyo", ".DS_Store", "Thumbs.db")


def read_version():
    manifest = os.path.join(ADDON_DIR, "blender_manifest.toml")
    with open(manifest, "r", encoding="utf-8") as f:
        m = re.search(r'^version\s*=\s*"([^"]+)"', f.read(), re.M)
    return m.group(1) if m else "0.0.0"


def build():
    if not os.path.isdir(ADDON_DIR):
        print(f"ERROR: '{ADDON_DIR}' not found. Run from the project root.")
        sys.exit(1)

    os.makedirs(DIST_DIR, exist_ok=True)
    version = read_version()
    output = os.path.join(DIST_DIR, f"drape-{version}.zip")

    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as zf:
        for root, dirs, files in os.walk(ADDON_DIR):
            dirs[:] = [d for d in dirs if d not in ("__pycache__",)]
            for fname in files:
                fpath = os.path.join(root, fname)
                if any(pat in fpath for pat in EXCLUDE):
                    continue
                arcname = os.path.relpath(fpath, ADDON_DIR)  # manifest at zip root
                zf.write(fpath, arcname)
                print(f"  + {arcname}")

    print(f"\nBuilt: {output}")
    return output


if __name__ == "__main__":
    build()
