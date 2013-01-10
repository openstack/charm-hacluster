import utils
import commands
import re
import subprocess
import sys


def execute(cmd):
    subprocess.check_call(cmd.split())


def execute_shell(cmd):
    subprocess.check_call(cmd, shell=True)


def prepare_drbd_disk(block_device=None):
    if block_device is None:
        sys.exit(1)

    cmd = 'dd if=/dev/zero of=%s bs=512 count=1 oflag=direct >/dev/null' % block_device
    execute_shell(cmd)
    cmd = '(echo n; echo p; echo 1; echo ; echo; echo w) | fdisk %s' % block_device
    execute_shell(cmd)


def modprobe_module():
    cmd = 'modprobe drbd'
    execute(cmd)
    cmd = 'echo drbd >> /etc/modules'
    execute_shell(cmd)


def create_md():
    cmd = 'drbdadm -- --force create-md export'
    execute(cmd)


def bring_resource_up():
    cmd = 'drbdadm up export'
    execute(cmd)


def clear_bitmap():
    cmd = 'drbdadm -- --clear-bitmap new-current-uuid export'
    execute(cmd)


def make_primary():
    cmd = 'drbdadm primary export'
    execute(cmd)


def make_primary():
    cmd = 'drbdadm secondary export'
    execute(cmd)

def format_drbd_device():
    cmd = 'mkfs -t ext3 /dev/drbd0'
    execute(cmd)


def is_connected():
    (status, output) = commands.getstatusoutput("drbd-overview")
    show_re = re.compile("0:export  Connected")
    quorum = show_re.search(output)
    if quorum:
        return True
    return False


def is_quorum_secondary():
    (status, output) = commands.getstatusoutput("drbd-overview")
    show_re = re.compile("Secondary/Secondary")
    quorum = show_re.search(output)
    if quorum:
        return True
    return False


def is_quorum_primary():
    (status, output) = commands.getstatusoutput("drbd-overview")
    show_re = re.compile("Primary/Secondary")
    quorum = show_re.search(output)
    if quorum:
        return True
    return False


def is_state_inconsistent():
    (status, output) = commands.getstatusoutput("drbd-overview")
    show_re = re.compile("Inconsistent/Inconsistent")
    quorum = show_re.search(output)
    if quorum:
        return True
    return False


def is_state_uptodate():
    (status, output) = commands.getstatusoutput("drbd-overview")
    show_re = re.compile("UpToDate/UpToDate")
    quorum = show_re.search(output)
    if quorum:
        return True
    return False

# Blow away any partitions on the disk:
#cmd = 'dd if=/dev/zero of=/dev/vdb bs=512 count=1 oflag=direct >/dev/null'
#subprocess.check_call(cmd, shell=True)

# Creating a partition
#cmd = '(echo o; echo n; echo p; echo 1; echo ; echo; echo w) | fdisk /dev/vdb'
#cmd = '(echo n; echo p; echo 1; echo ; echo; echo w) | fdisk /dev/vdb'
#subprocess.check_call(cmd, shell=True)

# Mounting module
#cmd = ['modprobe','drbd']
#subprocess.check_call(cmd)

#cmd = 'echo drbd >> /etc/modules'
#subprocess.check_call(cmd, shell=True)

# TODO: making configuration file


# Creating md/bringing up
#cmd = ['drbdadm', '--', '--force', 'create-md', 'export']
#subprocess.check_call(cmd)

#cmd = ['drbdadm', 'up', 'export']
#subprocess.check_call(cmd)


####################################3

# TODO: Check that both nodes have joined and are inconsistant.
#cmd = ['drbdadm', '--', '--clear-bitmap', 'new-current-uuid', 'export']
#subprocess.check_call(cmd)
# TODO: check that both nodes are UpToDate
#cmd = ['drbdadm', 'primary', 'export']
#subprocess.check_call(cmd)
#cmd = ['mkfs', '-t', 'ext3', '/dev/drbd0']
#subprocess.check_call(cmd)
