#!/bin/bash

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
  echo "Run this script with: source ./start.sh"
  echo "That is required to keep .venv active in your current shell."
  exit 1
fi

python3 -m venv .venv && source .venv/bin/activate && python -m pip install -U pip && python -m pip install -e .
