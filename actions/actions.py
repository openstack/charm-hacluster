#!/usr/bin/python

import sys
import os
sys.path.append('hooks/')
import subprocess
from charmhelpers.core.hookenv import action_fail
from utils import (
    pause_unit,
    resume_unit,
)

def pause(args):
    """Pause the hacluster services.
    @raises Exception should the service fail to stop.
    """
    pause_unit()

def resume(args):
    """Resume the hacluster services.
    @raises Exception should the service fail to start."""
    resume_unit()


ACTIONS = {"pause": pause, "resume": resume}

def main(args):
    action_name = os.path.basename(args[0])
    try:
        action = ACTIONS[action_name]
    except KeyError:
        return "Action %s undefined" % action_name
    else:
        try:
            action(args)
        except Exception as e:
            action_fail(str(e))


if __name__ == "__main__":
    sys.exit(main(sys.argv))
