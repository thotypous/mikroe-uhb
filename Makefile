PYTHON = python
INSTALL = install
all:
	$(PYTHON) setup.py build
test:
	$(PYTHON) setup.py test
install:
	$(PYTHON) setup.py install
	$(INSTALL) -m 644 conf/51-mikroe-uhb.rules $(DESTDIR)/etc/udev/rules.d
	$(INSTALL) -m 644 conf/mikroe-uhb.conf $(DESTDIR)/etc/modprobe.d
