import time, hid

RETRY_INTERVAL = .2

class HidApiWrapper(object):
    def __init__(self, h):
        self.h = h
    def write(self, buff):
        self.h.write(bytearray(buff))
    def read(self, max_length):
        return bytes(bytearray(self.h.read(max_length)))

def open_dev(vendor, product):
    """Wait a device to be attached and open it"""
    h = hid.device()
    while True:
        try:
            h.open(vendor, product)
            break
        except IOError as e:
            pass  # device not connected, retry
        time.sleep(RETRY_INTERVAL)
    h.set_nonblocking(False)
    return HidApiWrapper(h)
