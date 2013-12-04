import re, random, logging, unittest
from pkg_resources import resource_stream
from binascii import unhexlify, hexlify
from gzip import GzipFile
import mikroeuhb.device as device
from mikroeuhb.device import Device, Command, HID_buf_size
from mikroeuhb.bootinfo import BootInfo
from mikroeuhb.util import bord
import repeatable, logexception
device.logger.addHandler(logexception.LogExceptionHandler(level=logging.WARNING))

def gzresource(filename):
    """Returns a file object for reading a gzip compressed file in the
    current package directory"""
    gzf = GzipFile(fileobj=resource_stream(__name__, filename), mode='rb')
    if not hasattr(gzf, 'xreadlines'):
        gzf.xreadlines = gzf.readlines
    return gzf

class FakeDevFile(object):
    """Fake device file-object which aims to behave like UHB firmware
       revision 0x1200. All data transfered from/to the virtual device
       is appended to self.transfers."""
    def __init__(self, bootinforaw):
        self.bootloadermode = False
        self.response = None
        self.idle = True
        self.counter = 0
        self.transfers = []
        self.bootinforaw = bootinforaw
        self.bootinfo = BootInfo(bootinforaw)
        self.bufsize = self.bootinfo['EraseBlock']  # size of firmware's char[] fBuffer
    
    def _set_response(self, response):
        assert(self.response == None)  # previous response was read
        assert(len(response) == HID_buf_size)
        self.response = response
    
    def read(self, size):
        assert(size == HID_buf_size)
        assert(self.response != None)  # there is something to be read
        ret, self.response = self.response, None
        self.transfers.append(b'i ' + hexlify(ret))
        return ret
        
    def write(self, buf):
        # "The first byte of the buffer passed to write() should be set to the report
        #  number.  If the device does not use numbered reports, the first byte should
        #  be set to 0. The report data itself should begin at the second byte."
        # -- Linux kernel - Documentation/hid/hidraw.txt
        assert(bord(buf[0]) == 0)  # hidraw always strips the first byte if it is zero!
        buf = buf[1:]
        assert(len(buf) == HID_buf_size)
        assert(self.response == None)  # response was read before sending more data
        self.transfers.append(b'o ' + hexlify(buf))
        if self.idle:
            cmd = Command.from_buf(buf)
            if self.bootloadermode:
                assert(cmd.cmd not in [cmd.INFO, cmd.BOOT])
            else:
                assert(cmd.cmd in [cmd.INFO, cmd.BOOT])
            if cmd.cmd == cmd.WRITE:
                self.idle = False
                self.counter = cmd.counter
                self.availbuf = self.bufsize
            elif cmd.cmd == cmd.INFO:
                self._set_response(self.bootinforaw)
            elif cmd.cmd != cmd.REBOOT:
                if cmd.cmd == cmd.BOOT:
                    self.bootloadermode = True
                self._set_response(Command.from_attr(cmd.cmd).buf())
        else:
            readlen = min(self.counter, len(buf))
            self.counter -= readlen
            self.availbuf -= readlen
            assert(self.counter >= 0)
            assert(self.availbuf >= 0)
            if self.availbuf == 0 or self.counter == 0:
                self.availbuf = self.bufsize
                self._set_response(Command.from_attr(Command.WRITE).buf())
            if self.counter == 0:
                self.idle = True

class DevKitCase(unittest.TestCase):
    """Important: tests derived from this class are fragile, and
       may easily fail if the programming algorithm is changed in
       the devkit module."""
    def runTest(self):
        fakefile = FakeDevFile(unhexlify(re.sub(r'\s+','',self.bootinfo)))
        dev = Device(fakefile)
        dev.program(gzresource(self.hexfile), False)
        expected = [line.strip() for line in gzresource(self.capfile).xreadlines()]
        self.assertListEqual(fakefile.transfers, expected)

class STM32Program(DevKitCase):
    """Test if the calculator sample for the STM32 Cortex-M4 devkit
       is written as expected."""
    bootinfo = """380125000800000000001000030000400400040005001013
    0600000000000e00076d696b726f6d65646961000000000000000000000000
    000000000000000000"""
    hexfile = 'stm32calc.hex.gz'
    capfile = 'stm32calc.cap.gz'

class PIC18Program(DevKitCase):
    """Test if the LED blinking sample kindly provided by
       Kerekes Szilard is written as expected onto a
       PIC18 devkit."""
    bootinfo = """2b010208008000000340000420000500120600630000074e
    4f204e414d4500000000000000000000000000000000000000000000000000
    000000000000000000"""
    hexfile = 'pic18ledblink.hex.gz'
    capfile = 'pic18ledblink.cap.gz'

load_tests = repeatable.make_load_tests([STM32Program, PIC18Program])
