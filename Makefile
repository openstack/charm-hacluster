#!/usr/bin/make
PYTHON := /usr/bin/env python

lint:
	@flake8 --exclude hooks/charmhelpers hooks unit_tests tests
	@charm proof

unit_test:
	@echo Starting unit tests...
	@$(PYTHON) /usr/bin/nosetests --nologcapture --with-coverage  unit_tests

test:
	@echo Starting Amulet tests...
ifndef OS_CHARMS_AMULET_VIP
	@echo "WARNING: HA tests require OS_CHARMS_AMULET_VIP set to usable vip address"
endif
	# coreycb note: The -v should only be temporary until Amulet sends
	# raise_status() messages to stderr:
	#   https://bugs.launchpad.net/amulet/+bug/1320357
	@juju test -v -p AMULET_HTTP_PROXY,OS_CHARMS_AMULET_VIP --timeout 900 \
		00-setup 15-basic-trusty-icehouse

bin/charm_helpers_sync.py:
	@mkdir -p bin
	@bzr cat lp:charm-helpers/tools/charm_helpers_sync/charm_helpers_sync.py \
	> bin/charm_helpers_sync.py

sync: bin/charm_helpers_sync.py
	@$(PYTHON) bin/charm_helpers_sync.py -c charm-helpers-hooks.yaml
	@$(PYTHON) bin/charm_helpers_sync.py -c charm-helpers-tests.yaml

publish: lint unit_test
	bzr push lp:charms/hacluster
	bzr push lp:charms/trusty/hacluster
