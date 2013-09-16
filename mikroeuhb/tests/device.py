import random, logging, unittest
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

class FakeDevFile:
    """Fake device file-object which aims to behave like UHB firmware
       revision 0x1200. All data transfered from/to the virtual device
       is appended to self.transfers."""
    bootloadermode = False
    response = None
    idle = True
    counter = 0
    transfers = []
    
    def __init__(self, bootinforaw):
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

class STM32Program(unittest.TestCase):
    """Test if the calculator sample for the STM32 Cortex-M4 devkit
       is written as expected. Important: this test is fragile, and
       may easily fail if the programming algorithm is changed in
       the devkit module."""
    def runTest(self):
        fakefile = FakeDevFile(unhexlify(
            '38012500080000000000100003000040040004000500101306'+
            '00000000000e00076d696b726f6d6564696100000000000000'+
            '0000000000000000000000000000'))
        dev = Device(fakefile)
        dev.program(gzresource('stm32calc.hex.gz'), False)
        expected = [line.strip() for line in gzresource('stm32calc.cap.gz').xreadlines()]
        self.assertListEqual(fakefile.transfers, expected)

load_tests = repeatable.make_load_tests([STM32Program])