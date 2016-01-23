import pyudev, logging
logger = logging.getLogger(__name__)

def find_usbid(dev):
    """Walk pyudev device parents until USB idVendor and idProduct
       informations are found"""
    id_keys = ['idVendor', 'idProduct']
    while dev:
        attr = dev.attributes
        try:
            return tuple([int(attr.asstring(k), 16) for k in id_keys])
        except KeyError:
            dev = dev.parent

def wait_dev(vendor, product, subsystem='hidraw'):
    """Wait for a device with the supplied USB vendor and product IDs
       to be attached and identified by a given subsystem.
       Returns a pyudev device object."""
    context = pyudev.Context()
    monitor = pyudev.Monitor.from_netlink(context)
    monitor.filter_by(subsystem)
    monitor.start()
    for dev in iter(monitor.poll, None):
        if dev.action == 'add':
            usbid = find_usbid(dev)
            if not usbid:
                logger.warning('Could not recognize USB ID for device %s' % dev.device_path)
                continue
            logger.info('USB device %04x:%04x plugged' % usbid)
            if usbid == (vendor, product):
                logger.info('USB ID matches the expected one')
                return dev
            
def open_dev(vendor, product):
    """Wait a device to be attached and open its device node"""
    logger.debug('opening device vendor=%x, product=%x' % (vendor, product))
    udev_dev = wait_dev(vendor, product)
    return open(udev_dev.device_node, 'r+b', buffering=0)
