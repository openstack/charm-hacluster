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
    utils.install('corosync', 'pacemaker', 'openstack-resource-agents', 'python-netaddr')
    utils.enable_lsb_services('pacemaker')
    utils.juju_log('INFO', 'End install hook.')


def get_corosync_conf():
    for relid in utils.relation_ids('ha'):
        for unit in utils.relation_list(relid):
            conf = {
                'corosync_bindnetaddr': utils.get_network_address(
                                          utils.relation_get('corosync_bindiface',
                                          unit, relid)),
                'corosync_mcastport': utils.relation_get('corosync_mcastport',
                                        unit, relid),
                'corosync_mcastaddr': utils.config_get('corosync_mcastaddr'),
                'corosync_pcmk_ver': utils.config_get('corosync_pcmk_ver'),
                }
            if None not in conf.itervalues():
                return conf
    return None


def emit_corosync_conf():
    # read config variables
    corosync_conf_context = get_corosync_conf()

    # write config file (/etc/corosync/corosync.conf
    with open('/etc/corosync/corosync.conf', 'w') as corosync_conf:
        corosync_conf.write(utils.render_template('corosync.conf', corosync_conf_context))


def emit_base_conf():
    corosync_default_context = {'corosync_enabled': 'yes'}
    # write /etc/default/corosync file
    with open('/etc/default/corosync', 'w') as corosync_default:
        corosync_default.write(utils.render_template('corosync', corosync_default_context))

    # write the authkey
    corosync_key=utils.config_get('corosync_key')
    with open(corosync_key, 'w') as corosync_key_file:
        corosync_key_file.write(corosync_key)


def config_changed():
    utils.juju_log('INFO', 'Begin config-changed hook.')

    corosync_key = utils.config_get('corosync_key')
    if corosync_key == '':
        utils.juju_log('CRITICAL',
                       'No Corosync key supplied, cannot proceed')
        sys.exit(1)

    # Create a new config file
    emit_base_conf()

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

    # Only start pacemaker after making sure
    # corosync has been started
    # Wait a few seconds for corosync to start.
    time.sleep(2)
    if utils.running("corosync"):
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

    if utils.relation_get("corosync_bindiface") is None:
        return
    elif utils.relation_get("corosync_mcastport") is None:
        return
    else:
        emit_corosync_conf()
        utils.restart("corosync")
        time.sleep(2)
        utils.restart("pacemaker")

    # Check that there's enough nodes in order to perform the
    # configuration of the HA cluster
    if len(get_cluster_nodes()) < 2:
        return
    else:
        utils.juju_log('INFO', 'hanode-relation: Waiting for PCMK to start')
        pcmk.wait_for_pcmk()

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
    utils.juju_log('INFO', 'ha-relation: Configuring Resources')
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
        #if not pcmk.is_resource_present(res_name):
        if not pcmk.crm_opt_exists(res_name):
            if resource_params[res_name] is None:
                cmd = 'crm -F configure primitive %s %s' % (res_name, res_type)
            else:
                cmd = 'crm -F configure primitive %s %s %s' % (res_name, res_type, resource_params[res_name])
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    # Configuring groups
    utils.juju_log('INFO', 'ha-relation: Configuring Groups')
    for grp_name, grp_params in groups.iteritems():
        if not pcmk.crm_opt_exists(grp_name):
            cmd = 'crm -F configure group %s %s' % (grp_name, grp_params)
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    # Configuring ordering
    utils.juju_log('INFO', 'ha-relation: Configuring Orders')
    for ord_name, ord_params in orders.iteritems():
        if not pcmk.crm_opt_exists(ord_name):
            cmd = 'crm -F configure order %s %s' % (ord_name, ord_params)
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    # Configuring colocations
    utils.juju_log('INFO', 'ha-relation: Configuring Colocations')
    for col_name, col_params in colocations.iteritems():
        if not pcmk.crm_opt_exists(col_name):
            cmd = 'crm -F configure colocation %s %s' % (col_name, col_params)
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    # Configuring clones
    utils.juju_log('INFO', 'ha-relation: Configuring Clones')
    for cln_name, cln_params in clones.iteritems():
        if not pcmk.crm_opt_exists(cln_name):
            cmd = 'crm -F configure clone %s %s' % (cln_name, cln_params)
            pcmk.commit(cmd)
            utils.juju_log('INFO', '%s' % cmd)

    for res_name,res_type in resources.iteritems():
        # TODO: This should first check that the resources is running
        if len(init_services) != 0 and res_name in init_services:
            # If the resource is in HA already, and it is a service, restart
            # the pcmk resource as the config file might have changed by the
            # principal charm
            cmd = 'crm resource restart %s' % res_name
            pcmk.commit(cmd)

    utils.juju_log('INFO', 'End ha relation joined/changed hook')


def ha_relation_departed():
    # TODO: Fin out which node is departing and put it in standby mode.
    # If this happens, and a new relation is created in the same machine
    # (which already has node), then check whether it is standby and put it
    # in online mode. This should be done in ha_relation_joined.
    pcmk.standby(utils.get_unit_hostname())


def get_cluster_nodes():
    hosts = []
    hosts.append('{}:6789'.format(utils.get_host_ip()))

    for relid in utils.relation_ids('hanode'):
        for unit in utils.relation_list(relid):
            hosts.append(
                '{}:6789'.format(utils.get_host_ip(
                                    utils.relation_get('private-address',
                                                       unit, relid)))
                )

    hosts.sort()
    return hosts


def hanode_relation():
    utils.juju_log('INFO', 'Begin hanode peer relation hook')
    if len(get_cluster_nodes()) >= 2:
        utils.juju_log('INFO', 'hanode-relation: Waiting for PCMK to start')
        pcmk.wait_for_pcmk()

        utils.juju_log('INFO', 'hanode-relation: Doing global configuration')
        cmd = "crm configure property stonith-enabled=false"
        pcmk.commit(cmd)
        cmd = "crm configure property no-quorum-policy=ignore"
        pcmk.commit(cmd)
        cmd = 'crm configure rsc_defaults $id="rsc-options" resource-stickiness="100"'
        pcmk.commit(cmd)


utils.do_hooks({
        'install': install,
        'config-changed': config_changed,
        'start': start,
        'stop': stop,
        'upgrade-charm': upgrade_charm,
        'ha-relation-joined': ha_relation,
        'ha-relation-changed': ha_relation,
        'ha-relation-departed': ha_relation_departed,
        'hanode-relation-joined': hanode_relation,
        #'hanode-relation-departed': hanode_relation_departed, # TODO: should probably remove nodes from the cluster
        })

sys.exit(0)
