import struct, logging
from util import hexlify, maketrans, bord
from device import Device, Command, HID_buf_size
logger = logging.getLogger(__name__)
if __debug__:
    logger.setLevel(logging.DEBUG)
USE_CACHE = True  # PIC32 uses different virtual locations for cached flash

def encode_instruction(template, field=None, endianness='<'):
    """Encodes a MCU instruction, returning it as a bytestring.
       The template must be supplied as a string of bits, of
       length 8, 16, 24 or 32. The template may contain lowercase
       letters (a-z) which are substituted by a field (from the
       most to the least significant bits). Endianness may be
       specified using Python's struct module notation."""
    _map = {8: 'B', 16: 'H', 24: 'L', 32: 'L'}
    assert(len(template) in _map and endianness in '<>')
    a,z = map(ord, 'az')
    max_c = 0
    for c in template:
        if c not in '01':
            c = ord(c)
            if c < a or c > z:
                raise ValueError('char "%c" disallowed in template' % c)
            max_c = max(max_c, c - a + 1)
    if max_c != 0:
        if field == None:
            raise ValueError('supplied template requires a field')
        orig = ''.join([chr(a+i) for i in xrange(max_c)])
        field = bin(field)[2:].rjust(max_c, '0')
        template = template.translate(maketrans(orig, field))
    instruction = int(template, 2)
    instruction = struct.pack(endianness + _map[len(template)], instruction)
    if len(template) == 24:
        instruction = instruction[:-1] if endianness == '<' else instruction[1:]
    return instruction
    
class DevKitModel:
    """Inherit from this class to implement support for new development kits.
       A devkit class models the device Flash memory blocks, and also specifies
       any changes to the code needed for the bootloader to work."""
    
    flash_mem_offset = 0
    """Offset in memory to which the Flash contents are mapped.
       This value is subtracted from the address supplied to self.write,
       in order to convert "virtual" addresses (seen by the program) to
       "physical" addresses (relative to the start of the Flash memory)."""
    
    def __init__(self, bootinfo):
        """Initialize the devkit model. The bootinfo dictionary needs to
           contain at least the BootStart and EraseBlock fields."""
        for attr in ['BootStart', 'EraseBlock']:
            setattr(self, attr, bootinfo[attr])
        # EraseBlock needs to be a multiple of the HID packet size,
        # otherwise some assumptions made by us when computing remaining
        # buffer space in device (dev_buf_rem) may be broken. 
        assert(self.EraseBlock % HID_buf_size == 0)
        self._init_blocks()
        self._init_blockaddr()
    def _init_blocks(self):
        """Initialize blocks of size EraseBlock from address 0 to BootStart.
           Override this method if a devkit does not have a constant block size.
           This method needs to initialize self.dirty and self.blocks."""
        numblocks = self.BootStart // self.EraseBlock
        block_init = b'\xff' * self.EraseBlock
        # dirty is a list of booleans which tells us if the i-th block is
        # meant to be flashed to the device
        self.dirty = [False for i in xrange(numblocks)]
        # blocks is a list of bytearrays, containing data to be flashed
        # to each flash block
        self.blocks = [bytearray(block_init) for i in xrange(numblocks)]
    def _init_blockaddr(self):
        """Initialize self.blockaddr, a list containing the starting address
           of each Flash memory block. By default, addresses start at zero,
           and are incremented using the size of each block defined in
           self.blocks. Override this method if a devkit does not have
           contiguous Flash memory addresses."""
        self.blockaddr = [0]
        for x in self.blocks:
            self.blockaddr.append(self.blockaddr[-1] + len(x))
    
    def _write_addr(self, blk, blk_off=0):
        """Get the address of a block which needs to be supplied to the
           WRITE command. By default, returns the same as defined in
           self.blockaddr. Override this method if a devkit expects
           addresses supplied to WRITE to be different from the
           physical Flash byte positions."""
        return self.blockaddr[blk] + blk_off
    
    def _erase_addr(self, blk):
        """Get the address of a block which needs to be supplied to the
           ERASE command. By default, returns the same as defined in
           self._write_addr. Override this method if a devkit expects
           addresses supplied to ERASE to be different from the ones
           supplied to WRITE."""
        return self._write_addr(blk)
    
    _ptr = 0
    """Last Flash memory block to which data was written. Used to speed
       up block search based on data locality."""
    
    def _write_phy(self, addr, data):
        """Write a data bytestring or bytearray to a physical Flash
           memory address (relative to self.blockaddr)."""
        # Find the block. Start searching from the last block written.
        blk = self._ptr
        while True:
            try:
                start_addr = self.blockaddr[blk]
                end_addr = start_addr + len(self.blocks[blk])
            except IndexError as err:
                raise IndexError('invalid block %d at address 0x%x' % (
                    blk, addr))
            if addr >= end_addr:
                blk += 1
            elif addr < start_addr:
                blk -= 1
            else:
                break
        self._ptr = blk
        # Write data to the block
        self.dirty[blk] = True
        write_len = min(end_addr - addr, len(data))
        write_off = addr - start_addr
        self.blocks[blk][write_off:write_off+write_len] = data[:write_len]
        # Check if any data is remaining which did not fit into the block
        data = data[write_len:]
        if len(data):
            logger.debug('data trespassing block limits: addr=0x%x, write_len=0x%x' % (addr, write_len))
            self._write_phy(addr + write_len, data)
               
    def write(self, addr, data):
        """Write a data bytestring or bytearray to a "virtual" address
           (address as seen by the program). By default, simply
           subtracts flash_mem_offset from the address. Override this
           method if a devkit has a more complex memory map."""
        self._write_phy(addr - self.flash_mem_offset, data)
    
    def fix_bootloader(self, disable_bootloader=False):
        """Make any changes to the program code needed for the bootloader
           to work. Override this method to implement the changes needed
           for each different devkit. If disable_bootloader is enabled
           (use with caution), the device will be set in a way, if
           supported, such that the bootloader will not be loaded
           automatically anymore."""
        pass
    
    _write_max = 0x8000
    """Maximum amount of data bytes to be transferred during a
       single WRITE command."""
    
    def _blk_interval(self, dev, start, end):
        """Erase and write to the device an interval of Flash memory blocks
           (from "start" to "end")."""
        assert(isinstance(dev, Device))
        dev_buf_size = self.EraseBlock  # size of firmware's char[] fBuffer
        # Erase the Flash memory blocks
        dev.send(Command.from_attr(Command.ERASE,
                                   self._erase_addr(end - 1),
                                   end - start))
        dev.recv().expect(Command.ERASE)
        # Write each block blk
        for blk in xrange(start, end):
            blk_data = self.blocks[blk]
            # Split the Flash memory block into parts containing _write_max bytes.
            for blk_off in xrange(0, len(blk_data), self._write_max):
                data = blk_data[blk_off:blk_off+self._write_max]
                # Inform the device we are starting to send data
                address = self._write_addr(blk, blk_off)
                logger.debug('WRITE %d bytes to address 0x%x' % (
                    len(data), address))
                dev.send(Command.from_attr(Command.WRITE, address, len(data)))
                dev_buf_rem = dev_buf_size
                # Split into USB HID packets
                for i in xrange(0, len(data), HID_buf_size):
                    pkt = data[i:i+HID_buf_size]
                    #logger.debug('sending packet: %s' % repr(pkt))
                    dev.send_data(pkt)
                    dev_buf_rem -= len(pkt)
                    if dev_buf_rem == 0:
                        # Device sends an ACK whenever its buffer gets full
                        dev.recv().expect(Command.WRITE)
                        dev_buf_rem = dev_buf_size
                if dev_buf_rem != dev_buf_size:
                    # Device also sends an ACK when the WRITE command ends
                    # (if it has not just been sent because of a full buffer)
                    dev.recv().expect(Command.WRITE)
            
    def transfer(self, dev):
        """Transfer to the device data which was written to this devkit model"""
        logger.debug('transfer to device starting')
        assert(isinstance(dev, Device))
        numblocks = len(self.dirty)
        # Find ranges of contiguous blocks which are marked as dirty
        inside = False
        for blk in xrange(numblocks+1):
            if inside:
                if blk == numblocks or not self.dirty[blk]:
                    self._blk_interval(dev, start, blk)
                    inside = False
            else:
                if blk != numblocks and self.dirty[blk]:
                    start = blk
                    inside = True
                    

class ARMDevKit(DevKitModel):
    """All ARM-Thumb devkits need bootloader fixes"""
    _supported = ['ARM', 'STELLARIS_M3', 'STELLARIS_M4', 'STELLARIS']
    """The devkits above appear to use the default Flash memory block model,
       thus only the bootloader fix needs to diverge from the base devkit model."""
    def fix_bootloader(self, disable_bootloader=False):
        """Fix the first block to point the reset address to the bootloader.
           Put in the location expected by the bootloader a small ARM-Thumb
           program to initialize the stack pointer and to jump to the program
           being written."""
        first_block = self.blocks[0]
        stackp, resetaddr = struct.unpack('<LL', first_block[:8])
        logger.debug('first block before fix: ' + hexlify(first_block[:8]))
        if resetaddr & 1 != 1:
            logger.warn('reset address 0x%x does not have a Thumb mark -- enforcing it' % resetaddr)
            resetaddr |= 1
        # Change the reset address to point to the bootloader code.
        if not disable_bootloader:
            first_block[4:8] = struct.pack('<L', self.BootStart|1)
        logger.debug('first block after fix: ' + hexlify(first_block[:8]))
        
        def load_r0(value):
            """Return ARM-Thumb instructions for loading a 32-bit value
               into the r0 register."""
            return b''.join([
                # movw r0, #lo
                encode_instruction('0fgh0000ijklmnop11110e100100abcd',
                                   value & 0xffff),
                # movt r0, #hi
                encode_instruction('0fgh0000ijklmnop11110e101100abcd',
                                   (value >> 16) & 0xffff),
            ])
        program = b''.join([
            load_r0(stackp),
            encode_instruction('0100011010000101'),  # mov sp, r0
            load_r0(resetaddr),
            encode_instruction('0100011100000000'),  # bx r0
            ])
        assert(len(program) == 20)  # length expected by bootloader
        
        logger.debug('reset program: ' + hexlify(program))
        self._write_phy(self.BootStart - len(program), program)
        

class STM32DevKit(ARMDevKit):
    """Besides being ARM-Thumb devices, STM32s have a different Flash memory block model. See:
       http://www.mikroe.com/download/eng/documents/compilers/mikroc/pro/arm/help/flash_memory_library.htm#flash_addresstosector
    """
    _supported = ['STM32L1XX', 'STM32F1XX', 'STM32F2XX', 'STM32F4XX']
    """STM32 MCUs are listed above"""
    flash_mem_offset = 0x8000000
    """Flash memory is mapped to the address above. See: 
       https://github.com/ashima/embedded-STM32F-lib/blob/master/readDocs/byhand/memory-overview-STM32F407.xml
    """
    def _init_blocks(self):
        numblocks = 11
        self.dirty = [False for i in xrange(numblocks)]
        self.blocks = []
        def block(size):
            self.blocks.append(bytearray(b'\xff' * size))
        for i in xrange(4):
            block(16 * 1024)
        block(64 * 1024)
        for i in xrange(6):
            block(128 * 1024)
        assert(len(self.blocks) == numblocks)
        assert(sum([len(x) for x in self.blocks]) == self.BootStart)
        

class PIC18DevKit(DevKitModel):
    _supported = ['PIC18', 'PIC18FJ']

    config_data_addr = 0x300000
    """ The address above is used for writing PIC configuration data.
        However, writing this is not supported by the bootloader, so
        we simply ignore any writes to this address."""

    def write(self, addr, data):
        if addr != self.config_data_addr:
            DevKitModel.write(self, addr, data)

    def fix_bootloader(self, disable_bootloader=False):
        first_block = self.blocks[0]
        jump_to_main_prog = first_block[:4]
        logger.debug('first block before fix: ' + hexlify(jump_to_main_prog))
        if not disable_bootloader:
            assert(self.BootStart & 1 == 0)
            k = self.BootStart >> 1
            # http://ww1.microchip.com/downloads/en/DeviceDoc/39500a.pdf p.726
            # GOTO k (2 words instruction)
            first_block[0:2] = encode_instruction('11101111abcdefgh', k & 0xff)
            first_block[2:4] = encode_instruction('1111abcdefghijkl', k >> 8)
        logger.debug('first block after fix: ' + hexlify(first_block[:4]))
        self.write(self.BootStart - len(jump_to_main_prog), jump_to_main_prog)


class PIC24DevKit(DevKitModel):
    _supported = ['PIC24', 'DSPIC', 'DSPIC33']
    
    config_data_addr = 0x1f00008
    """ The address above is used for writing PIC configuration data.
        However, writing this is not supported by the bootloader, so
        we simply ignore any writes to this address."""
    
    def _pic24_addr_to_phy(self, addr):
        """Convert a PIC24/DSPIC address representation to the
           physical number-of-the-byte inside the Flash blocks."""
        assert(addr % 2 == 0)
        return 3*addr//2
    
    def _phy_addr_to_pic24(self, addr):
        """Inverse function of _pic24_addr_to_phy"""
        assert(addr % 3 == 0)
        return 2*addr//3
    
    def _hex_addr_to_phy(self, addr):
        """For every four bytes in a PIC24/DSPIC hexfile, the
           fourth byte is a null padding byte."""
        assert(addr % 4 == 0)
        return 3*addr//4
    
    def _init_blocks(self):
        # Take into account that device informs BootStart in PIC24-style address
        self.BootStart = self._pic24_addr_to_phy(self.BootStart)
        DevKitModel._init_blocks(self)
        self.BootStart = self._phy_addr_to_pic24(self.BootStart)
    
    def _write_addr(self, blk, blk_off=0):
        return self._phy_addr_to_pic24(self.blockaddr[blk] + blk_off)
    
    def write(self, addr, data):
        if addr == self.config_data_addr:
            return
        assert(len(data) % 4 == 0)
        newd = []
        # discard padding bytes (at every fourth byte)
        for i in xrange(0, len(data), 4):
            newd += list(data[i:i+3])
            padbyte = bord(data[i+3])
            if padbyte != 0:
                logger.warning('padding byte at addr 0x%x (%02X) is not null' %
                               (addr+i+3, padbyte))
        # write the new data array
        self._write_phy(self._hex_addr_to_phy(addr), bytearray(newd))
    
    def fix_bootloader(self, disable_bootloader=False):
        first_block = self.blocks[0]
        jump_to_main_prog = first_block[:6]
        logger.debug('first block before fix: ' + hexlify(jump_to_main_prog))
        if not disable_bootloader:
            assert(self.BootStart & 1 == 0)
            # http://ww1.microchip.com/downloads/en/DeviceDoc/70157F.pdf p.250
            # GOTO lit23 (2 words instruction)
            first_block[0:3] = encode_instruction('00000100abcdefghijklmnop',
                                                  self.BootStart & 0xffff)
            first_block[3:6] = encode_instruction('00000000000000000abcdefg',
                                                  self.BootStart >> 16)
        logger.debug('first block after fix: ' + hexlify(first_block[:6]))
        self._write_phy(self._pic24_addr_to_phy(self.BootStart) -
                        len(jump_to_main_prog), jump_to_main_prog)

class PIC32DevKit(DevKitModel):
    _supported = ['PIC32']

    config_data_addr = 0x1fc02ff0  # don't overwrite configuration bits
    ''' http://hades.mech.northwestern.edu
        /index.php/NU32v2:_A_Detailed_Look_at_Programming_the_PIC32
        shows mapping of pic32 addresses to physical addresses'''
    def _pic32_addr_to_phy(self, addr):
        """Convert a PIC32 address representation to the
           physical number-of-the-byte inside the Flash blocks."""
        return addr & 0x1fffffff

    def _phy_addr_to_pic32(self, addr):
        """Inverse function of _pic32_addr_to_phy

           see http://www.johnloomis.org/microchip/pic32/memory/memory.html"""
        if addr >= 0x1fc00000:  # boot ROM
            return addr + 0xa0000000
        elif addr >= 0x1d000000:  # flash, cached or uncached
            if USE_CACHE:
                return addr + 0x80000000
            else:
                return addr + 0xa0000000
        else:
            return addr + 0x80000000

    def _hex_addr_to_phy(self, addr):
        """Every four bytes in a PIC32 hexfile are a word"""
        return addr

    def _write_addr(self, blk, blk_off=0):
        '''
        return the correct physical address for writing
        '''
        return self.blockaddr[blk] + blk_off

    def write(self, addr, data):
        if addr >= self.config_data_addr:
            logger.debug('skipping write to config_data_addr')
            return
        else:
            logger.debug('writing %d bytes to 0x%x' % (len(data), addr))
        if len(data) % 4:
            logger.warning('writing data of length %d' % len(data))
        # write the new data array
        self._write_phy(self._hex_addr_to_phy(addr), bytearray(data))

    def _init_blocks(self, block = None):
        """
        Initialize blocks of size EraseBlock from address 0 to BootStart.
        Override this method if a devkit does not have a constant block size.
        This method needs to initialize self.dirty and self.blocks.

        dirty is a dict of booleans which tells us if the i-th block is
        meant to be flashed to the device

        blocks is a dict of bytearrays, containing data to be flashed
        to each flash block

        FIXME: self.BootStart should be mapped to physical address!
        """
        logger.debug('PIC32 initializing blocks, block = %s' % block)
        numblocks = self.BootStart // self.EraseBlock
        logger.debug('initializing %d blocks of %d bytes each,'
            ' total of 0x%x bytes' % (
                numblocks, self.EraseBlock, self.BootStart))
        block_init = b'\xff' * self.EraseBlock
        if block is None:
            self.dirty = {}
            self.blocks = {}
        else:
            logger.debug('initializing extra block %d' % block)
            self.blocks[block] = bytearray(block_init)
            self.dirty[block] = False

    def _init_blockaddr(self, block = None):
        """
        Initialize self.blockaddr

        a dict containing the starting address of each Flash memory block.
        By default, addresses start at zero,
        and are incremented using the size of each block defined in
        self.blocks. Override this method if a devkit does not have
        contiguous Flash memory addresses.
        """
        logger.debug('PIC32 initializing blockaddr, block = %s' % block)
        self.blockaddr = getattr(self, 'blockaddr', {})
        blocklist = [block] if block is not None else range(len(self.blocks))
        for x in blocklist:
            self.blockaddr[x] = x * self.EraseBlock

    def _write_phy(self, addr, data):
        """Write a data bytestring or bytearray to a physical Flash
           memory address. (Actually just buffers data for `transfer`)"""
        logger.debug('buffering %d bytes to addr 0x%x' % (
            len(data), addr))
        # Find the block.
        blk = addr / self.EraseBlock
        if not blk in self.blocks:
            self._init_blocks(blk)
            self._init_blockaddr(blk)
        start_addr = self.blockaddr[blk]
        end_addr = start_addr + len(self.blocks[blk])
        self._ptr = blk
        # Write data to the block
        self.dirty[blk] = True
        write_len = min(end_addr - addr, len(data))
        write_off = addr - start_addr
        self.blocks[blk][write_off:write_off+write_len] = data[:write_len]
        # Check if any data is remaining which did not fit into the block
        data = data[write_len:]
        if len(data):
            logger.debug('data trespassing block limits: addr=0x%x, write_len=0x%x' % (addr, write_len))
            self._write_phy(addr + write_len, data)

    def fix_bootloader(self, disable_bootloader=False):
        logger.debug('FIXME: fix_bootloader() unimplemented')

    def transfer(self, dev):
        """
        Transfer to the device data which was written to this devkit model

        see http://stackoverflow.com/questions/
            2154249/identify-groups-of-continuous-numbers-in-a-list
        """
        logger.debug('transfer to device starting')
        assert(isinstance(dev, Device))
        # Find ranges of contiguous blocks which are marked as dirty
        from operator import itemgetter
        from itertools import groupby
        inside = False
        blocks = sorted([key for key in self.dirty.keys() if self.dirty[key]])
        for key, group in groupby(enumerate(blocks), lambda(i, x): i - x):
            grouped = map(itemgetter(1), group)
            logger.debug('writing blocks %d through %d' % (
                grouped[0], grouped[1]))
            self._blk_interval(dev, grouped[0], grouped[-1] + 1)

_map = {}
def factory(bootinfo):
    """Factory for constructing devkit objects from a bootinfo dictionary"""
    if len(_map) == 0:
        for clsname, cls in globals().iteritems():
            if hasattr(cls, '_supported'):    
                for mcu in cls._supported:
                    # a mcu cannot be supported by two different classes
                    assert(mcu not in _map)
                    _map[mcu] = cls
    mcu = bootinfo['McuType']
    if not mcu in _map:
        raise NotImplemented('support for this devkit is not yet implemented')
    return _map[mcu](bootinfo)
# vim: tabstop=4 expandtab shiftwidth=4 softtabstop=4
