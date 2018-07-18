#!/bin/bash
set -xe
python3 -m venv /opt/cms_venv
source /opt/cms_venv/bin/activate
pip install --no-cache-dir -r requirements.txt
./setup.py install
./prerequisites.py build_l10n
