#!/usr/bin/python

#
# Copyright 2012 Canonical Ltd.
#
# Authors:
#  Andres Rodriguez <andres.rodriguez@canonical.com>
#

import glob
import os
import subprocess
import shutil
import sys
import time

import utils
import pcmk


def install():
    utils.juju_log('INFO', 'Begin install hook.')
    utils.configure_source()
    utils.install('corosync', 'pacemaker', 'openstack-resource-agents')
    utils.juju_log('INFO', 'End install hook.')


def emit_corosync_conf():
    # read config variables
    corosync_conf_context = {
        'corosync_bindnetaddr': utils.config_get('corosync_bindnetaddr'),
        'corosync_mcastaddr': utils.config_get('corosync_mcastaddr'),
        'corosync_mcastport': utils.config_get('corosync_mcastport'),
        'corosync_pcmk_ver': utils.config_get('corosync_pcmk_ver'),
        }

    # write /etc/default/corosync file
    with open('/etc/default/corosync', 'w') as corosync_default:
        corosync_default.write(utils.render_template('corosync', corosync_conf_context))

    # write config file (/etc/corosync/corosync.conf
    with open('/etc/corosync/corosync.conf', 'w') as corosync_conf:
        corosync_conf.write(utils.render_template('corosync.conf', corosync_conf_context))

    # write the authkey
    corosync_key=utils.config_get('corosync_key')
    with open(corosync_key, 'w') as corosync_key_file:
        corosync_key_file.write(corosync_key)


def config_changed():
    utils.juju_log('INFO', 'Begin config-changed hook.')

    # validate configuration options
    corosync_bindnetaddr = utils.config_get('corosync_bindnetaddr')
    if corosync_bindnetaddr == '':
        utils.juju_log('CRITICAL', 'No bindnetaddr supplied, cannot proceed.')
        sys.exit(1)

    corosync_key = utils.config_get('corosync_key')
    if corosync_key == '':
        utils.juju_log('CRITICAL',
                       'No Corosync key supplied, cannot proceed')
        sys.exit(1)

    # Create a new config file
    emit_corosync_conf()

    utils.juju_log('INFO', 'End config-changed hook.')


def upgrade_charm():
    utils.juju_log('INFO', 'Begin upgrade-charm hook.')
    emit_corosync_conf()
    utils.juju_log('INFO', 'End upgrade-charm hook.')


def start():
    if utils.running("corosync"):
        utils.restart("corosync")
    else:
        utils.start("corosync")

    # TODO: Only start pacemaker after making sure
    # corosync has been started
    # Wait a few seconds for corosync to start.
    time.sleep(2)
    if utils.running("pacemaker"):
        utils.restart("pacemaker")
    else:
        utils.start("pacemaker")


def stop():
    service("corosync", "stop")
    time.sleep(2)
    service("pacemaker", "stop")


def ha_relation():
    utils.juju_log('INFO', 'Begin ha relation joined/changed hook')

    pcmk.wait_for_pcmk()

    cmd = "crm configure property stonith-enabled=false"
    pcmk.commit(cmd)
    cmd = "crm configure property no-quorum-policy=ignore"
    pcmk.commit(cmd)
    cmd = 'crm configure rsc_defaults $id="rsc-options" resource-stickiness="100"'
    pcmk.commit(cmd)

    # Obtain relation information
    import ast
    resources = {} if utils.relation_get("resources") is None else ast.literal_eval(utils.relation_get("resources"))
    resource_params = {} if utils.relation_get("resource_params") is None else ast.literal_eval(utils.relation_get("resource_params"))
    groups = {} if utils.relation_get("groups") is None else ast.literal_eval(utils.relation_get("groups"))
    orders = {} if utils.relation_get("orders") is None else ast.literal_eval(utils.relation_get("orders"))
    colocations = {} if utils.relation_get("colocations") is None else ast.literal_eval(utils.relation_get("colocations"))
    clones = {} if utils.relation_get("clones") is None else ast.literal_eval(utils.relation_get("clones"))
    init_services = {} if utils.relation_get("init_services") is None else ast.literal_eval(utils.relation_get("init_services"))

    # Configuring the Resource
    for res_name,res_type in resources.iteritems():
        # disable the service we are going to put in HA
        if res_type.split(':')[0] == "lsb":
            utils.disable_lsb_services(res_type.split(':')[1])
            if utils.running(res_type.split(':')[1]):
                utils.stop(res_type.split(':')[1])
        elif len(init_services) != 0 and res_name in init_services and init_services[res_name]:
            utils.disable_upstart_services(init_services[res_name])
            if utils.running(init_services[res_name]):
                utils.stop(init_services[res_name])
        # Put the services in HA, if not already done so
        if not pcmk.is_resource_present(res_name):
            if resource_params[res_name] is None:
                cmd = 'crm -F configure primitive %s %s' % (res_name, res_type)
            else:
                cmd = 'crm -F configure primitive %s %s %s' % (res_name, res_type, resource_params[res_name])
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    # Configuring groups
    for grp_name, grp_params in groups.iteritems():
        cmd = 'crm -F configure group %s %s' % (grp_name, grp_params)
        pcmk.commit(cmd)
        utils.juju_log('INFO', '%s' % cmd)

    # Configuring ordering
    for ord_name, ord_params in orders.iteritems():
        cmd = 'crm -F configure order %s %s' % (ord_name, ord_params)
        pcmk.commit(cmd)
        utils.juju_log('INFO', '%s' % cmd)

    # Configuring colocations
    for col_name, col_params in colocations.iteritems():
        cmd = 'crm -F configure colocation %s %s' % (col_name, col_params)
        pcmk.commit(cmd)
        utils.juju_log('INFO', '%s' % cmd)

    # Configuring clones
    for cln_name, cln_params in clones.iteritems():
        cmd = 'crm -F configure clone %s %s' % (cln_name, cln_params)
        pcmk.commit(cmd)
        utils.juju_log('INFO', '%s' % cmd)

    utils.juju_log('INFO', 'End ha relation joined/changed hook')


def ha_relation_departed():
    # TODO: Fin out which node is departing and put it in standby mode.
    # If this happens, and a new relation is created in the same machine
    # (which already has node), then check whether it is standby and put it
    # in online mode. This should be done in ha_relation_joined.
    cmd = "crm -F node standby %s" % utils.get_unit_hostname()
    pcmk.commit(cmd)


utils.do_hooks({
        'config-changed': config_changed,
        'install': install,
        'start': start,
        'stop': stop,
        'upgrade-charm': upgrade_charm,
        'ha-relation-joined': ha_relation,
        'ha-relation-changed': ha_relation,
        'ha-relation-departed': ha_relation_departed,
        #'hanode-relation-departed': hanode_relation_departed, # TODO: should probably remove nodes from the cluster
        })

sys.exit(0)
