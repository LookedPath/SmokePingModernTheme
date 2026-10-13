#!/usr/bin/env python3
"""Create a portable release containing only the theme, installer, and documentation."""
from pathlib import Path
import tarfile

root = Path(__file__).resolve().parents[1]
output = root / 'dist/smokeping-atlas-1.1.0.tar.gz'
output.parent.mkdir(exist_ok=True)
with tarfile.open(output, 'w:gz') as archive:
    for name in ('theme', 'server', 'tools/install.py', 'README.md', 'LICENSE', 'docs/screenshots'):
        archive.add(root / name, arcname='smokeping-atlas/'+name, filter=lambda item: None if '__pycache__' in item.name or item.name.endswith('.pyc') else item)
print(output)
