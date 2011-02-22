import httplib
import logging
import math
import os
import traceback
import urllib2

from lxml.html import parse as lxml_parse
from urlparse import urlsplit, urlunsplit
from StringIO import StringIO

# Third party libraries
import redis
from robotexclusionrulesparser import RobotExclusionRulesParser

# Settings and configuration - the default is below
SETTINGS = {"DEBUG":False, "THREADED":True, "DIE_EARLY":False, "PROCESSES":128,
  "BUSY_QUEUE_INTERVAL":4, "BUSY_QUEUE_CHUNK":2500, "DEFAULT_ROBOTS_DELAY":1}
def prepare_settings(directory=None, config_file="crawl.cfg"):
  if not directory:
    directory = os.getcwd()
  filename = os.path.join(directory, config_file)

  d = {}
  try:
    execfile(filename, d)
  except IOError:
    logging.info("No configuration file read found at %s" % filename)
    return

  for key in d:
    if key.isupper():
      SETTINGS[key] = d[key]

if SETTINGS["DEBUG"]:
  logging.basicConfig(level=logging.DEBUG)
else:
  logging.basicConfig(level=logging.INFO)

class URLHandler(object):
  @staticmethod
  def add_url(db, url):
    db.lpush("queue", url)

  @staticmethod
  def get_url(db):
    #FIXME: Should use rpoplpush to keep track of in progress URLs
    url = db.rpop("queue")
    # Check if the list is empty
    while URLHandler.is_seen(db, url):
      url = db.rpop("queue")
    URLHandler.add_seen(db, url)
    return url

  @staticmethod
  def add_seen(db, url):
    db.sadd("seen", url)

  @staticmethod
  def is_seen(db, url):
    return db.sismember("seen", url)

  @staticmethod
  def add_to_busy(db, url):
    db.lpush("busy_queue", url)

  @staticmethod
  def get_busy_lock(db, thread_id=0):
    if not db.exists("process_busy_queue"):
      logging.debug("(TID:%d) Acquiring busy lock..." % thread_id)
      db.setnx("process_busy_queue", thread_id)
      db.expire("process_busy_queue", SETTINGS["BUSY_QUEUE_INTERVAL"])
      if int(db.get("process_busy_queue")) == thread_id:
        logging.debug("(TID:%d) Processing busy queue..." % thread_id)
        URLHandler.empty_busy_queue(db)
      else:
        logging.debug("(TID:%d) Failed busy lock attempt" % thread_id)

  @staticmethod
  def empty_busy_queue(db):
    resurrected = 0
    # Only add this link back if we haven't added another from the same domain
    batch = set()
    bq_len = db.llen("busy_queue")
    print bq_len
    for i in xrange(min(SETTINGS["BUSY_QUEUE_CHUNK"], bq_len)):
      link = db.lrange("busy_queue", 0, 0)[0]
      scheme, netloc, path, query, fragment = urlsplit(link)
      # The link is no longer constrained by the crawl delay
      if not db.exists(netloc) and netloc not in batch:
        link = db.lpop("busy_queue")
        db.lpush("queue", link)
        batch.add(netloc)
        resurrected += 1
      # Rotate the list around for O(n) traversal
      db.rpoplpush("busy_queue", "busy_queue")
    logging.info("Resurrected %d links from the busy queue" % resurrected)
    return resurrected

ROBOT_CACHE = {}

class CrawlRequest(object):
  def __init__(self, thread_id=None, database=None, seed_url=None):
    self.thread_id = thread_id or 0
    self.db = database if database else redis.Redis()

    if not seed_url:
      self.url = URLHandler.get_url(self.db)
    else:
      if URLHandler.is_seen(db, seed_url):
        return
      self.url

    if not self.url:
      logging.info("(TID:%s) Empty list" % (thread_id))
      return

    if self.allowed_url():
      try:
        if self.fetch():
          self.parse()
      except urllib2.URLError, e:
        print e
        return

  def allowed_url(self):
    #FIXME: Should use the geturl address as it may have been redirected
    scheme, netloc, path, query, fragment = urlsplit(self.url)
    robot_url = urlunsplit([scheme, netloc, "robots.txt", "", ""])

    #FIXME: Should cache robots.txt in a better persistent data structure
    if robot_url in ROBOT_CACHE:
      rp = ROBOT_CACHE[robot_url]
    else:
      rp = RobotExclusionRulesParser()
      try:
        rp.fetch(robot_url)
      # Currently if there's a problem we assume there is no robots.txt
      except IOError:
        # Should be catching the urllib2.URLError exception
        logging.debug("Couldn't retrieve robots.txt for %s" % robot_url)
        rp = None
      except UnicodeDecodeError:
        logging.debug("Unicode decode error for robots.txt at %s" % robot_url)
        rp = None
      except httplib.HTTPException:
        logging.debug("Generic HTTPException for robots.txt at %s" % robot_url)
        rp = None
      ROBOT_CACHE[robot_url] = rp

    if rp is None or rp.is_allowed("*", self.url):
      base_url = urlunsplit([scheme, netloc, "", "", ""])

      # If there's a current delay on the site respect robots.txt and stall
      if self.db.exists(netloc):
        logging.debug("Obeying robot overlord for %s..." % netloc)
        URLHandler.add_to_busy(self.db, self.url)
        return False

      # Set a delay for any other requests to this site to respect robots.txt
      delay = rp.get_crawl_delay("*") if rp else None
      if delay:
        delay = int(math.ceil(float(rp.get_crawl_delay("*"))))
      else:
        delay = SETTINGS["DEFAULT_ROBOTS_DELAY"]
      self.db.setex(netloc, "1", delay)

      return True
    else:
      return False

  def fetch(self):
    self.f = urllib2.urlopen(self.url)
    logging.info("(TID:%d) Retrieving %s" % (self.thread_id, self.f.geturl()))
    self.db.sadd("seen", self.f.geturl())

    #FIXME: Allow handlers for certain types of content
    if "Content-Type" in self.f.info() and "text/html" in self.f.info()["Content-Type"].lower():
      return True
    else:
      if SETTINGS["DEBUG"]:
        if "Content-Type" in self.f.info():
          logging.debug("Unmatched content: %s" % self.f.info()["Content-Type"])
        else:
          logging.debug("File has no content type")
      return False

  def store(self):
    #TODO
    pass

  def parse(self):
    doc = lxml_parse(StringIO(self.f.read()), base_url=self.f.geturl()).getroot()
    if doc is None:
      return None

    # Make all relative links absolute
    doc.make_links_absolute()

    links = list(doc.cssselect("a"))
    logging.debug("(TID:%d) %s: %d links" % (self.thread_id, "links_"+self.f.geturl(), len(links)))
    for link in links:
      if not link.get("href"):
        continue

      scheme, netloc, path, query, fragment = urlsplit(link.get("href"))
      if scheme.lower() in ["http"]:
        # Add the link to the queue to be processed
        URLHandler.add_url(self.db, link.get("href"))
        # Add the link to the page's link set
        self.db.sadd("links_"+self.f.geturl(), link.get("href"))

def crawl_loop(thread_id=None):
  db = redis.Redis()
  while db.llen("queue") or db.llen("busy_queue"):
    URLHandler.get_busy_lock(db, thread_id)
    try:
      cr = CrawlRequest(thread_id, database=db)
    except:
      #TODO: Store the number and tracebacks of exceptions for later review
      print "Exception in Thread %s" % str(thread_id)
      traceback.print_exc()
      if SETTINGS["DIE_EARLY"]:
        raise

if __name__=="__main__":
  prepare_settings()
  print SETTINGS

  if "SEEDS" in SETTINGS:
    for seed in SETTINGS["SEEDS"]:
      CrawlRequest(seed_url=seed)

  if SETTINGS["THREADED"]:
    from multiprocessing.dummy import Pool
  else:
    from multiprocessing import Pool

  n = SETTINGS["PROCESSES"]

  if SETTINGS["DEBUG"]:
    crawl_loop()
  else:
    p = Pool(n)
    p.map(crawl_loop, range(n))
