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

import ast
import pcmk
import maas
import json
import os
import re
import subprocess
import socket
import fcntl
import struct
import time
import xml.etree.ElementTree as ET

from base64 import b64decode

from charmhelpers.core.hookenv import (
    local_unit,
    log,
    DEBUG,
    ERROR,
    INFO,
    WARNING,
    relation_get,
    related_units,
    relation_ids,
    config,
    unit_get,
    status_set,
)
from charmhelpers.contrib.openstack.utils import (
    get_host_ip,
    set_unit_paused,
    clear_unit_paused,
    is_unit_paused_set,
    is_unit_upgrading_set,
)
from charmhelpers.contrib.openstack.ha.utils import (
    assert_charm_supports_dns_ha
)
from charmhelpers.core.host import (
    mkdir,
    rsync,
    service_start,
    service_stop,
    service_running,
    write_file,
    file_hash,
    lsb_release,
    init_is_systemd,
    CompareHostReleases,
)
from charmhelpers.fetch import (
    apt_install,
    add_source,
    apt_update,
)
from charmhelpers.contrib.hahelpers.cluster import (
    peer_ips,
)
from charmhelpers.contrib.network import ip as utils

try:
    import netifaces
except ImportError:
    apt_install('python-netifaces')
    import netifaces

try:
    from netaddr import IPNetwork
except ImportError:
    apt_install('python-netaddr', fatal=True)
    from netaddr import IPNetwork


try:
    import jinja2
except ImportError:
    apt_install('python-jinja2', fatal=True)
    import jinja2


TEMPLATES_DIR = 'templates'
COROSYNC_CONF = '/etc/corosync/corosync.conf'
COROSYNC_DEFAULT = '/etc/default/corosync'
COROSYNC_AUTHKEY = '/etc/corosync/authkey'
COROSYNC_HACLUSTER_ACL_DIR = '/etc/corosync/uidgid.d'
COROSYNC_HACLUSTER_ACL = COROSYNC_HACLUSTER_ACL_DIR + '/hacluster'
COROSYNC_CONF_FILES = [
    COROSYNC_DEFAULT,
    COROSYNC_AUTHKEY,
    COROSYNC_CONF,
    COROSYNC_HACLUSTER_ACL,
]
SUPPORTED_TRANSPORTS = ['udp', 'udpu', 'multicast', 'unicast']
PCMKR_MAX_RETRIES = 3
PCMKR_SLEEP_SECS = 5

SYSTEMD_OVERRIDES_DIR = '/etc/systemd/system/{}.service.d'
SYSTEMD_OVERRIDES_FILE = '{}/overrides.conf'


MAAS_DNS_CONF_DIR = '/etc/maas_dns'


class MAASConfigIncomplete(Exception):
    pass


def disable_upstart_services(*services):
    for service in services:
        with open("/etc/init/{}.override".format(service), "w") as override:
            override.write("manual")


def enable_upstart_services(*services):
    for service in services:
        path = '/etc/init/{}.override'.format(service)
        if os.path.exists(path):
            os.remove(path)


def disable_lsb_services(*services):
    for service in services:
        subprocess.check_call(['update-rc.d', '-f', service, 'remove'])


def enable_lsb_services(*services):
    for service in services:
        subprocess.check_call(['update-rc.d', '-f', service, 'defaults'])


def get_iface_ipaddr(iface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x8919,  # SIOCGIFADDR
        struct.pack('256s', iface[:15])
    )[20:24])


def get_iface_netmask(iface):
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    return socket.inet_ntoa(fcntl.ioctl(
        s.fileno(),
        0x891b,  # SIOCGIFNETMASK
        struct.pack('256s', iface[:15])
    )[20:24])


def get_netmask_cidr(netmask):
    netmask = netmask.split('.')
    binary_str = ''
    for octet in netmask:
        binary_str += bin(int(octet))[2:].zfill(8)
    return str(len(binary_str.rstrip('0')))


def get_network_address(iface):
    if iface:
        iface = str(iface)
        network = "{}/{}".format(get_iface_ipaddr(iface),
                                 get_netmask_cidr(get_iface_netmask(iface)))
        ip = IPNetwork(network)
        return str(ip.network)
    else:
        return None


def get_ipv6_network_address(iface):
    # Behave in same way as ipv4 get_network_address() above if iface is None.
    if not iface:
        return None

    try:
        ipv6_addr = utils.get_ipv6_addr(iface=iface)[0]
        all_addrs = netifaces.ifaddresses(iface)

        for addr in all_addrs[netifaces.AF_INET6]:
            if ipv6_addr == addr['addr']:
                network = "{}/{}".format(addr['addr'], addr['netmask'])
                return str(IPNetwork(network).network)

    except ValueError:
        msg = "Invalid interface '%s'" % iface
        status_set('blocked', msg)
        raise Exception(msg)

    msg = "No valid network found for interface '%s'" % iface
    status_set('blocked', msg)
    raise Exception(msg)


def get_corosync_id(unit_name):
    # Corosync nodeid 0 is reserved so increase all the nodeids to avoid it
    off_set = 1000
    return off_set + int(unit_name.split('/')[1])


def nulls(data):
    """Returns keys of values that are null (but not bool)"""
    return [k for k in data.iterkeys()
            if not isinstance(data[k], bool) and not data[k]]


def get_corosync_conf():
    if config('prefer-ipv6'):
        ip_version = 'ipv6'
        bindnetaddr = get_ipv6_network_address
    else:
        ip_version = 'ipv4'
        bindnetaddr = get_network_address

    transport = get_transport()

    # NOTE(jamespage) use local charm configuration over any provided by
    # principle charm
    conf = {
        'ip_version': ip_version,
        'ha_nodes': get_ha_nodes(),
        'transport': transport,
    }

    # NOTE(jamespage): only populate multicast configuration if udp is
    #                  configured
    if transport == 'udp':
        conf.update({
            'corosync_bindnetaddr': bindnetaddr(config('corosync_bindiface')),
            'corosync_mcastport': config('corosync_mcastport'),
            'corosync_mcastaddr': config('corosync_mcastaddr')
        })

    if config('prefer-ipv6'):
        conf['nodeid'] = get_corosync_id(local_unit())

    if config('netmtu'):
        conf['netmtu'] = config('netmtu')

    if config('debug'):
        conf['debug'] = config('debug')

    if not nulls(conf):
        log("Found sufficient values in local config to populate "
            "corosync.conf", level=DEBUG)
        return conf

    conf = {}
    for relid in relation_ids('ha'):
        for unit in related_units(relid):
            conf = {
                'ip_version': ip_version,
                'ha_nodes': get_ha_nodes(),
                'transport': transport,
            }

            # NOTE(jamespage): only populate multicast configuration if udpu is
            #                  configured
            if transport == 'udp':
                bindiface = relation_get('corosync_bindiface',
                                         unit, relid)
                conf.update({
                    'corosync_bindnetaddr': bindnetaddr(bindiface),
                    'corosync_mcastport': relation_get('corosync_mcastport',
                                                       unit, relid),
                    'corosync_mcastaddr': config('corosync_mcastaddr'),
                })

            if config('prefer-ipv6'):
                conf['nodeid'] = get_corosync_id(local_unit())

            if config('netmtu'):
                conf['netmtu'] = config('netmtu')

            if config('debug'):
                conf['debug'] = config('debug')

            # Values up to this point must be non-null
            if nulls(conf):
                continue

            return conf

    missing = [k for k, v in conf.iteritems() if v is None]
    log('Missing required configuration: %s' % missing)
    return None


def emit_systemd_overrides_file():
    """Generate the systemd overrides file
    With Start and Stop timeout values
    Note: (David Ames) Bug#1654403 Work around
    May be removed if bug is resolved
    If timeout value is set to -1 pass infinity
    """
    if not init_is_systemd():
        return

    stop_timeout = int(config('service_stop_timeout'))
    if stop_timeout < 0:
        stop_timeout = 'infinity'
    start_timeout = int(config('service_start_timeout'))
    if start_timeout < 0:
        start_timeout = 'infinity'

    systemd_overrides_context = {'service_stop_timeout': stop_timeout,
                                 'service_start_timeout': start_timeout,
                                 }

    for service in ['corosync', 'pacemaker']:
        overrides_dir = SYSTEMD_OVERRIDES_DIR.format(service)
        overrides_file = SYSTEMD_OVERRIDES_FILE.format(overrides_dir)
        if not os.path.isdir(overrides_dir):
            os.mkdir(overrides_dir)

        write_file(path=overrides_file,
                   content=render_template('systemd-overrides.conf',
                                           systemd_overrides_context))

    # Update systemd with the new information
    subprocess.check_call(['systemctl', 'daemon-reload'])


def emit_corosync_conf():
    corosync_conf_context = get_corosync_conf()
    if corosync_conf_context:
        write_file(path=COROSYNC_CONF,
                   content=render_template('corosync.conf',
                                           corosync_conf_context))
        return True

    return False


def emit_base_conf():
    if not os.path.isdir(COROSYNC_HACLUSTER_ACL_DIR):
        os.mkdir(COROSYNC_HACLUSTER_ACL_DIR)
    corosync_default_context = {'corosync_enabled': 'yes'}
    write_file(path=COROSYNC_DEFAULT,
               content=render_template('corosync',
                                       corosync_default_context))

    write_file(path=COROSYNC_HACLUSTER_ACL,
               content=render_template('hacluster.acl', {}))

    corosync_key = config('corosync_key')
    if corosync_key:
        write_file(path=COROSYNC_AUTHKEY,
                   content=b64decode(corosync_key),
                   perms=0o400)
        return True

    return False


def render_template(template_name, context, template_dir=TEMPLATES_DIR):
    templates = jinja2.Environment(
        loader=jinja2.FileSystemLoader(template_dir)
    )
    template = templates.get_template(template_name)
    return template.render(context)


def assert_charm_supports_ipv6():
    """Check whether we are able to support charms ipv6."""
    _release = lsb_release()['DISTRIB_CODENAME'].lower()
    if CompareHostReleases(_release) < "trusty":
        msg = "IPv6 is not supported in the charms for Ubuntu " \
              "versions less than Trusty 14.04"
        status_set('blocked', msg)
        raise Exception(msg)


def get_transport():
    transport = config('corosync_transport')
    _deprecated_transport_values = {"multicast": "udp", "unicast": "udpu"}
    val = _deprecated_transport_values.get(transport, transport)
    if val not in ['udp', 'udpu']:
        msg = ("Unsupported corosync_transport type '%s' - supported "
               "types are: %s" % (transport, ', '.join(SUPPORTED_TRANSPORTS)))
        status_set('blocked', msg)
        raise ValueError(msg)

    return val


def get_ipv6_addr():
    """Exclude any ip addresses configured or managed by corosync."""
    excludes = []
    for rid in relation_ids('ha'):
        for unit in related_units(rid):
            resources = parse_data(rid, unit, 'resources')
            for res in resources.itervalues():
                if 'ocf:heartbeat:IPv6addr' in res:
                    res_params = parse_data(rid, unit, 'resource_params')
                    res_p = res_params.get(res)
                    if res_p:
                        for k, v in res_p.itervalues():
                            if utils.is_ipv6(v):
                                log("Excluding '%s' from address list" % v,
                                    level=DEBUG)
                                excludes.append(v)

    return utils.get_ipv6_addr(exc_list=excludes)[0]


def get_ha_nodes():
    ha_units = peer_ips(peer_relation='hanode')
    ha_nodes = {}
    for unit in ha_units:
        corosync_id = get_corosync_id(unit)
        addr = ha_units[unit]
        if config('prefer-ipv6'):
            if not utils.is_ipv6(addr):
                # Not an error since cluster may still be forming/updating
                log("Expected an ipv6 address but got %s" % (addr),
                    level=WARNING)

            ha_nodes[corosync_id] = addr
        else:
            ha_nodes[corosync_id] = get_host_ip(addr)

    corosync_id = get_corosync_id(local_unit())
    if config('prefer-ipv6'):
        addr = get_ipv6_addr()
    else:
        addr = get_host_ip(unit_get('private-address'))

    ha_nodes[corosync_id] = addr

    return ha_nodes


def get_cluster_nodes():
    hosts = []
    if config('prefer-ipv6'):
        hosts.append(get_ipv6_addr())
    else:
        hosts.append(unit_get('private-address'))

    for relid in relation_ids('hanode'):
        for unit in related_units(relid):
            if relation_get('ready', rid=relid, unit=unit):
                hosts.append(relation_get('private-address', unit, relid))

    hosts.sort()
    return hosts


def parse_data(relid, unit, key):
    """Helper to detect and parse json or ast based relation data"""
    _key = 'json_{}'.format(key)
    data = relation_get(_key, unit, relid) or relation_get(key, unit, relid)
    if data:
        try:
            return json.loads(data)
        except (TypeError, ValueError):
            return ast.literal_eval(data)

    return {}


def configure_stonith():
    if config('stonith_enabled') not in ['true', 'True', True]:
        log('Disabling STONITH', level=INFO)
        cmd = "crm configure property stonith-enabled=false"
        pcmk.commit(cmd)
    else:
        log('Enabling STONITH for all nodes in cluster.', level=INFO)
        # configure stontih resources for all nodes in cluster.
        # note: this is totally provider dependent and requires
        # access to the MAAS API endpoint, using endpoint and credentials
        # set in config.
        url = config('maas_url')
        creds = config('maas_credentials')
        if None in [url, creds]:
            msg = 'maas_url and maas_credentials must be set ' \
                  'in config to enable STONITH.'
            status_set('blocked', msg)
            raise Exception(msg)

        nodes = maas.MAASHelper(url, creds).list_nodes()
        if not nodes:
            msg = 'Could not obtain node inventory from ' \
                  'MAAS @ %s.' % url
            status_set('blocked', msg)
            raise Exception(msg)

        cluster_nodes = pcmk.list_nodes()
        for node in cluster_nodes:
            rsc, constraint = pcmk.maas_stonith_primitive(nodes, node)
            if not rsc:
                msg = 'Failed to determine STONITH primitive for ' \
                      'node %s' % node
                status_set('blocked', msg)
                raise Exception(msg)

            rsc_name = str(rsc).split(' ')[1]
            if not pcmk.is_resource_present(rsc_name):
                log('Creating new STONITH primitive %s.' % rsc_name,
                    level=DEBUG)
                cmd = 'crm -F configure %s' % rsc
                pcmk.commit(cmd)
                if constraint:
                    cmd = 'crm -F configure %s' % constraint
                    pcmk.commit(cmd)
            else:
                log('STONITH primitive already exists for node.', level=DEBUG)

        pcmk.commit("crm configure property stonith-enabled=true")


def configure_monitor_host():
    """Configure extra monitor host for better network failure detection"""
    log('Checking monitor host configuration', level=DEBUG)
    monitor_host = config('monitor_host')
    if monitor_host:
        if not pcmk.crm_opt_exists('ping'):
            log('Implementing monitor host configuration (host: %s)' %
                monitor_host, level=DEBUG)
            monitor_interval = config('monitor_interval')
            cmd = ('crm -w -F configure primitive ping '
                   'ocf:pacemaker:ping params host_list="%s" '
                   'multiplier="100" op monitor interval="%s" ' %
                   (monitor_host, monitor_interval))
            pcmk.commit(cmd)
            cmd = ('crm -w -F configure clone cl_ping ping '
                   'meta interleave="true"')
            pcmk.commit(cmd)
        else:
            log('Reconfiguring monitor host configuration (host: %s)' %
                monitor_host, level=DEBUG)
            cmd = ('crm -w -F resource param ping set host_list="%s"' %
                   monitor_host)
    else:
        if pcmk.crm_opt_exists('ping'):
            log('Disabling monitor host configuration', level=DEBUG)
            pcmk.commit('crm -w -F resource stop ping')
            pcmk.commit('crm -w -F configure delete ping')


def configure_cluster_global():
    """Configure global cluster options"""
    log('Applying global cluster configuration', level=DEBUG)
    # NOTE(lathiat) quorum in a two-node scenario is handled by
    # corosync two_node=1.  In this case quorum is required for
    # initial cluster startup but not if a node was previously in
    # contact with the full cluster.
    log('Configuring no-quorum-policy to stop', level=DEBUG)
    cmd = "crm configure property no-quorum-policy=stop"

    pcmk.commit(cmd)
    cmd = ('crm configure rsc_defaults $id="rsc-options" '
           'resource-stickiness="100"')
    pcmk.commit(cmd)

    log('Configuring cluster-recheck-interval to 60 seconds', level=DEBUG)
    cmd = "crm configure property cluster-recheck-interval=60"
    pcmk.commit(cmd)


def get_ip_addr_from_resource_params(params):
    """Returns the IP address in the resource params provided

    :return: the IP address in the params or None if not found
    """
    reg_ex = r'.* ip_address="([a-fA-F\d\:\.]+)".*'
    res = re.search(reg_ex, params)
    return res.group(1) if res else None


def restart_corosync_on_change():
    """Simple decorator to restart corosync if any of its config changes"""
    def wrap(f):
        def wrapped_f(*args, **kwargs):
            checksums = {}
            for path in COROSYNC_CONF_FILES:
                checksums[path] = file_hash(path)
            return_data = f(*args, **kwargs)
            # NOTE: this assumes that this call is always done around
            # configure_corosync, which returns true if configuration
            # files where actually generated
            if return_data:
                for path in COROSYNC_CONF_FILES:
                    if checksums[path] != file_hash(path):
                        validated_restart_corosync()
                        break

            return return_data
        return wrapped_f
    return wrap


def try_pcmk_wait():
    """Try pcmk.wait_for_pcmk()
    Log results and set status message
    """
    try:
        pcmk.wait_for_pcmk()
        log("Pacemaker is ready", DEBUG)
    except pcmk.ServicesNotUp:
        msg = ("Pacemaker is down. Please manually start it.")
        log(msg, ERROR)
        status_set('blocked', msg)
        raise pcmk.ServicesNotUp(msg)


@restart_corosync_on_change()
def configure_corosync():
    log('Configuring and (maybe) restarting corosync', level=DEBUG)
    # David Ames Bug#1654403 Work around
    # May be removed if bug is resolved
    emit_systemd_overrides_file()
    return emit_base_conf() and emit_corosync_conf()


def services_running():
    """Determine if both Corosync and Pacemaker are running
    Both from the operating system perspective and with a functional test
    @returns boolean
    """
    pacemaker_status = service_running("pacemaker")
    corosync_status = service_running("corosync")
    log("Pacemaker status: {}, Corosync status: {}"
        "".format(pacemaker_status, corosync_status),
        level=DEBUG)
    if not (pacemaker_status and corosync_status):
        # OS perspective
        return False
    else:
        # Functional test of pacemaker
        return pcmk.wait_for_pcmk()


def validated_restart_corosync(retries=10):
    """Restart and validate Corosync and Pacemaker are in fact up and running.

    @param retries: number of attempts to restart the services before giving up
    @raises pcmk.ServicesNotUp if after retries services are still not up
    """
    for restart in range(retries):
        try:
            if restart_corosync():
                log("Corosync and Pacemaker are validated as up and running.",
                    INFO)
                return
            else:
                log("Corosync or Pacemaker not validated as up yet, retrying",
                    WARNING)
        except pcmk.ServicesNotUp:
            log("Pacemaker failed to start, retrying", WARNING)
            continue

    msg = ("Corosync and/or Pacemaker failed to restart after {} retries"
           "".format(retries))
    log(msg, ERROR)
    status_set('blocked', msg)
    raise pcmk.ServicesNotUp(msg)


def restart_corosync():
    if service_running("pacemaker"):
        log("Stopping pacemaker", DEBUG)
        service_stop("pacemaker")

    if not is_unit_paused_set():
        log("Stopping corosync", DEBUG)
        service_stop("corosync")
        log("Starting corosync", DEBUG)
        service_start("corosync")
        log("Starting pacemaker", DEBUG)
        service_start("pacemaker")

    return services_running()


def validate_dns_ha():
    """Validate the DNS HA

    Assert the charm will support DNS HA
    Check MAAS related configuration options are properly set

    :raises MAASConfigIncomplete: if maas_url and maas_credentials are not set
    """

    # Will raise an exception if unable to continue
    assert_charm_supports_dns_ha()

    if config('maas_url') and config('maas_credentials'):
        return True
    else:
        msg = ("DNS HA is requested but the maas_url or maas_credentials "
               "settings are not set")
        raise MAASConfigIncomplete(msg)


def setup_maas_api():
    """Install MAAS PPA and packages for accessing the MAAS API.
    """
    add_source(config('maas_source'))
    apt_update(fatal=True)
    apt_install('python3-maas-client', fatal=True)


def setup_ocf_files():
    """Setup OCF resrouce agent files
    """

    # TODO (thedac) Eventually we want to package the OCF files.
    # Bundle with the charm until then.
    mkdir('/usr/lib/ocf/resource.d/ceph')
    mkdir('/usr/lib/ocf/resource.d/maas')
    # Xenial corosync is not creating this directory
    mkdir('/etc/corosync/uidgid.d')

    rsync('ocf/ceph/rbd', '/usr/lib/ocf/resource.d/ceph/rbd')
    rsync('ocf/maas/dns', '/usr/lib/ocf/resource.d/maas/dns')
    rsync('ocf/maas/maas_dns.py', '/usr/lib/heartbeat/maas_dns.py')
    rsync('ocf/maas/maasclient/', '/usr/lib/heartbeat/maasclient/')


def write_maas_dns_address(resource_name, resource_addr):
    """Writes the specified IP address to the resource file for MAAS dns.

    :param resource_name: the name of the resource the address belongs to.
        This is the name of the file that will be written in /etc/maas_dns.
    :param resource_addr: the IP address for the resource. This will be
        written to the resource_name file.
    """
    mkdir(MAAS_DNS_CONF_DIR)
    write_file(os.path.join(MAAS_DNS_CONF_DIR, resource_name),
               content=resource_addr)


def needs_maas_dns_migration():
    """Determines if the MAAS DNS ocf resources need migration.

    :return: True if migration is necessary, False otherwise.
    """
    try:
        subprocess.check_call(['grep', 'OCF_RESOURCE_INSTANCE',
                               '/usr/lib/ocf/resource.d/maas/dns'])
        return True
    except subprocess.CalledProcessError:
        # check_call will raise an exception if grep doesn't find the string
        return False


def is_in_standby_mode(node_name):
    """Check if node is in standby mode in pacemaker

    @param node_name: The name of the node to check
    @returns boolean - True if node_name is in standby mode
    """
    out = subprocess.check_output(['crm', 'node', 'status', node_name])
    root = ET.fromstring(out)

    standby_mode = False
    for nvpair in root.iter('nvpair'):
        if (nvpair.attrib.get('name') == 'standby' and
                nvpair.attrib.get('value') == 'on'):
            standby_mode = True
    return standby_mode


def get_hostname():
    """Return the hostname of this unit

    @returns hostname
    """
    return socket.gethostname()


def enter_standby_mode(node_name, duration='forever'):
    """Put this node into standby mode in pacemaker

    @returns None
    """
    subprocess.check_call(['crm', 'node', 'standby', node_name, duration])


def leave_standby_mode(node_name):
    """Take this node out of standby mode in pacemaker

    @returns None
    """
    subprocess.check_call(['crm', 'node', 'online', node_name])


def node_has_resources(node_name):
    """Check if this node is running resources

    @param node_name: The name of the node to check
    @returns boolean - True if node_name has resources
    """
    out = subprocess.check_output(['crm_mon', '-X'])
    root = ET.fromstring(out)
    has_resources = False
    for resource in root.iter('resource'):
        for child in resource:
            if child.tag == 'node' and child.attrib.get('name') == node_name:
                has_resources = True
    return has_resources


def set_unit_status():
    """Set the workload status for this unit

    @returns None
    """
    status_set(*assess_status_helper())


def resume_unit():
    """Resume services on this unit and update the units status

    @returns None
    """
    node_name = get_hostname()
    messages = []
    leave_standby_mode(node_name)
    if is_in_standby_mode(node_name):
        messages.append("Node still in standby mode")
    if messages:
        raise Exception("Couldn't resume: {}".format("; ".join(messages)))
    else:
        clear_unit_paused()
        set_unit_status()


def pause_unit():
    """Pause services on this unit and update the units status

    @returns None
    """
    node_name = get_hostname()
    messages = []
    enter_standby_mode(node_name)
    if not is_in_standby_mode(node_name):
        messages.append("Node not in standby mode")

    # some resources may take some time to be migrated out from the node. So 3
    # retries are made with a 5 seconds wait between each one.
    i = 0
    ready = False
    has_resources = False
    while i < PCMKR_MAX_RETRIES and not ready:
        if node_has_resources(node_name):
            has_resources = True
            i += 1
            time.sleep(PCMKR_SLEEP_SECS)
        else:
            ready = True
            has_resources = False

    if has_resources:
        messages.append("Resources still running on unit")
    status, message = assess_status_helper()
    if status != 'active':
        messages.append(message)
    if messages and not is_unit_upgrading_set():
        raise Exception("Couldn't pause: {}".format("; ".join(messages)))
    else:
        set_unit_paused()
        status_set("maintenance",
                   "Paused. Use 'resume' action to resume normal service.")


def assess_status_helper():
    """Assess status of unit

    @returns status, message - status is workload status and message is any
                               corresponding messages
    """

    if is_unit_upgrading_set():
        return ("blocked",
                "Ready for do-release-upgrde. Set complete when finished")
    if is_unit_paused_set():
        return ("maintenance",
                "Paused. Use 'resume' action to resume normal service.")

    node_count = int(config('cluster_count'))
    status = 'active'
    message = 'Unit is ready and clustered'
    try:
        try_pcmk_wait()
    except pcmk.ServicesNotUp:
        message = 'Pacemaker is down'
        status = 'blocked'
    for relid in relation_ids('hanode'):
        if len(related_units(relid)) + 1 < node_count:
            status = 'blocked'
            message = ("Insufficient peer units for ha cluster "
                       "(require {})".format(node_count))

    # if the status was not changed earlier, we verify the maintenance status
    try:
        if status == 'active':
            prop = pcmk.get_property('maintenance-mode').strip()
    except pcmk.PropertyNotFound:
        # the property is not the output of 'crm configure show xml', so we use
        # the default value for this property. For crmsh>=2.2.0 the default
        # value is automatically provided by show-property or get-property.
        prop = 'false'

    if (status == 'active' and prop == 'true'):
        # maintenance mode enabled in pacemaker
        status = 'maintenance'
        message = 'Pacemaker in maintenance mode'

    return status, message


def ocf_file_exists(res_name, resources,
                    RES_ROOT='/usr/lib/ocf/resource.d'):
    """To determine whether the ocf file exists, allow multiple ocf
       files with the same name in different directories

    @param res_name: The name of the ocf resource to check
    @param resources: ocf resources
    @return: boolean - True if the ocf resource exists
    """
    res_type = None
    for key, val in resources.iteritems():
        if res_name == key:
            if len(val.split(':')) > 2:
                res_type = val.split(':')[1]
                ocf_name = res_name.replace('res_', '').replace('_', '-')
                ocf_file = os.path.join(RES_ROOT, res_type, ocf_name)
                if os.path.isfile(ocf_file):
                    return True
    return False


def kill_legacy_ocf_daemon_process(res_name):
    """Kill legacy ocf daemon process

    @param res_name: The name of the ocf process to kill
    """
    ocf_name = res_name.replace('res_', '').replace('_', '-')
    reg_expr = '([0-9]+)\s+[^0-9]+{}'.format(ocf_name)
    cmd = ['ps', '-eo', 'pid,cmd']
    ps = subprocess.check_output(cmd)
    res = re.search(reg_expr, ps, re.MULTILINE)
    if res:
        pid = res.group(1)
        subprocess.call(['sudo', 'kill', '-9', pid])


def maintenance_mode(enable):
    """Enable/disable pacemaker's maintenance mode"""

    log('Setting maintenance-mode to %s' % enable, level=INFO)

    try:
        current_state = pcmk.get_property('maintenance-mode').strip().lower()
    except pcmk.PropertyNotFound:
        current_state = 'false'

    current_state = True if current_state == 'true' else False
    log('Is maintenance-mode currently enabled? %s' % current_state,
        level=DEBUG)
    if current_state != enable:
        pcmk.set_property('maintenance-mode', str(enable).lower())
    else:
        log('Desired value for maintenance-mode is already set', level=DEBUG)
