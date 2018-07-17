#!/bin/bash
chmod +x /opt/cms/deploy/setup.sh
exec sudo /usr/bin/systemd-run -P -p User=deploy -p MemoryMax= /opt/cms/deploy/setup.sh
