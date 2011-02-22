PubCrawl
========
`As the world doesn't have enough horrible crawlers`

This is a minimalist web crawler written in Python for fun over two evenings. PubCrawl currently uses Redis as a persistent backend for the URL frontier (queue), seen URL sets and Memcache style key expiration for use with robots.txt. On a commodity laptop with a standard ADSL2+ connection the download rate is a sustained 25-50 pages per second (or 2-4 million crawled pages per day).

- Multiple Python clients can be started and run at the same time either using multiple processes (multiprocessing) or threads
- The crawl can be stopped and restarted with only a minimal loss of URLs (zero by the future addition of an in-progress set of URLs)
- The web crawler respects `robots.txt` even when the crawl is stopped and restarted (as long as the Redis database layer persists)
- PubCrawl only depends on Redis which plays the role of message queue, URL set curator and Memcache server

The web crawler respects `robots.txt` through the use of a slightly modified robot exclusion rules parser by Philip Semanchuk. Currently when a website is retrieved the web domain is added as a key to Redis and given an expiry time. The expiry time is either the one provided by `robots.txt` or a one second program default.

For actual production use it's suggested to install a local DNS caching server such as `dnsmasq` or `ncsd` for performance reasons.

## Dependencies

- Python 2.6 (due to `multiprocessing`)
- Redis
- redis-py `sudo easy_install redis`

## Todo

- Better busy queue implementation for handling links that are constrained due to the `robots.txt` delay
- Improve the `robots.txt` parser to handle Unicode and generally more complex formats
- Implement a flat file storage system for the page contents (as this is currently only useful for the link graph)
- Allow for modifying both the structure, database layer and location of the Redis database server
- Make `CrawlRequest` easily extendible so that a new layer of processing can be added arbitrarily
- The cache for `robots.txt` should be globally accessible and not a localised Python object
- The link graph may be better stored on disk (or at the very least there should be an interface for storage/manipulation)
- Store the number of exceptions and their tracebacks for later review
- Investigate alternative methods for fetching URLs in order to improve the speed and concurrency over `urllib2.urlopen`
