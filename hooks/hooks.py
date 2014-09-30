#!/usr/bin/python

#
# Copyright 2012 Canonical Ltd.
#
# Authors:
#  Andres Rodriguez <andres.rodriguez@canonical.com>
#

import shutil
import sys
import time
import os
from base64 import b64decode

import maas as MAAS
import pcmk
import hacluster

from charmhelpers.core.hookenv import (
    log,
    relation_get,
    related_units,
    relation_ids,
    relation_set,
    unit_get,
    config,
    Hooks, UnregisteredHookError,
    local_unit,
)

from charmhelpers.core.host import (
    service_stop,
    service_start,
    service_restart,
    service_running,
    lsb_release
)

from charmhelpers.fetch import (
    apt_install,
)

from charmhelpers.contrib.hahelpers.cluster import (
    peer_units,
    oldest_peer
)

hooks = Hooks()


@hooks.hook()
def install():
    if config('prefer-ipv6'):
        assert_charm_supports_ipv6()

    apt_install(['corosync', 'pacemaker', 'python-netaddr', 'ipmitool'],
                fatal=True)
    # XXX rbd OCF only included with newer versions of ceph-resource-agents.
    # Bundle /w charm until we figure out a better way to install it.
    if not os.path.exists('/usr/lib/ocf/resource.d/ceph'):
        os.makedirs('/usr/lib/ocf/resource.d/ceph')
    if not os.path.isfile('/usr/lib/ocf/resource.d/ceph/rbd'):
        shutil.copy('ocf/ceph/rbd', '/usr/lib/ocf/resource.d/ceph/rbd')


def get_corosync_conf():
    conf = {}
    if config('prefer-ipv6'):
        ip_version = 'ipv6'
        bindnetaddr = hacluster.get_ipv6_network_address
    else:
        ip_version = 'ipv4'
        bindnetaddr = hacluster.get_network_address

    for relid in relation_ids('ha'):
        for unit in related_units(relid):
            bindiface = relation_get('corosync_bindiface',
                                     unit, relid)
            if bindiface is None:
                log('No corosync_bindiface is set yet.')
                continue

            conf = {
                'corosync_bindnetaddr':
                bindnetaddr(bindiface),
                'corosync_mcastport': relation_get('corosync_mcastport',
                                                   unit, relid),
                'corosync_mcastaddr': config('corosync_mcastaddr'),
                'ip_version': ip_version,
            }

            if config('prefer-ipv6'):
                local_unit_no = int(local_unit().split('/')[1])
                # nodeid should not be 0
                conf['nodeid'] = local_unit_no + 1
                conf['netmtu'] = config('netmtu')

            if None not in conf.itervalues():
                return conf
    missing = [k for k, v in conf.iteritems() if v is None]
    log('Missing required principle configuration: %s' % missing)
    return None


def emit_corosync_conf():
    # read config variables
    corosync_conf_context = get_corosync_conf()
    # write config file (/etc/corosync/corosync.conf
    with open('/etc/corosync/corosync.conf', 'w') as corosync_conf:
        corosync_conf.write(render_template('corosync.conf',
                                            corosync_conf_context))


def emit_base_conf():
    corosync_default_context = {'corosync_enabled': 'yes'}
    # write /etc/default/corosync file
    with open('/etc/default/corosync', 'w') as corosync_default:
        corosync_default.write(render_template('corosync',
                                               corosync_default_context))
    corosync_key = config('corosync_key')
    if corosync_key:
        # write the authkey
        with open('/etc/corosync/authkey', 'w') as corosync_key_file:
            corosync_key_file.write(b64decode(corosync_key))
        os.chmod = ('/etc/corosync/authkey', 0o400)


@hooks.hook()
def config_changed():
    if config('prefer-ipv6'):
        assert_charm_supports_ipv6()

    corosync_key = config('corosync_key')
    if not corosync_key:
        log('CRITICAL',
            'No Corosync key supplied, cannot proceed')
        sys.exit(1)

    hacluster.enable_lsb_services('pacemaker')

    # Create a new config file
    emit_base_conf()

    # Reconfigure the cluster if required
    configure_cluster()

    # Setup fencing.
    configure_stonith()


@hooks.hook()
def upgrade_charm():
    install()
    config_changed()


def restart_corosync():
    if service_running("pacemaker"):
        service_stop("pacemaker")
    service_restart("corosync")
    time.sleep(5)
    service_start("pacemaker")

HAMARKER = '/var/lib/juju/haconfigured'


@hooks.hook('ha-relation-joined',
            'ha-relation-changed',
            'hanode-relation-joined',
            'hanode-relation-changed')
def configure_cluster():
    # Check that we are not already configured
    if os.path.exists(HAMARKER):
        log('HA already configured, not reconfiguring')
        return
    # Check that we are related to a principle and that
    # it has already provided the required corosync configuration
    if not get_corosync_conf():
        log('Unable to configure corosync right now, bailing')
        return
    else:
        log('Ready to form cluster - informing peers')
        relation_set(relation_id=relation_ids('hanode')[0],
                     ready=True)
    # Check that there's enough nodes in order to perform the
    # configuration of the HA cluster
    if (len(get_cluster_nodes()) <
            int(config('cluster_count'))):
        log('Not enough nodes in cluster, bailing')
        return

    relids = relation_ids('ha')
    if len(relids) == 1:  # Should only ever be one of these
        # Obtain relation information
        relid = relids[0]
        unit = related_units(relid)[0]
        log('Using rid {} unit {}'.format(relid, unit))
        import ast
        resources = \
            {} if relation_get("resources",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("resources",
                                               unit, relid))
        resource_params = \
            {} if relation_get("resource_params",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("resource_params",
                                               unit, relid))
        groups = \
            {} if relation_get("groups",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("groups",
                                               unit, relid))
        ms = \
            {} if relation_get("ms",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("ms",
                                               unit, relid))
        orders = \
            {} if relation_get("orders",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("orders",
                                               unit, relid))
        colocations = \
            {} if relation_get("colocations",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("colocations",
                                               unit, relid))
        clones = \
            {} if relation_get("clones",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("clones",
                                               unit, relid))
        init_services = \
            {} if relation_get("init_services",
                               unit, relid) is None \
            else ast.literal_eval(relation_get("init_services",
                                               unit, relid))

    else:
        log('Related to {} ha services'.format(len(relids)))
        return

    if True in [ra.startswith('ocf:openstack')
                for ra in resources.itervalues()]:
        apt_install('openstack-resource-agents')
    if True in [ra.startswith('ocf:ceph')
                for ra in resources.itervalues()]:
        apt_install('ceph-resource-agents')

    log('Configuring and restarting corosync')
    emit_corosync_conf()
    restart_corosync()

    log('Waiting for PCMK to start')
    pcmk.wait_for_pcmk()

    log('Doing global cluster configuration')
    cmd = "crm configure property stonith-enabled=false"
    pcmk.commit(cmd)
    cmd = "crm configure property no-quorum-policy=ignore"
    pcmk.commit(cmd)
    cmd = 'crm configure rsc_defaults $id="rsc-options"' \
          ' resource-stickiness="100"'
    pcmk.commit(cmd)

    # Configure Ping service
    monitor_host = config('monitor_host')
    if monitor_host:
        if not pcmk.crm_opt_exists('ping'):
            monitor_interval = config('monitor_interval')
            cmd = 'crm -w -F configure primitive ping' \
                  ' ocf:pacemaker:ping params host_list="%s"' \
                  ' multiplier="100" op monitor interval="%s"' %\
                  (monitor_host, monitor_interval)
            cmd2 = 'crm -w -F configure clone cl_ping ping' \
                   ' meta interleave="true"'
            pcmk.commit(cmd)
            pcmk.commit(cmd2)

    # Only configure the cluster resources
    # from the oldest peer unit.
    if oldest_peer(peer_units()):
        log('Configuring Resources')
        log(str(resources))
        for res_name, res_type in resources.iteritems():
            # disable the service we are going to put in HA
            if res_type.split(':')[0] == "lsb":
                hacluster.disable_lsb_services(res_type.split(':')[1])
                if service_running(res_type.split(':')[1]):
                    service_stop(res_type.split(':')[1])
            elif (len(init_services) != 0 and
                  res_name in init_services and
                  init_services[res_name]):
                hacluster.disable_upstart_services(init_services[res_name])
                if service_running(init_services[res_name]):
                    service_stop(init_services[res_name])
            # Put the services in HA, if not already done so
            # if not pcmk.is_resource_present(res_name):
            if not pcmk.crm_opt_exists(res_name):
                if res_name not in resource_params:
                    cmd = 'crm -w -F configure primitive %s %s' % (res_name,
                                                                   res_type)
                else:
                    cmd = 'crm -w -F configure primitive %s %s %s' % \
                        (res_name,
                         res_type,
                         resource_params[res_name])
                pcmk.commit(cmd)
                log('%s' % cmd)
                if monitor_host:
                    cmd = 'crm -F configure location Ping-%s %s rule' \
                          ' -inf: pingd lte 0' % (res_name, res_name)
                    pcmk.commit(cmd)

        log('Configuring Groups')
        log(str(groups))
        for grp_name, grp_params in groups.iteritems():
            if not pcmk.crm_opt_exists(grp_name):
                cmd = 'crm -w -F configure group %s %s' % (grp_name,
                                                           grp_params)
                pcmk.commit(cmd)
                log('%s' % cmd)

        log('Configuring Master/Slave (ms)')
        log(str(ms))
        for ms_name, ms_params in ms.iteritems():
            if not pcmk.crm_opt_exists(ms_name):
                cmd = 'crm -w -F configure ms %s %s' % (ms_name, ms_params)
                pcmk.commit(cmd)
                log('%s' % cmd)

        log('Configuring Orders')
        log(str(orders))
        for ord_name, ord_params in orders.iteritems():
            if not pcmk.crm_opt_exists(ord_name):
                cmd = 'crm -w -F configure order %s %s' % (ord_name,
                                                           ord_params)
                pcmk.commit(cmd)
                log('%s' % cmd)

        log('Configuring Colocations')
        log(str(colocations))
        for col_name, col_params in colocations.iteritems():
            if not pcmk.crm_opt_exists(col_name):
                cmd = 'crm -w -F configure colocation %s %s' % (col_name,
                                                                col_params)
                pcmk.commit(cmd)
                log('%s' % cmd)

        log('Configuring Clones')
        log(str(clones))
        for cln_name, cln_params in clones.iteritems():
            if not pcmk.crm_opt_exists(cln_name):
                cmd = 'crm -w -F configure clone %s %s' % (cln_name,
                                                           cln_params)
                pcmk.commit(cmd)
                log('%s' % cmd)

        for res_name, res_type in resources.iteritems():
            if len(init_services) != 0 and res_name in init_services:
                # Checks that the resources are running and started.
                # Ensure that clones are excluded as the resource is
                # not directly controllable (dealt with below)
                # Ensure that groups are cleaned up as a whole rather
                # than as individual resources.
                if (res_name not in clones.values() and
                    res_name not in groups.values() and
                        not pcmk.crm_res_running(res_name)):
                    # Just in case, cleanup the resources to ensure they get
                    # started in case they failed for some unrelated reason.
                    cmd = 'crm resource cleanup %s' % res_name
                    pcmk.commit(cmd)

        for cl_name in clones:
            # Always cleanup clones
            cmd = 'crm resource cleanup %s' % cl_name
            pcmk.commit(cmd)

        for grp_name in groups:
            # Always cleanup groups
            cmd = 'crm resource cleanup %s' % grp_name
            pcmk.commit(cmd)

    for rel_id in relation_ids('ha'):
        relation_set(relation_id=rel_id,
                     clustered="yes")

    with open(HAMARKER, 'w') as marker:
        marker.write('done')

    configure_stonith()


def configure_stonith():
    if config('stonith_enabled') not in ['true', 'True']:
        return

    if not os.path.exists(HAMARKER):
        log('HA not yet configured, skipping STONITH config.')
        return

    log('Configuring STONITH for all nodes in cluster.')
    # configure stontih resources for all nodes in cluster.
    # note: this is totally provider dependent and requires
    # access to the MAAS API endpoint, using endpoint and credentials
    # set in config.
    url = config('maas_url')
    creds = config('maas_credentials')
    if None in [url, creds]:
        log('maas_url and maas_credentials must be set'
            ' in config to enable STONITH.')
        sys.exit(1)

    maas = MAAS.MAASHelper(url, creds)
    nodes = maas.list_nodes()
    if not nodes:
        log('Could not obtain node inventory from '
            'MAAS @ %s.' % url)
        sys.exit(1)

    cluster_nodes = pcmk.list_nodes()
    for node in cluster_nodes:
        rsc, constraint = pcmk.maas_stonith_primitive(nodes, node)
        if not rsc:
            log('Failed to determine STONITH primitive for node'
                ' %s' % node)
            sys.exit(1)

        rsc_name = str(rsc).split(' ')[1]
        if not pcmk.is_resource_present(rsc_name):
            log('Creating new STONITH primitive %s.' %
                rsc_name)
            cmd = 'crm -F configure %s' % rsc
            pcmk.commit(cmd)
            if constraint:
                cmd = 'crm -F configure %s' % constraint
                pcmk.commit(cmd)
        else:
            log('STONITH primitive already exists '
                'for node.')

    cmd = "crm configure property stonith-enabled=true"
    pcmk.commit(cmd)


def get_cluster_nodes():
    hosts = []
    hosts.append(unit_get('private-address'))
    for relid in relation_ids('hanode'):
        for unit in related_units(relid):
            if relation_get('ready',
                            rid=relid,
                            unit=unit):
                hosts.append(relation_get('private-address',
                                          unit, relid))
    hosts.sort()
    return hosts

TEMPLATES_DIR = 'templates'

try:
    import jinja2
except ImportError:
    apt_install('python-jinja2', fatal=True)
    import jinja2


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir)
    )
    template = templates.get_template(template_name)
    return template.render(context)


def assert_charm_supports_ipv6():
    """Check whether we are able to support charms ipv6."""
    if lsb_release()['DISTRIB_CODENAME'].lower() < "trusty":
        raise Exception("IPv6 is not supported in the charms for Ubuntu "
                        "versions less than Trusty 14.04")


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
