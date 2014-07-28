#!/usr/bin/python
from setuptools import setup, find_packages
import sys

install_requires = []
if sys.platform.startswith("linux"):
    install_requires += ["pyudev>=0.13"]
else:
    install_requires += ["hidapi>=0.7.99"]

exclusions = []
if 'test' not in sys.argv:
    # only exclude tests if we are not testing: hack to
    # force tests passing through 2to3 on py3
    exclusions += ["*.tests"]

setup(
    name = "mikroe-uhb",
    version = "0.2",
    packages = find_packages(exclude=exclusions),
    install_requires = install_requires,
    test_suite = "mikroeuhb.tests",
    scripts = ["mikroe-uhb"],
    use_2to3 = True,
)
