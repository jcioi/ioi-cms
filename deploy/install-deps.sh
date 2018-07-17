#!/bin/bash
set -xe
cd /opt/cms
python -m venv /opt/cms_venv
source /opt/cms_venv/bin/activate
pip install --no-cache-dir -r requirements.txt
./setup.py install
./prerequisites.py build_l10n
