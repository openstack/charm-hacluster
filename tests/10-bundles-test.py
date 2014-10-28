#!/usr/bin/env python3

# This amulet test deploys the bundles.yaml file in this directory.

import os
import unittest
import yaml
import amulet

seconds_to_wait = 600


class BundleTest(unittest.TestCase):
    """ Create a class for testing the charm in the unit test framework. """
    @classmethod
    def setUpClass(cls):
        """ Set up an amulet deployment using the bundle. """
        d = amulet.Deployment()
        bundle_path = os.path.join(os.path.dirname(__file__), 'bundles.yaml')
        with open(bundle_path, 'r') as bundle_file:
            contents = yaml.safe_load(bundle_file)
            d.load(contents)
        d.setup(seconds_to_wait)
        d.sentry.wait(seconds_to_wait)
        cls.d = d

    def test_deployed(self):
        """ Test to see if the bundle deployed successfully. """
        self.assertTrue(self.d.deployed)


if __name__ == '__main__':
    unittest.main()