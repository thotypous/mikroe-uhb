import struct, logging
from binascii import unhexlify
from util import bord
logger = logging.getLogger(__name__)

def load(f, devkit):
    """Load a Intel HEX File from a file object into a devkit.
       The devkit must implement a write(address,data) method."""
    lineno = 0
    base_addr = 0
    for line in f.xreadlines():
        lineno += 1
        line = line.strip()
        if line == '':
            continue
        if bord(line[0]) != ord(':'):
            raise IOError('line %d: malformed' % lineno)
        line = unhexlify(line[1:])
        byte_count, address, record_type = struct.unpack('>BHB', line[:4])
        correct_len = byte_count + 5
        if len(line) != correct_len:
            logger.warn('line %d: should have %d bytes -- truncating' % (lineno, correct_len))
            line = line[:correct_len]
        if sum(map(bord,line)) & 0xFF != 0:
            raise IOError('line %d: incorrect checksum' % lineno)
        data = line[4:-1]
        if record_type == 0x00:    # data record
            devkit.write(base_addr + address, data)
        elif record_type == 0x01:  # end of file record
            break
        elif record_type == 0x04:  # extended linear address record
            if byte_count != 2:
                raise IOError('line %d: extended linear address record must have 2 bytes of data' % lineno)
            base_addr, = struct.unpack('>H', data)
            base_addr <<= 16
        else:
            raise IOError('line %d: unsupported record type %d' % (lineno, record_type))
    