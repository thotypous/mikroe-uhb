import os, re, shutil, subprocess, random, tempfile, unittest, logging
from binascii import unhexlify
import repeatable, logexception
import mikroeuhb.bootinfo as bootinfo
bootinfo.logger.addHandler(logexception.LogExceptionHandler(level=logging.WARNING))

class BootInfoCase(unittest.TestCase):
    """Parse self.data, supplied as a string of hex digits, and check
       if the BootInfo dictionary matches self.expected"""
    def runTest(self):
        info = bootinfo.BootInfo(unhexlify(re.sub(r'\s+','',self.data)))
        self.assertDictEqual(info, self.expected)

class MikromediaSTM32(BootInfoCase):
    data = """38012500080000000000100003000040040004000500101306
    00000000000e00076d696b726f6d65646961000000000000000000000000
    000000000000000000"""
    expected = {
        'McuType': 'STM32F4XX',
        'EraseBlock': 0x4000,
        'WriteBlock': 0x4,
        'BootRev': 0x1310,
        'BootStart': 0xe0000,
        'DevDsc': b'mikromedia\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        'McuSize': 0x100000,
    }

class MikromediaDSPIC33(BootInfoCase):
    data = """32010b000800000408000300000c0400800105000013060000
    400500076d696b726f6d6564696100000000000000000000000000000000
    000000000000000000"""
    expected = {
        'McuType': 'DSPIC33',
        'EraseBlock': 0xc00,
        'WriteBlock': 0x180,
        'BootRev': 0x1300,
        'BootStart': 0x54000,
        'DevDsc': b'mikromedia\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        'McuSize': 0x80400,
    }

class PIC18Board(BootInfoCase):
    data = """2b010208008000000340000420000500120600630000074e4f
    204e414d4500000000000000000000000000000000000000000000000000
    000000000000000000"""
    expected = {
        'McuType': 'PIC18',
        'EraseBlock': 0x40,
        'WriteBlock': 0x20,
        'BootRev': 0x1200,
        'BootStart': 0x6300,
        'DevDsc': b'NO NAME\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        'McuSize': 0x8000,
    }
    
class MultiMediaBoardPIC32MX7(BootInfoCase):
    data = """380114000300001004000002050000130600000000c0079d07
    4d4d42204d58370000000000000000000000000000000008000000000008
    000000000000000000"""
    expected = {
        'McuType': 'PIC32',
        'EraseBlock': 0x1000,
        'WriteBlock': 0x200,
        'BootRev': 0x1300,
        'BootStart': 2634530816L,
        'DevDsc': 'MMB MX7\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00',
        'McuSize': 0x80000,
    }

class RandomBootInfo(BootInfoCase):
    """Assemble random BootInfo structs, compile them using gcc -m32,
    and check if they are correctly parsed by us"""
    
    count = 20
    
    _template = """
    #include <stdio.h>
    #include <stdint.h>
    typedef struct {{
            uint8_t type;
            uint8_t value;
    }} sUInt8;
    typedef struct {{
            uint8_t type;
            uint16_t i;
    }} sUInt16;
    typedef struct {{
            uint8_t type;
            uint32_t value;
    }} sUInt32;
    typedef struct {{
            uint8_t type;
            uint8_t value[20];
    }} sString;
    typedef struct {{
	uint8_t size;
        {members}
    }} sBootInfo;
    static const sBootInfo BootInfo = {{
	sizeof(sBootInfo),
        {data}
    }};
    int main() {{
	int i; const uint8_t *buf = (const uint8_t *)&BootInfo;
	for(i = 0; i < BootInfo.size; i++) {{
		printf("%02x", buf[i]);
	}}
	printf("\\n");
	return 0;
    }}
    """
    
    _smap = {1: 'sUInt8', 2: 'sUInt16', 4: 'sUInt32', 20: 'sString'}
    def setUp(self):
        types = set(bootinfo._field.keys()) - set([1])
        n = random.randint(1, len(types))
        types = random.sample(types, n)
        types.append(1)
        random.shuffle(types)
        
        self.expected = {}
        members = ''
        data = ''
        
        for tid in types:
            name, num_bytes, enum_map = bootinfo._field[tid]
            if enum_map:
                allowed = enum_map.keys()
                if tid == 1:
                    reverse_enum_map = dict([(v,k) for k,v in enum_map.iteritems()])
                    disallowed = set([reverse_enum_map[mcu] for x in bootinfo._fieldalign_override.itervalues() for mcu in x.iterkeys()])
                    allowed = list(set(allowed) - disallowed)
                value = random.choice(allowed)
                expected_value = enum_map[value]
            elif num_bytes > 4:
                raw_value = [random.randint(0, 255) for i in xrange(num_bytes)]
                value = '"' + ''.join(['\\x%02x'%x for x in raw_value]) + '"'
                expected_value = bytes(bytearray(raw_value))
            else:
                value = random.randint(0, 1<<(8*num_bytes)-1)
                expected_value = value
            members += '%s %s;\n' % (self._smap[num_bytes], name)
            data += '{%d, %s},\n' % (tid, str(value))
            self.expected[name] = expected_value
            
        program = self._template.format(members=members, data=data)
        self.tempdir = tempfile.mkdtemp('bootinfo')
        sourcefile = os.path.join(self.tempdir, 'test.c')
        programfile = os.path.join(self.tempdir, 'test')
        f = open(sourcefile, 'w')
        f.write(program)
        f.close()
        
        p = subprocess.Popen(['gcc', '-m32', sourcefile, '-o', programfile])
        p.wait()
        p = subprocess.Popen([programfile], stdout=subprocess.PIPE)
        self.data = p.stdout.read().decode('ascii')
        p.stdout.close()
    def tearDown(self):
        shutil.rmtree(self.tempdir)

load_tests = repeatable.make_load_tests([MikromediaSTM32, MikromediaDSPIC33,
                                         MultiMediaBoardPIC32MX7,
                                         PIC18Board, RandomBootInfo])
