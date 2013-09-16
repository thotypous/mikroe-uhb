#!/usr/bin/awk -f
# Wireshark can export packet dissections collected during a USB capture:
#   File -> Export Packet Dissections -> as XML - "PDML" (packet details) file
# This script converts the XML file to a more simple format, compatible with
# the one used by mikroeuhb.tests.FakeDevFile.transfers. This way, captures
# made when running mikrobootloader in a virtual machine can be compared
# (using e.g. gvimdiff) to the behavior of this project.
{
	if(match($0, /Direction: (IN|OUT)/, a))
		dir = a[1] == "IN" ? "i" : "o"
}
/field name="usb\.capdata"/ {
	if(match($0, /value="([0-9a-f]+)"/, a))
		print dir " " a[1]	
}
