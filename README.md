mikroe-uhb
==========

USB HID Bootloader programming application for devices manufactured by MikroElektronika.


Supported devices
-----------------

### ARM devices

Currently, this project was only tested with a **Mikromedia for STM32** development kit. However, from what I understand of the bootloader source code and by reverse engineering the mikroBootloader application supplied by the manufacturer, I believe it should work for any ARM-based development kit currently available from MikroElektronika.

If you plan to test this application using any development kit different from the STM32 ones, please be prepared to use JTAG if something goes wrong (although the bootloader itself has a protection code which should bar most mistakes).

### PIC18 devices

This project is currently under test with PIC18 devices. Many thanks to Kerekes Szilard for providing USB captures and further information.


How to install
--------------

First, you need to check if you have `python-setuptools` installed.
Then, just run:

```
make && sudo make install
```

This application is compatible both with Python 2.7 and with Python 3. The `pyudev` module is required, but will be installed automatically if it is not already present. Currently, only Linux is supported.


How to use
----------

### Printing information about the device

If you just want to see information about a development kit, without programming anything, run:

```
mikroe-uhb
```

You need to unplug/plug or reset the kit after issuing the command above, because this application is solely able to talk with the bootloader firmware, which runs only when the device is starting up.


### Programming the device

To program a hex file to the device, call:

```
mikroe-uhb -v file.hex
```

Then plug the device to the USB port, or press its reset button if it is already plugged to USB.

The `-v` option is meant to print debugging information during the programming process. It can be ommited if you prefer the programming process to be silent.


How to contribute
-----------------

### Support for other devices

I do not own development kits from MikroElektronika other than the Mikromedia for STM32, so I cannot test this project with other devices. However, support for them is certainly welcome.

Most kits need their own `fix_bootloader` implementation in `devkit.py`. PIC32 has a different memory division scheme with I did not study in detail. Kits based on other MCUs should be more straightforward to support.

Code should be self-documenting. There are also some useful tools for dealing with USB captures made with Wireshark under the `devtools` directory. Please read the comments.

If you cannot contribute with code, providing USB capture dumps is very useful. They can be obtained the following way:

* Install this application in your computer, or at least copy the `conf/mikroe-uhb.conf` file to `/etc/modprobe.d`. It is meant to prevent your system from detecting the USB HID Bootloader as a usbtouchscreen and messing things up.
* Install mikroBootloader in a Windows VM inside VirtualBox or other virtualization software with decent USB emulation support.
* Load the `usbmon` module (`modprobe usbmon`) and use Wireshark to start a USB capture. Then, fire mikroBootloader and program your device.
* Please provide me with the capture file saved by Wireshark and with the hex file you used to program your device.

You can also take USB captures directly on Wireshark for Windows if you install the [usbpcap driver](http://desowin.org/usbpcap) and follow the instructions in its website. Please do not forget to use a Wireshark version able to support the driver.

### Support for other operating systems

This project currently only supports Linux. Contributions for introducing support for BSD or other operating systems are welcome.
