"""Useful functions, mainly for Python 2/3 portability"""
import string, binascii

def hexlify(data):
    """The binascii.hexlify function returns a bytestring in
       Python3, but sometimes we want to use its output to
       show a log message. This function returns an unicode
       str, which is suitable for it."""
    return binascii.hexlify(data).decode('ascii')

def maketrans(fromstr, tostr):
    """In Python2, maketrans is defined in the string module.
       In Python3, it is defined in the str object.
       This calls the adequate function."""
    try:
        return string.maketrans(fromstr, tostr)
    except AttributeError as err:
        return str.maketrans(fromstr, tostr)

def bord(c):
    """In Python2, one calls ord(buf[i]) to get the i-th byte of
       a bytestring. In Python3, buf[i] already returns an int.
       Call bord(buf[i]) to achieve portability."""
    if isinstance(c, int):
        return c
    return ord(c)