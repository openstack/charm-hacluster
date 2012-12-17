import utils
import commands
import re
import subprocess

#def is_quorum():
#import time

#def is_leader():


def wait_for_pcmk():
    crm_up = None
    while not crm_up:
        (status, output) = commands.getstatusoutput("crm node list")
        show_re = re.compile(utils.get_unit_hostname())
        crm_up = show_re.search(output)


def commit(cmd):
    subprocess.call(cmd.split())


def is_resource_present(resource):
    (status, output) = \
        commands.getstatusoutput("crm resource status %s" % resource)
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
    (status, output) = commands.getstatusoutput("crm configure show")
    show_re = re.compile(opt_name)
    opt = show_re.search(output)
    if opt:
        return True
    return False
