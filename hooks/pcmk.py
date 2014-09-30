import commands
import subprocess
import socket

from charmhelpers.core.hookenv import log, ERROR


def wait_for_pcmk():
    crm_up = None
    hostname = socket.gethostname()
    while not crm_up:
        output = commands.getstatusoutput("crm node list")[1]
        crm_up = hostname in output


def commit(cmd):
    subprocess.call(cmd.split())


def is_resource_present(resource):
    status = commands.getstatusoutput("crm resource status %s" % resource)[0]
    if status != 0:
        return False
    return True


def standby(node=None):
    if node is None:
        cmd = "crm -F node standby"
    else:
        cmd = "crm -F node standby %s" % node
    commit(cmd)


def online(node=None):
    if node is None:
        cmd = "crm -F node online"
    else:
        cmd = "crm -F node online %s" % node
    commit(cmd)


def crm_opt_exists(opt_name):
    output = commands.getstatusoutput("crm configure show")[1]
    if opt_name in output:
        return True
    return False


def crm_res_running(opt_name):
    output = commands.getstatusoutput("crm resource status %s" % opt_name)[1]
    if opt_name in output:
        return False
    return True


def list_nodes():
    cmd = ['crm', 'node', 'list']
    out = subprocess.check_output(cmd)
    nodes = []
    for line in str(out).split('\n'):
        if line != '':
            nodes.append(line.split(':')[0])
    return nodes


def _maas_ipmi_stonith_resource(node, power_params):
    rsc_name = 'res_stonith_%s' % node
    rsc = 'primitive %s stonith:external/ipmi' % rsc_name
    rsc += ' params hostname=%s ipaddr=%s userid=%s passwd=%s interface=lan' %\
           (node, power_params['power_address'],
            power_params['power_user'], power_params['power_pass'])

    # ensure ipmi stonith agents are not running on the nodes that
    # they manage.
    constraint = 'location const_loc_stonith_avoid_%s %s -inf: %s' %\
        (node, rsc_name, node)

    return rsc, constraint


def maas_stonith_primitive(maas_nodes, crm_node):
    power_type = power_params = None
    for node in maas_nodes:
        if node['hostname'].startswith(crm_node):
            power_type = node['power_type']
            power_params = node['power_parameters']

    if not power_type or not power_params:
        return False, False

    rsc = constraint = None
    # we can extend to support other power flavors in the future?
    if power_type == 'ipmi':
        rsc, constraint = _maas_ipmi_stonith_resource(crm_node, power_params)
    else:
        log('Unsupported STONITH power_type: %s' % power_type, ERROR)
        return False, False

    if not rsc or not constraint:
        return False, False

    return rsc, constraint
