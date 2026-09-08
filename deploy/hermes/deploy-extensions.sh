#!/usr/bin/env bash
set -euo pipefail
cd /home/ubuntu/haudi-hermes
venv/bin/python deploy-extensions.py --archive extensions.zip
