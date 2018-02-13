#!/bin/sh
set -e
export FLASK_ENV="TESTING"
coverage run -m pytest "$@"
coverage report -m
