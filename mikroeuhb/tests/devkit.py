import random, unittest
from binascii import unhexlify
import mikroeuhb.devkit as devkit
import repeatable

_stm32 = {
    'McuType': 'STM32F4XX',
    'EraseBlock': 0x4000,
    'BootStart': 0xe0000
}

class EncodeInstr(unittest.TestCase):
    def runTest(self):
        for size in [8, 16, 32]:
            devkit.encode_instruction(size*'0')
        self.assertRaises(ValueError,
            lambda: devkit.encode_instruction('0000000a'))
        self.assertRaises(ValueError,
            lambda: devkit.encode_instruction('0000000-', '1'))

class STM32Factory(unittest.TestCase):
    """Check if the bootinfo dictionary is correctly identified for STM32 devices"""
    def runTest(self):
        bootinfo = dict(_stm32)
        for mcu in devkit.STM32DevKit._supported:
            bootinfo['McuType'] = mcu
            self.assertIsInstance(devkit.factory(bootinfo), devkit.STM32DevKit)            

class STM32Bootloader(unittest.TestCase):
    """The beginning of the first block, and the end of the last block before
    bootloader must be modified correctly in STM32 devices"""
    def runTest(self):
        kit = devkit.factory(_stm32)
        self.assertIsInstance(kit, devkit.STM32DevKit)
        kit.write(0x08000000, unhexlify('FCFF0120997E0000417E0000417E0000'))
        kit.fix_bootloader()
        self.assertEqual(unhexlify('FCFF012001000E00'),
                         kit.blocks[0][:8])
        self.assertEqual(unhexlify('4FF6FC70C2F20100854647F69960C0F200000047'),
                         kit.blocks[-1][-20:])
        
class STM32IndexError(unittest.TestCase):
    """Test if we fail correctly when writing outside range or when trying to
    overwrite the bootloader sector"""
    def runTest(self):
        kit = devkit.factory(_stm32)
        self.assertRaises(IndexError,
            lambda: kit.write(0x08000000 - 1, b'\xff'))
        self.assertRaises(IndexError,
            lambda: kit.write(0x08000000 + _stm32['BootStart'], b'\xff'))

class STM32FullFlashBlock(unittest.TestCase):
    """Try to fill the entire flash randomly and assert data does not corrupt
    in the flash-block representation"""
    count = 3
    def runTest(self):
        kit = devkit.factory(_stm32)
        memsize = _stm32['BootStart']
        randmem = bytearray(memsize)
        for i in xrange(memsize):
            randmem[i] = random.randint(0, 255)
        kit.write(0x08000000, randmem)
        self.assertEqual(b''.join(map(bytes,kit.blocks)), bytes(randmem))
        
class STM32RandomWrites(unittest.TestCase):
    """Do self.blkcount random block writes to flash, and check if data
    does not corrupt"""
    count = 10
    blkcount = 5
    def runTest(self):
        kit = devkit.factory(_stm32)
        memsize = _stm32['BootStart']
        randmem = bytearray(memsize)
        for i in xrange(memsize):
            randmem[i] = 255
        for i in xrange(self.blkcount):
            size = random.randint(1, memsize)
            addr = random.randint(0, memsize - size)
            randblk = bytearray(size)
            for j in xrange(size):
                randblk[i] = random.randint(0, 255)
            randmem[addr:addr+size] = randblk
            kit.write(0x08000000 + addr, randblk)
        self.assertEqual(b''.join(map(bytes,kit.blocks)), bytes(randmem))
        
load_tests = repeatable.make_load_tests([
    EncodeInstr, STM32Factory, STM32Bootloader, STM32IndexError,
    STM32FullFlashBlock, STM32RandomWrites
])