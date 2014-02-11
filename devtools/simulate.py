# Simulates device programming
# usage: simulate.py bootinfo file.hex
from mikroeuhb.tests.device import FakeDevFile
from mikroeuhb.device import Device
from mikroeuhb.bootinfo import BootInfo
from binascii import unhexlify
import sys, re, logging

logging.basicConfig(level=logging.DEBUG)

bootinforaw = re.sub(r'\s+','',sys.argv[1])
assert(len(bootinforaw) % 2 == 0)
bootinforaw += '00' * (64 - len(bootinforaw)/2)
bootinforaw = unhexlify(bootinforaw)

fakefile = FakeDevFile(bootinforaw)
dev = Device(fakefile)
dev.program(open(sys.argv[2]), False)

print('\n'.join(fakefile.transfers))