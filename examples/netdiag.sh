#!/bin/sh

# Network diagnostics image: tcpdump, iproute2 (ip/ss), iputils (ping),
# net-tools (netstat), and curl, plus a shell and the common file tools
# (--filetools). A handy "drop in and poke the network" container.
#
# tcpdump drops privileges to the "tcpdump" user when run as root, so that
# account must exist in the image (-u tcpdump).
#
# CMD defaults to a shell; override it to run any packed tool by full path:
#   docker run --rm netdiag /usr/sbin/ip addr
#   docker run --rm netdiag /usr/bin/tcpdump --version

dockerize -t netdiag \
	-u tcpdump \
	-c /bin/sh \
	--filetools \
	/usr/bin/tcpdump \
	/usr/sbin/ip \
	/usr/bin/ss \
	/usr/bin/ping \
	/usr/bin/netstat \
	/usr/bin/curl \
	/bin/sh
