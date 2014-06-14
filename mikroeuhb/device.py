import re, struct, logging
from util import hexlify
from bootinfo import BootInfo
logger = logging.getLogger(__name__)

HID_buf_size = 64   # Size of a USB HID packet, fixed by the standard
STX = 0x0f          # Mark for the start of a command in the UHB protocol

class Command:
    """UHB Command"""
    SYNC = 1
    INFO = 2
    BOOT = 3
    REBOOT = 4
    WRITE = 11
    ERASE = 21
    
    stx, cmd, addr, counter = 0, 0, 0, 0
    _fmt = '<BBLH'  # Format of a command
    
    @staticmethod
    def from_buf(buf):
        """Construct a Command object from a bytestring buf"""
        self = Command()
        self.stx, self.cmd, self.addr, self.counter = \
            struct.unpack(self._fmt, buf[:8])
        if self.stx != STX:
            logger.error('missing stx: ' + hexlify(buf))
        return self
    @staticmethod
    def from_attr(cmd, addr=0, counter=0):
        """Construct a Command object with the supplied attributes"""
        self = Command()
        self.stx, self.cmd, self.addr, self.counter = \
            STX, cmd, addr, counter
        return self
    
    def buf(self):
        """Return a bytestring containing a packet which can be sent via USB HID"""
        buf = struct.pack(self._fmt, self.stx, self.cmd, self.addr, self.counter)
        return buf.ljust(HID_buf_size, b'\x00')
    def send(self, f):
        """Send the command to a hidraw device"""
        f.write(b'\x00' + self.buf())
    @staticmethod
    def recv(f):
        """Receive a command from a hidraw device"""
        return Command.from_buf(f.read(HID_buf_size))
    
    _map = None
    def _init_map(self):
        """Init a internal map from command code to string"""
        if not self._map:
            self._map = {}
            for attr in dir(self):
                value = getattr(self, attr)
                if re.match(r'^[A-Z]+$', attr) and isinstance(value, int):
                    self._map[value] = attr

    def __repr__(self):
        self._init_map()
        return '%s, cmd=%s, addr=0x%08x, counter=0x%04x' % (
            'stx' if self.stx == STX else 'invalid',
            self._map[self.cmd] if self.cmd in self._map else hex(self.cmd),
            self.addr, self.counter)
    
    def expect(self, cmd):
        """If the Command code is cmd, return True. Otherwise, log an error
           to this module's logger, and return False."""
        if self.cmd != cmd:
            self._init_map()
            logger.error('Expected command %s, got %d (%s)' % (
                self._map[cmd], self.cmd,
                self._map[self.cmd] if self.cmd in self._map else 'invalid'))
            return False
        return True

class Device:
    bootinfo = None
    def __init__(self, fileObj):
        """Create a Device given a hidraw device file object"""
        self.f = fileObj
    def send(self, cmd):
        """Send a Command"""
        logger.debug('send cmd: ' + repr(cmd))
        cmd.send(self.f)
    def send_data(self, data):
        """Send data (mainly for writing the flash)"""
        logger.debug('send data: ' + hexlify(data))
        self.f.write(b'\x00' + data.ljust(HID_buf_size, b'\xff'))
    def recv(self):
        """Receive a Command (mainly for checking ACKs)"""
        cmd = Command.recv(self.f)
        logger.debug('recv cmd: ' + repr(cmd))
        return cmd
    def recv_data(self):
        """Receive data (mainly for getting the BootInfo struct)"""
        data = self.f.read(HID_buf_size)
        logger.debug('recv data: ' + hexlify(data))
        return data
        
    def _simple_cmd(self, cmd):
        """Send a command which returns an immediate ACK"""
        self.send(Command.from_attr(cmd))
        self.recv().expect(cmd)
    def cmd_sync(self):
        """Send a SYNC command (behaves as a ping)"""
        self._simple_cmd(Command.SYNC)
    def cmd_info(self):
        """Send a INFO command and fill self.bootinfo"""
        self.send(Command.from_attr(Command.INFO))
        self.bootinfo = BootInfo(self.recv_data())
        return self.bootinfo
    def cmd_boot(self):
        """Send a BOOT command (enter into flashing mode)"""
        self._simple_cmd(Command.BOOT)
    def cmd_reboot(self):
        """Send a REBOOT command (restarts the device)"""
        self.send(Command.from_attr(Command.REBOOT))
        
    def program(self, hexf=None, print_info=True, disable_bootloader=False):
        """Do a sequence of commands to program the hexf file
           (codified in Intel HEX format) to the flash memory.
           If hexf is not supplied, only read the bootinfo.
           If print_info is True, print bootinfo to standard output.
           Use disable_bootloader with caution.
        """
        import devkit, hexfile
        bootinfo = self.cmd_info()
        if print_info:
            print 'bootinfo:'
            print(repr(bootinfo))
        if hexf:
            self.cmd_boot()
            self.cmd_sync()
            kit = devkit.factory(bootinfo)
            hexfile.load(hexf, kit)
            kit.fix_bootloader(disable_bootloader)
            kit.transfer(self)
            self.cmd_reboot()
