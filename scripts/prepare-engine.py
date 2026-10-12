#!/usr/bin/env python3
"""Fetch and verify the fixed official OFIQ bundle outside the source tree."""
import argparse
import hashlib
import urllib.request
from pathlib import Path
from zipfile import ZipFile

URL = 'https://resources.eulisa.europa.eu/research/OFIQ-PrecompiledBinaries.zip'
SHA256 = 'c8996f37246731d7bd195697da04542b97cdf4e34a5d43ea1ab6a3138c4620ce'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    args.directory.mkdir(parents=True, exist_ok=True)
    archive = args.directory / 'upstream.zip'
    if not archive.exists():
        urllib.request.urlretrieve(URL, archive)
    with archive.open('rb') as f:
        digest = hashlib.file_digest(f, 'sha256').hexdigest()
    if digest != SHA256:
        raise SystemExit('官方下载内容与固定版本不符；请保留旧包并审核版本，不能自动升级。')
    with ZipFile(archive) as bundle:
        prefixes = ('releases/ubuntu_x86_64/', 'source/OFIQlib/include/',
                    'source/data/models/')
        exact = ('source/data/ofiq_config.jaxn', 'source/LICENSE.md', 'source/Version.txt')
        for item in bundle.infolist():
            relative = item.filename.removeprefix('OFIQ-Release/')
            if not item.is_dir() and (relative.startswith(prefixes) or relative in exact):
                path = args.directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(bundle.read(item))
    print('OFIQ 1.0.3 bundle verified and extracted:', args.directory)


if __name__ == '__main__':
    main()
