#!/bin/sh

# curl — demonstrates the two real-world gotchas for HTTPS in a scratch image:
#   * TLS:  the CA certificate bundle must be copied in, or HTTPS requests
#           fail with a certificate-verification error. We stage /etc/ssl/certs.
#   * DNS:  name resolution needs the right NSS modules. dockerize copies
#           files,dns by default; --nss-modules makes that explicit here.
#
#   docker run --rm curl -fsSL https://example.com

dockerize -t curl \
	--nss-modules files,dns \
	-a /etc/ssl/certs /etc/ssl/certs \
	-e /usr/bin/curl \
	/usr/bin/curl
