### A naive method to get a dump of the raw link graph (primarily for debugging)
# This will likely not scale beyond a small seen set as the entire list is returned

import redis

if __name__ == "__main__":
  db = redis.Redis()

  seen = db.smembers("seen")
  print "Saving links for %d websites" % len(seen)
  f = open("links.txt", "w")
  for i, link in enumerate(seen):
    for href in db.smembers("links_"+link):
      f.write("%s -> %s\n" % (link, href))

    if i % 1000 == 0:
      print "%d out of %d links extracted" % (i, len(seen))

  f.close()
