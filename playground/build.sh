#!/bin/sh
set -eu
rm -rf _site
mkdir _site
cp playground/index.html playground/app.js playground/worker.js playground/style.css playground/playground.py _site/
set -- dist/*.whl
if [ "$#" -ne 1 ] || [ ! -f "$1" ]; then
  echo "Expected exactly one wheel in dist/." >&2
  exit 1
fi
cp "$1" _site/
basename "$1" > _site/wheel.txt
