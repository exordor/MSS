#!/bin/bash
URL=$1
DEST=$2

git submodule add $URL $DEST
git submodule update --init --recursive
git add .gitmodules $DEST
git commit -m "Add submodule: $DEST"
