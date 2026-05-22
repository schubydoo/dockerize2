#!/bin/sh

# A minimal static-file web server using mini-httpd. (The original thttpd
# example was dropped: thttpd is no longer packaged in current Debian.)
#
# Demonstrates two patterns at once:
#   * -a SRC DST  — stage a directory of default content into the image.
#   * an entrypoint with baked-in flags, via shell-quoted --entrypoint/--cmd.
#
# Serve the baked-in content:
#   docker run --rm -p 8080:80 httpd
# Serve your own content instead:
#   docker run --rm -p 8080:80 -v /my/content:/var/www httpd

mkdir -p /tmp/www && echo '<h1>dockerize2</h1>' > /tmp/www/index.html

dockerize -t httpd \
	-a /tmp/www /var/www \
	--entrypoint '/usr/sbin/mini_httpd -D -d /var/www -p 80' \
	/usr/sbin/mini_httpd
