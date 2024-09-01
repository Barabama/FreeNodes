# items.py

import scrapy


class NodeItem(scrapy.Item):
    name = scrapy.Field()
    ext = scrapy.Field()
    date = scrapy.Field()
    body = scrapy.Field()


class GeoLocItem(scrapy.Item):
    filename = scrapy.Field()
    geoloc = scrapy.Field()
    node = scrapy.Field()
