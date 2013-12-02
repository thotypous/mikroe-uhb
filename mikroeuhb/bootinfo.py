import struct, logging
from util import bord
logger = logging.getLogger(__name__)

# Map MCU type numeric codes to their names
_mcutype_enum = {
    1:  'PIC16', 2: 'PIC18', 3: 'PIC18FJ', 4: 'PIC24',
    10: 'DSPIC',
    20: 'PIC32',
    30: 'ARM',
    31: 'STELLARIS_M3',
    32: 'STELLARIS_M4',
    33: 'STELLARIS',
    34: 'STM32L1XX',
    35: 'STM32F1XX',
    36: 'STM32F2XX',
    37: 'STM32F4XX',
}

# Fields which may be present in a BootInfo struct, in the following format:
# id: (name, number of bytes, enum_map)
# If number of bytes exceeds 4, we assume the field contains a char[].
_field = {
    1: ('McuType',     1, _mcutype_enum),
    2: ('McuId',       4, None),  # XXX apparently unused
    3: ('EraseBlock',  2, None),
    4: ('WriteBlock',  2, None),
    5: ('BootRev',     2, None),
    6: ('BootStart',   4, None),
    7: ('DevDsc',     20, None),
    8: ('McuSize',     4, None),
}
assert(0 not in _field)  # No field shall have a zero id

# 16-bit MCUs apparently have packed structs
# XXX Needs further assessment. Works with bootinfo data obtained from a
#     PIC18 board kindly provided by Kerekes Szilard. However, I have seen
#     some code for aligning 32-bit fields to 16-bit on these MCUs when
#     reverse engineering the mikrobootloader executable.
_16bit_mcus = ['PIC16', 'PIC18', 'PIC18FJ', 'PIC24', 'DSPIC']
_fieldalign_override = dict([(field_name,
                              dict([(mcu, 1) for mcu in _16bit_mcus])) 
                             for field_name,_,_ in _field.itervalues()])

class BootInfo(dict):
    def __init__(self, buf, endianness='<'):
        """Parse a bytestring buf containing a BootInfo struct.
           Endianness may be provided using Python's struct module notation,
           but should always be little-endian for all current Mikroe kits,
           at least from what I know."""
        def unpack(fmt, buf):
            return struct.unpack(endianness + fmt, buf)
        
        # Get sizeof struct and truncate it
        bSize = bord(buf[0])
        buf = buf[:bSize]
        pos = 1
        
        while pos < len(buf):
            # Skip initial field padding
            pad = 0
            while pos < len(buf) and bord(buf[pos]) == 0:
                pos += 1
                pad += 1
            if pos >= len(buf): break
            
            # Parse field type
            field_type = bord(buf[pos])
            if field_type not in _field:
                logger.error('Field %d not recognized -- aborting parsing' % field_type)
                break
            
            name, num_bytes, enum_map = _field[field_type]
            pad_bytes = min(num_bytes, 4)
            
            # Check for any alignment override
            if 'McuType' in self and name in _fieldalign_override:
                pad_bytes = _fieldalign_override[name].get(self['McuType'], pad_bytes)
                
            # Sanity check the detected initial padding
            if pad >= pad_bytes or (num_bytes <= 4 and pos % pad_bytes != 0):
                logger.warn('Initial padding of %d inadequate in field "%s" (%d)' % (pad, name, field_type))
                
            # Go to data (skip the internal padding)
            pos += 1
            if num_bytes <= 4:    
                pad = (pad_bytes - pos % pad_bytes) % pad_bytes
                pos += pad
                
            # Read the value
            fmt = {1: 'B', 2: 'H', 4: 'L'}
            value = buf[pos:pos+num_bytes]
            if num_bytes in fmt:
                value, = unpack(fmt[num_bytes], value)
            pos += num_bytes
            
            # Fill the field
            if enum_map:
                if value in enum_map:
                    value = enum_map[value]
                else:
                    logger.warn('Field "%s" (%d) contains value %d not mapped in its enum' % (name, field_type, value))
            if name in self:
                logger.warn('Field "%s" (%d) duplicated -- discarding old value: %s' % (name, field_type, repr(fields[name])))
            self[name] = value
            
    def __repr__(self):
        """Pretty-print the fields in the same order as specified in _field"""
        s = ''
        for k,_,_ in _field.itervalues():
            if k not in self: continue
            v = self[k]
            if isinstance(v, int):
                v = '0x%x' % v
            elif isinstance(v, bytes):
                v = v.split(b'\x00', 1) [0]
                v = repr(v)
            else:
                v = repr(v)
            s += '%s: %s\n' % (k,v)
        return s
