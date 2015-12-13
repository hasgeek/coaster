#!/bin/sh
coverage run `which nosetests`
coverage report
