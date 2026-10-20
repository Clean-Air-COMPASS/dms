#!/bin/sh
set -eu

# A running Nginx process alone does not mean CompassAQ can start in a browser.
wget -q -T 2 -O - http://127.0.0.1/ | grep -q '<div id="root">'
wget -q -T 2 -O - http://127.0.0.1/api/health/readiness | grep -q '"status":"ready"'
