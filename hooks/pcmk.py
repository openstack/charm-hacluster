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


#def wait_for_cluster():
#    while (not is_running()):
#        time.sleep(3)

def is_resource_present(resource):
    (status, output) = commands.getstatusoutput("crm resource status %s" % resource)
    if status != 0:
        return False
    return True
