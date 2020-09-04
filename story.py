#!/usr/bin/env python3

import requests
import re
from bs4 import BeautifulSoup
from urllib.parse import urlparse
from argparse import ArgumentParser
import os
import subprocess
import email
import smtplib
import mimetypes
import sys
import traceback


class Story():
    def __init__(self, args):
        self.initial_url = args['url']
        self.debug = args.get('verbosity', 0)
        self.container = args.get('container', 'div.chapter-content')
        self.story = self.init_story()

    def init_story(self, template_file='template.html'):
        with open(template_file, 'r') as f:
            return BeautifulSoup(f, features='lxml')

    def load_webpage(self, url):
        response = requests.get(url)

        if self.debug:
            print(response.status_code, response.reason)
        if self.debug > 1:
            print(response.text)

        if response.status_code == 200:
            return response.text
        else:
            return False

    def load_soup(self, page):
        return BeautifulSoup(page, features='lxml')

    def process_story_content(self, soup, container=None):
        if not container:
            container = self.container

        # filter chapter content
        filtered = soup.select(container)

        # add chapter content to story
        if len(filtered) < 1:
            print('Container not found.')
        else:
            for tag in filtered:
                self.story.body.append(tag)


if __name__ == '__main__':
    s = Story({'url': 'https://novelfull.com/' +
               'god-of-slaughter/chapter-119-the-devil-king-bo-xun.html',
               'verbosity': 1,
               'container': 'div.chapter-c > p'})
    page = s.load_webpage(s.initial_url)
    soup = s.load_soup(page)
    s.filter_story_content(soup)
    print(s.story.prettify())
