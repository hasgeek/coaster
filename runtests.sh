#!/bin/sh
export FLASK_ENV="TESTING"
coverage run `which nosetests`
coverage report
