import struct, logging
from util import hexlify, maketrans, bord
from device import Device, Command, HID_buf_size
logger = logging.getLogger(__name__)

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

    config_data_addr = None
    """Address used for writing MCU configuration data (if not None).
       Writing this is not supported by the bootloader, so we simply
       ignore any writes to addresses after this address."""

    def __init__(self, bootinfo):
        """Initialize the devkit model. The bootinfo dictionary needs to
           contain at least the BootStart, EraseBlock and McuSize fields."""
        self.BootStart = bootinfo['BootStart']
        self.EraseBlock = bootinfo['EraseBlock']
        self.McuSize = bootinfo['McuSize']
        # EraseBlock needs to be a multiple of the HID packet size,
        # otherwise some assumptions made by us when computing remaining
        # buffer space in device (dev_buf_rem) may be broken.
        assert(self.EraseBlock % HID_buf_size == 0)
        self.blocks = {}
        self._init_blockaddr()

    def _init_blockaddr(self):
        """Initialize blocks of size EraseBlock from address 0 to BootStart.
           Override this method if a devkit does not have a constant block size
           or if Flash memory addresses are not contiguous. This method needs
           to initialize self.blockaddr, a list of tuples defining the span
           interval [start_addr, end_addr) of each block."""
        self.blockaddr = []
        self._init_blockrange(0, self.BootStart)

    def _init_blockrange(self, range_start, range_end):
        """Initialize a range of blocks of size EraseBlock from
        address range_start to range_end."""
        assert((range_end - range_start) % self.EraseBlock == 0)
        self.blockaddr += [(addr, addr + self.EraseBlock) for addr in
                           xrange(range_start, range_end, self.EraseBlock)]

    def _lazy_block(self, blk):
        """Lazily initialize a bytearray for block number blk. Override this
           method if a devkit uses NOR Flash instead of NAND Flash or if there
           are any other reasons for filling self.blocks in a different way."""
        if blk not in self.blocks:
            start_addr, end_addr = self.blockaddr[blk]
            blk_len = end_addr - start_addr
            self.blocks[blk] = bytearray(b'\xff' * blk_len)

    def _write_addr(self, blk, blk_off=0):
        """Get the address of a block which needs to be supplied to the
           WRITE command. By default, returns the same as defined in
           self.blockaddr. Override this method if a devkit expects
           addresses supplied to WRITE to be different from the
           physical Flash byte positions."""
        start_addr, end_addr = self.blockaddr[blk]
        addr = start_addr + blk_off
        assert(addr < end_addr)
        return addr

    def _erase_addr(self, blk):
        """Get the address of a block which needs to be supplied to the
           ERASE command. By default, returns the same as defined in
           self._write_addr. Override this method if a devkit expects
           addresses supplied to ERASE to be different from the ones
           supplied to WRITE."""
        return self._write_addr(blk)

    _ptr = 0
    """Last Flash memory block to which data were written. Used to speed
       up block search based on data locality."""

    def _find_blk(self, addr):
        """Find the Flash block containing a given address."""
        # Start searching from the last block written.
        blk = self._ptr
        while True:
            try:
                start_addr, end_addr = self.blockaddr[blk]
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
        return blk, start_addr, end_addr

    def _write_phy(self, addr, data):
        """Write a data bytestring or bytearray to a physical Flash
           memory address (relative to self.blockaddr)."""
        blk, start_addr, end_addr = self._find_blk(addr)
        # Write data to the block
        self._lazy_block(blk)
        write_len = min(end_addr - addr, len(data))
        write_off = addr - start_addr
        self.blocks[blk][write_off:write_off+write_len] = data[:write_len]
        # Check if any data is remaining which did not fit into the block
        data = data[write_len:]
        if len(data):
            logger.debug('data trespassing block limits: addr=0x%x, write_len=0x%x' % (addr, write_len))
            self._write_phy(addr + write_len, data)

    def _read_phy(self, addr, size):
        """Read a data bytestring from a physical Flash memory address."""
        blk, start_addr, end_addr = self._find_blk(addr)
        read_len = min(end_addr - addr, size)
        read_off = addr - start_addr
        if blk in self.blocks:
            data = bytes(self.blocks[blk][read_off:read_off+read_len])
        else:
            data = b'\xff' * read_len
        if size > read_len:
            data += self._read_phy(addr + read_len, size - read_len)
        return data

    def write(self, addr, data):
        """Write a data bytestring or bytearray to a "virtual" address
           (address as seen by the program). By default, simply
           subtracts flash_mem_offset from the address. Override this
           method if a devkit has a more complex memory map."""
        if self.config_data_addr is None or addr < self.config_data_addr:
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
        """Erase and write to the device the Flash memory block
           interval [start,end)."""
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
        """Transfer to the device data which were written to this devkit model"""
        logger.debug('transfer to device starting')
        assert(isinstance(dev, Device))
        # Find ranges of contiguous blocks to which data were written
        blocks = sorted(self.blocks.keys())
        if len(blocks) == 0:
            return  # nothing to transfer
        previous_end = self.blockaddr[blocks[0]][0]
        frontier_blk = blocks[0]
        previous_blk = blocks[0]
        for blk in blocks:
            start_addr, end_addr = self.blockaddr[blk]
            if start_addr != previous_end:
                self._blk_interval(dev, frontier_blk, previous_blk+1)
                frontier_blk = blk
            previous_end = end_addr
            previous_blk = blk
        self._blk_interval(dev, frontier_blk, previous_blk+1)


class ARMDevKit(DevKitModel):
    """Implements bootloader fixes for all ARM-Thumb devkits"""
    _supported = ['ARM', 'STELLARIS_M3', 'STELLARIS_M4', 'STELLARIS', 'TIVA_M4']
    """The devkits above appear to use the default Flash memory block model,
       thus only the bootloader fix needs to diverge from the base devkit model."""
    def fix_bootloader(self, disable_bootloader=False):
        """Fix the first block to point the reset address to the bootloader.
           Put in the location expected by the bootloader a small ARM-Thumb
           program to initialize the stack pointer and to jump to the program
           being written."""
        reset_vec = self._read_phy(0, 8)
        stackp, resetaddr = struct.unpack('<LL', reset_vec)
        logger.debug('reset vector before fix: ' + hexlify(reset_vec))
        if resetaddr & 1 != 1:
            logger.warn('reset address 0x%x does not have a Thumb mark -- enforcing it' % resetaddr)
            resetaddr |= 1
        # Change the reset address to point to the bootloader code.
        if not disable_bootloader:
            self._write_phy(4, struct.pack('<L', self.BootStart|1))
        logger.debug('reset vector after fix:  ' + hexlify(self._read_phy(0, 8)))

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

        logger.debug('start program routine: ' + hexlify(program))
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
    def _init_blockaddr(self):
        block_list = [(4,  16*1024),
                      (1,  64*1024),
                      (6, 128*1024)]
        self.blockaddr = []
        start_addr = 0
        for number_of_blocks, block_size in block_list:
            for i in xrange(number_of_blocks):
                end_addr = start_addr + block_size
                self.blockaddr.append((start_addr, end_addr))
                start_addr = end_addr
        assert(end_addr == self.BootStart)


class PIC18DevKit(DevKitModel):
    _supported = ['PIC18', 'PIC18FJ']

    config_data_addr = 0x300000

    def fix_bootloader(self, disable_bootloader=False):
        jump_to_main_prog = self._read_phy(0, 4)
        logger.debug('reset code before fix: ' + hexlify(jump_to_main_prog))
        if not disable_bootloader:
            assert(self.BootStart & 1 == 0)
            k = self.BootStart >> 1
            # http://ww1.microchip.com/downloads/en/DeviceDoc/39500a.pdf p.726
            # GOTO k (2 words instruction)
            self._write_phy(0, encode_instruction('11101111abcdefgh', k & 0xff))
            self._write_phy(2, encode_instruction('1111abcdefghijkl', k >> 8))
        logger.debug('reset code after fix:  ' + hexlify(self._read_phy(0, 4)))
        self._write_phy(self.BootStart - len(jump_to_main_prog), jump_to_main_prog)


class PIC24DevKit(DevKitModel):
    _supported = ['PIC24', 'DSPIC', 'DSPIC33']

    config_data_addr = 0x1f00008

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

    def _init_blockaddr(self):
        # Take into account that device informs BootStart in PIC24-style address
        origBootStart = self.BootStart
        self.BootStart = self._pic24_addr_to_phy(self.BootStart)
        DevKitModel._init_blockaddr(self)
        self.BootStart = self._phy_addr_to_pic24(self.BootStart)
        assert(self.BootStart == origBootStart)

    def _write_addr(self, blk, blk_off=0):
        return self._phy_addr_to_pic24(DevKitModel._write_addr(self, blk, blk_off))

    def write(self, addr, data):
        if addr >= self.config_data_addr:
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
        jump_to_main_prog = self._read_phy(0, 6)
        logger.debug('reset code before fix: ' + hexlify(jump_to_main_prog))
        if not disable_bootloader:
            assert(self.BootStart & 1 == 0)
            # http://ww1.microchip.com/downloads/en/DeviceDoc/70157F.pdf p.250
            # GOTO lit23 (2 words instruction)
            self._write_phy(0, encode_instruction('00000100abcdefghijklmnop',
                                                  self.BootStart & 0xffff))
            self._write_phy(3, encode_instruction('00000000000000000abcdefg',
                                                  self.BootStart >> 16))
        logger.debug('reset code after fix:  ' + hexlify(self._read_phy(0, 6)))
        self._write_phy(self._pic24_addr_to_phy(self.BootStart) -
                        len(jump_to_main_prog), jump_to_main_prog)


class PIC32DevKit(DevKitModel):
    _supported = ['PIC32']

    main_flash_addr = 0x1d000000
    boot_rom_addr   = 0x1fc00000

    config_data_addr = boot_rom_addr | 0x2ff0  # configuration bits

    def _init_blockaddr(self):
        self.blockaddr = []
        
        self._init_blockrange(self.main_flash_addr, self.main_flash_addr + self.McuSize)
        # The last Flash block range should stop before the the start of the block
        # containing configuration bits, to prevent its erasure.
        config_offset_in_block = (self.config_data_addr - self.boot_rom_addr) % self.EraseBlock
        config_block_start = self.config_data_addr - config_offset_in_block
        self._init_blockrange(self.boot_rom_addr, config_block_start)

    def _pic32_addr_to_phy(self, addr):
        """Convert a PIC32 address representation to the
        physical number-of-the-byte inside the Flash blocks."""
        return addr & 0x1fffffff

    def _phy_addr_to_pic32(self, addr, use_cache=True):
        """Inverse function of _pic32_addr_to_phy

        see http://www.johnloomis.org/microchip/pic32/memory/memory.html"""
        if addr >= self.boot_rom_addr:
            return addr + 0xa0000000
        elif addr >= self.main_flash_addr: # flash, cached or uncached
            if use_cache:
                return addr + 0x80000000
            else:
                return addr + 0xa0000000
        else:
            return addr + 0x80000000

    def fix_bootloader(self, disable_bootloader=False):
        boot_rom_first_instr, = struct.unpack('<L',
            self._read_phy(self.boot_rom_addr, 4))
        logger.debug('first instruction on boot rom: 0x%08x' %
            boot_rom_first_instr)
        def jump_to(addr):
            return struct.pack('<4L',
                0x3c1e0000 | (addr >> 16),     # lui $30,[addr>>16]
                0x37de0000 | (addr & 0xffff),  # ori $30,$30,[addr&0xffff]
                0x03c00008,                    # jr $30
                0x70000000)                    # nop
        startprogram_routine = jump_to(
            self._phy_addr_to_pic32(self.boot_rom_addr + 0x50))
        startprogram_routine_len = len(startprogram_routine)
        startprogram_routine_addr = self._pic32_addr_to_phy(
            self.BootStart - startprogram_routine_len)
        if boot_rom_first_instr in (0x27bdfffc,  # addiu $sp,$sp,-4
                                    0x70000000): # nop
            jump_bootstart_displ = 0x40
        else:
            jump_bootstart_displ = 0
            startprogram_routine = self._read_phy(
                self.boot_rom_addr, startprogram_routine_len)
        logger.debug('start program routine before fix: ' +
                     hexlify(self._read_phy(startprogram_routine_addr,
                                            startprogram_routine_len)))
        logger.debug('start program routine after fix:  ' +
                     hexlify(startprogram_routine))
        self._write_phy(startprogram_routine_addr, startprogram_routine)
        if not disable_bootloader:
            jump_bootstart_addr = self.boot_rom_addr + jump_bootstart_displ
            jump_bootstart_code = jump_to(self.BootStart)
            jump_bootstart_len = len(jump_bootstart_code)
            logger.debug('jump to bootstart before fix: ' +
                         hexlify(self._read_phy(jump_bootstart_addr,
                                                jump_bootstart_len)))
            self._write_phy(jump_bootstart_addr, jump_bootstart_code)
            logger.debug('jump to bootstart after fix:  ' +
                         hexlify(jump_bootstart_code))
            
class PIC32MZDevKit(PIC32DevKit):
    _supported = ['PIC32MZ']

    boot_rom_addr   = 0x1fc00000

    config_data_addr = boot_rom_addr | 0xff00  # configuration bits
