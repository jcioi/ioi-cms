#!/bin/bash
set -xe
cd /opt/cms
chmod +x ./deploy/*.sh
./deploy/chmod.sh
if [ ! -e /opt/cms_venv/.built-on-codebuild  ];then
  ./deploy/install-deps.sh
fi
