PubCrawl
========
`As the world doesn't have enough horrible crawlers`

This is a minimalist web crawler written in Python for fun over two evenings. PubCrawl currently uses Redis as a persistent backend for the URL frontier (queue), seen URL sets and Memcache style key expiration for use with robots.txt.

- Multiple Python clients can be started and run at the same time either using multiple processes (multiprocessing) or threads
- The crawl can be stopped and restarted with only a minimal loss of URLs (zero by the future addition of an in-progress set of URLs)

The web crawler respects `robots.txt` through the use of a slightly modified robot exclusion rules parser by Philip Semanchuk. Currently when a website is retrieved the web domain is added as a key to Redis and given an expiry time. The expiry time is either the one provided by `robots.txt` or a one second program default.

For actual production use it's suggested to install a local DNS caching server such as `dnsmasq` or `ncsd` for performance reasons.
