#!/usr/bin/python
"""A standalone dissector for files processed by usbcap.awk"""
import sys, struct
from binascii import hexlify, unhexlify
EraseBlock = 0x4000  # change according to the one reported by the device
cmd_enum = {
    1: 'SYNC',
    2: 'INFO',
    3: 'BOOT',
    4: 'REBOOT',
    11: 'WRITE',
    21: 'ERASE',
}
idle = True
counter, buf_size = 0, 0
for line in sys.stdin.readlines():
    direction, data = line.strip().split(' ', 2)
    data = unhexlify(data)
    assert(direction in ('i','o'))
    if direction == 'i':
        if data in (b'\x00', b'\x02'):
            print('In: USB RESET')
        elif data[0:1] == b'\x0f':
            cmd = ord(data[1:2])
            print('In: ACK: %5s (%02x)' % (cmd_enum[cmd], cmd))
        else:
            print('In: BootInfo? (len=%d)' % ord(data[0:1]))
    else:
        if idle:
            stx, cmd, addr, counter = struct.unpack('<BBLH', data[:8])
            assert(stx == 0x0f)
            cmd = cmd_enum[cmd]
            print('Out: CMD %5s (addr=0x%08x counter=0x%04x)' % (cmd, addr, counter))
            if cmd == 'WRITE':
                buf_size = EraseBlock
                idle = False
        else:
            read_len = min(counter, len(data))
            print('Out: Data %s' % hexlify(data[:read_len]).upper().decode('ascii'))
            counter -= read_len
            buf_size -= read_len
            assert(buf_size >= 0)
            assert(counter >= 0)
            if buf_size == 0 or counter == 0:
                buf_size = EraseBlock
                print('Expecting ACK')
            if counter == 0:
                idle = True
            
