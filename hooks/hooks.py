#!/usr/bin/python
#
# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import shutil
import os
import sys
import glob

import pcmk
import socket

from charmhelpers.core.hookenv import (
    log,
    DEBUG,
    INFO,
    related_units,
    relation_ids,
    relation_get,
    relation_set,
    config,
    Hooks,
    UnregisteredHookError,
    local_unit,
    status_set,
)

from charmhelpers.core.host import (
    service_stop,
    service_running,
    lsb_release,
    CompareHostReleases,
)

from charmhelpers.fetch import (
    apt_install,
    apt_purge,
    filter_installed_packages,
)

from charmhelpers.contrib.hahelpers.cluster import (
    peer_units,
    oldest_peer
)

from utils import (
    get_corosync_conf,
    assert_charm_supports_ipv6,
    get_cluster_nodes,
    parse_data,
    configure_corosync,
    configure_stonith,
    configure_monitor_host,
    configure_cluster_global,
    enable_lsb_services,
    disable_lsb_services,
    disable_upstart_services,
    get_ipv6_addr,
    validate_dns_ha,
    setup_maas_api,
    setup_ocf_files,
    set_unit_status,
    ocf_file_exists,
    kill_legacy_ocf_daemon_process,
    try_pcmk_wait,
)

from charmhelpers.contrib.charmsupport import nrpe
from charmhelpers.contrib.network.ip import (
    is_ipv6,
)

hooks = Hooks()

PACKAGES = ['corosync', 'pacemaker', 'python-netaddr', 'ipmitool']
COROSYNC_CONF = '/etc/corosync/corosync.conf'
COROSYNC_DEFAULT = '/etc/default/corosync'
COROSYNC_AUTHKEY = '/etc/corosync/authkey'

COROSYNC_CONF_FILES = [
    COROSYNC_DEFAULT,
    COROSYNC_AUTHKEY,
    COROSYNC_CONF
]

PACKAGES = ['corosync', 'pacemaker', 'python-netaddr', 'ipmitool',
            'libnagios-plugin-perl']
SUPPORTED_TRANSPORTS = ['udp', 'udpu', 'multicast', 'unicast']
DEPRECATED_TRANSPORT_VALUES = {"multicast": "udp", "unicast": "udpu"}


@hooks.hook()
def install():
    ubuntu_release = lsb_release()['DISTRIB_CODENAME'].lower()
    if CompareHostReleases(ubuntu_release) >= 'zesty':
        PACKAGES.remove('libnagios-plugin-perl')
        PACKAGES.append('libnagios-object-perl')
    # NOTE(dosaboy): we currently disallow upgrades due to bug #1382842. This
    # should be removed once the pacemaker package is fixed.
    status_set('maintenance', 'Installing apt packages')
    apt_install(filter_installed_packages(PACKAGES), fatal=True)
    setup_ocf_files()


def get_transport():
    transport = config('corosync_transport')
    val = DEPRECATED_TRANSPORT_VALUES.get(transport, transport)
    if val not in ['udp', 'udpu']:
        msg = ("Unsupported corosync_transport type '%s' - supported "
               "types are: %s" % (transport, ', '.join(SUPPORTED_TRANSPORTS)))
        status_set('blocked', msg)
        raise ValueError(msg)
    return val


def ensure_ipv6_requirements(hanode_rid):
    # hanode relation needs ipv6 private-address
    addr = relation_get(rid=hanode_rid, unit=local_unit(),
                        attribute='private-address')
    log("Current private-address is %s" % (addr))
    if not is_ipv6(addr):
        addr = get_ipv6_addr()
        log("New private-address is %s" % (addr))
        relation_set(relation_id=hanode_rid,
                     **{'private-address': addr})


@hooks.hook()
def config_changed():

    setup_ocf_files()

    if config('prefer-ipv6'):
        assert_charm_supports_ipv6()

    corosync_key = config('corosync_key')
    if not corosync_key:
        message = 'No Corosync key supplied, cannot proceed'
        status_set('blocked', message)
        raise Exception(message)

    enable_lsb_services('pacemaker')

    if config('prefer-ipv6'):
        for rid in relation_ids('hanode'):
            ensure_ipv6_requirements(rid)

    status_set('maintenance', "Setting up corosync")
    if configure_corosync():
        try_pcmk_wait()
        configure_cluster_global()
        configure_monitor_host()
        configure_stonith()

    update_nrpe_config()


@hooks.hook()
def upgrade_charm():
    install()

    update_nrpe_config()


@hooks.hook('hanode-relation-joined',
            'hanode-relation-changed')
def hanode_relation_changed():
    if config('prefer-ipv6'):
        ensure_ipv6_requirements(None)

    ha_relation_changed()


@hooks.hook('ha-relation-joined',
            'ha-relation-changed')
def ha_relation_changed():
    # Check that we are related to a principle and that
    # it has already provided the required corosync configuration
    if not get_corosync_conf():
        log('Unable to configure corosync right now, deferring configuration',
            level=INFO)
        return

    if relation_ids('hanode'):
        log('Ready to form cluster - informing peers', level=DEBUG)
        relation_set(relation_id=relation_ids('hanode')[0], ready=True)
    else:
        log('Ready to form cluster, but not related to peers just yet',
            level=INFO)
        return

    # Check that there's enough nodes in order to perform the
    # configuration of the HA cluster
    if len(get_cluster_nodes()) < int(config('cluster_count')):
        log('Not enough nodes in cluster, deferring configuration',
            level=INFO)
        return

    relids = relation_ids('ha')
    if len(relids) == 1:  # Should only ever be one of these
        # Obtain relation information
        relid = relids[0]
        units = related_units(relid)
        if len(units) < 1:
            log('No principle unit found, deferring configuration',
                level=INFO)
            return

        unit = units[0]
        log('Parsing cluster configuration using rid: %s, unit: %s' %
            (relid, unit), level=DEBUG)
        resources = parse_data(relid, unit, 'resources')
        delete_resources = parse_data(relid, unit, 'delete_resources')
        resource_params = parse_data(relid, unit, 'resource_params')
        groups = parse_data(relid, unit, 'groups')
        ms = parse_data(relid, unit, 'ms')
        orders = parse_data(relid, unit, 'orders')
        colocations = parse_data(relid, unit, 'colocations')
        clones = parse_data(relid, unit, 'clones')
        locations = parse_data(relid, unit, 'locations')
        init_services = parse_data(relid, unit, 'init_services')
    else:
        log('Related to %s ha services' % (len(relids)), level=DEBUG)
        return

    if True in [ra.startswith('ocf:openstack')
                for ra in resources.itervalues()]:
        apt_install('openstack-resource-agents')
    if True in [ra.startswith('ocf:ceph')
                for ra in resources.itervalues()]:
        apt_install('ceph-resource-agents')

    if True in [ra.startswith('ocf:maas')
                for ra in resources.values()]:
        if validate_dns_ha():
            log('Setting up access to MAAS API', level=INFO)
            setup_maas_api()
            # Update resource_parms for DNS resources to include MAAS URL and
            # credentials
            for resource in resource_params.keys():
                if resource.endswith("_hostname"):
                    resource_params[resource] += (
                        ' maas_url="{}" maas_credentials="{}"'
                        ''.format(config('maas_url'),
                                  config('maas_credentials')))
        else:
            msg = ("DNS HA is requested but maas_url "
                   "or maas_credentials are not set")
            status_set('blocked', msg)
            raise ValueError(msg)

    # NOTE: this should be removed in 15.04 cycle as corosync
    # configuration should be set directly on subordinate
    configure_corosync()
    try_pcmk_wait()
    configure_cluster_global()
    configure_monitor_host()
    configure_stonith()

    # Only configure the cluster resources
    # from the oldest peer unit.
    if oldest_peer(peer_units()):
        log('Deleting Resources' % (delete_resources), level=DEBUG)
        for res_name in delete_resources:
            if pcmk.crm_opt_exists(res_name):
                if ocf_file_exists(res_name, resources):
                    log('Stopping and deleting resource %s' % res_name,
                        level=DEBUG)
                    if pcmk.crm_res_running(res_name):
                        pcmk.commit('crm -w -F resource stop %s' % res_name)
                else:
                    log('Cleanuping and deleting resource %s' % res_name,
                        level=DEBUG)
                    pcmk.commit('crm resource cleanup %s' % res_name)
                # Daemon process may still be running after the upgrade.
                kill_legacy_ocf_daemon_process(res_name)
                pcmk.commit('crm -w -F configure delete %s' % res_name)

        log('Configuring Resources: %s' % (resources), level=DEBUG)
        for res_name, res_type in resources.iteritems():
            # disable the service we are going to put in HA
            if res_type.split(':')[0] == "lsb":
                disable_lsb_services(res_type.split(':')[1])
                if service_running(res_type.split(':')[1]):
                    service_stop(res_type.split(':')[1])
            elif (len(init_services) != 0 and
                  res_name in init_services and
                  init_services[res_name]):
                disable_upstart_services(init_services[res_name])
                if service_running(init_services[res_name]):
                    service_stop(init_services[res_name])
            # Put the services in HA, if not already done so
            # if not pcmk.is_resource_present(res_name):
            if not pcmk.crm_opt_exists(res_name):
                if res_name not in resource_params:
                    cmd = 'crm -w -F configure primitive %s %s' % (res_name,
                                                                   res_type)
                else:
                    cmd = ('crm -w -F configure primitive %s %s %s' %
                           (res_name, res_type, resource_params[res_name]))

                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)
                if config('monitor_host'):
                    cmd = ('crm -F configure location Ping-%s %s rule '
                           '-inf: pingd lte 0' % (res_name, res_name))
                    pcmk.commit(cmd)

        log('Configuring Groups: %s' % (groups), level=DEBUG)
        for grp_name, grp_params in groups.iteritems():
            if not pcmk.crm_opt_exists(grp_name):
                cmd = ('crm -w -F configure group %s %s' %
                       (grp_name, grp_params))
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

        log('Configuring Master/Slave (ms): %s' % (ms), level=DEBUG)
        for ms_name, ms_params in ms.iteritems():
            if not pcmk.crm_opt_exists(ms_name):
                cmd = 'crm -w -F configure ms %s %s' % (ms_name, ms_params)
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

        log('Configuring Orders: %s' % (orders), level=DEBUG)
        for ord_name, ord_params in orders.iteritems():
            if not pcmk.crm_opt_exists(ord_name):
                cmd = 'crm -w -F configure order %s %s' % (ord_name,
                                                           ord_params)
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

        log('Configuring Colocations: %s' % colocations, level=DEBUG)
        for col_name, col_params in colocations.iteritems():
            if not pcmk.crm_opt_exists(col_name):
                cmd = 'crm -w -F configure colocation %s %s' % (col_name,
                                                                col_params)
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

        log('Configuring Clones: %s' % clones, level=DEBUG)
        for cln_name, cln_params in clones.iteritems():
            if not pcmk.crm_opt_exists(cln_name):
                cmd = 'crm -w -F configure clone %s %s' % (cln_name,
                                                           cln_params)
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

        log('Configuring Locations: %s' % locations, level=DEBUG)
        for loc_name, loc_params in locations.iteritems():
            if not pcmk.crm_opt_exists(loc_name):
                cmd = 'crm -w -F configure location %s %s' % (loc_name,
                                                              loc_params)
                pcmk.commit(cmd)
                log('%s' % cmd, level=DEBUG)

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
        relation_set(relation_id=rel_id, clustered="yes")


@hooks.hook()
def stop():
    cmd = 'crm -w -F node delete %s' % socket.gethostname()
    pcmk.commit(cmd)
    apt_purge(['corosync', 'pacemaker'], fatal=True)


@hooks.hook('nrpe-external-master-relation-joined',
            'nrpe-external-master-relation-changed')
def update_nrpe_config():
    scripts_src = os.path.join(os.environ["CHARM_DIR"], "files",
                               "nrpe")
    scripts_dst = "/usr/local/lib/nagios/plugins"
    if not os.path.exists(scripts_dst):
        os.makedirs(scripts_dst)
    for fname in glob.glob(os.path.join(scripts_src, "*")):
        if os.path.isfile(fname):
            shutil.copy2(fname,
                         os.path.join(scripts_dst, os.path.basename(fname)))

    sudoers_src = os.path.join(os.environ["CHARM_DIR"], "files",
                               "sudoers")
    sudoers_dst = "/etc/sudoers.d"
    for fname in glob.glob(os.path.join(sudoers_src, "*")):
        if os.path.isfile(fname):
            shutil.copy2(fname,
                         os.path.join(sudoers_dst, os.path.basename(fname)))

    hostname = nrpe.get_nagios_hostname()
    current_unit = nrpe.get_nagios_unit_name()

    nrpe_setup = nrpe.NRPE(hostname=hostname)

    apt_install('python-dbus')

    # corosync/crm checks
    nrpe_setup.add_check(
        shortname='corosync_rings',
        description='Check Corosync rings {%s}' % current_unit,
        check_cmd='check_corosync_rings')
    nrpe_setup.add_check(
        shortname='crm_status',
        description='Check crm status {%s}' % current_unit,
        check_cmd='check_crm')

    # process checks
    nrpe_setup.add_check(
        shortname='corosync_proc',
        description='Check Corosync process {%s}' % current_unit,
        check_cmd='check_procs -c 1:1 -C corosync'
    )
    nrpe_setup.add_check(
        shortname='pacemakerd_proc',
        description='Check Pacemakerd process {%s}' % current_unit,
        check_cmd='check_procs -c 1:1 -C pacemakerd'
    )

    nrpe_setup.write()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e), level=DEBUG)
    set_unit_status()
