#!/usr/bin/python
from setuptools import setup, find_packages
import sys

install_requires = []
if sys.platform.startswith("linux"):
    install_requires += ["pyudev>=0.13"]
else:
    install_requires += ["hidapi>=0.7.99"]

setup(
    name = "mikroe-uhb",
    version = "0.1",
    packages = find_packages(exclude=["*.tests"]),
    install_requires = install_requires,
    test_suite = "mikroeuhb.tests",
    scripts = ["mikroe-uhb"],
    use_2to3 = True,
)
