"""
Author: Richard Baldwin
Date:   2024
E-mail: eyeclept@pm.me

"""
from scrapy.spiders import CrawlSpider, Rule
from scrapy.linkextractors import LinkExtractor
# classes


class LocalSpider(CrawlSpider):
    name = "local_spider"
    allowed_domains = ["epinisea.lan"] 
    start_urls = ("http://unused5.epinisea.lan:8080/wikipedia_en_all_mini_2024-04/A/User:The_other_Kiwix_guy/Landing",)
    rules = (
        Rule(LinkExtractor(unique=True), follow=True, callback="parse_item"),
    )

    custom_settings = {
        #'ROBOTSTXT_OBEY': False,  # Temporarily disable robots.txt compliance
        "DEPTH_LIMIT": 2
    }

    def parse_item(self, response):
        # Check if the URL is within the allowed domain
        if 'epinisea.lan' not in response.url:
            return

        # Now you can process the URL and extract data as needed
        yield {
            'url': response.url,
            'title': response.css('title::text').get(),
        }