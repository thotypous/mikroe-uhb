import sys
if sys.platform.startswith("linux"):
    from linux import open_dev
else:
    from generic import open_dev
