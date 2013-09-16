#!/usr/bin/python
from setuptools import setup, find_packages
setup(
    name = "mikroe-uhb",
    version = "0.1",
    packages = find_packages(exclude=["*.tests"]),
    install_requires = ["pyudev>=0.13"],
    test_suite = "mikroeuhb.tests",
    scripts = ["mikroe-uhb"],
    use_2to3 = True,
)
