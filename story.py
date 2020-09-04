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

        # get base url of site
        parsed_url = urlparse(self.initial_url)
        self.base_url = parsed_url.scheme + '://' + parsed_url.hostname
        self.debug = args.get('verbosity', 0)
        self.container = args.get('container', 'div.chapter-content')
        self.next = args.get('next', 'a#next_chap')
        self.args = args
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
        elif response.status_code == 404:
            return '404'
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
                if tag.string and (re.search(r'Chapter\s+\d+', tag.text)
                                   is not None):
                    tag.name = 'h2'
                    tag['class'] = 'chapter'
                self.story.body.append(tag)

    def get_next_url(self, soup):
        next_url = soup.select(self.next)

        if next_url:
            return self.base_url + next_url[0]['href']
        else:
            print('Could not get next url.')
            return ''

    def add_chapter(self, url):
        page = self.load_webpage(url)
        soup = self.load_soup(page)
        self.process_story_content(soup)
        return self.get_next_url(soup)

    def add_style(self, style_file):
        style = self.story.new_tag('link')
        style['rel'] = 'stylesheet'
        style['type'] = 'text/css'
        style['href'] = os.path.abspath(style_file)
        self.story.head.append(style)


class Email():
    def __init__(self, story, args):
        self.story = story
        self.args = args

    def create_message(self):
        self.msg = {'From': 'jono.nicholas@hotmail.co.uk',
                    'To': 'jono.nicholas_kindle@kindle.com'}


if __name__ == '__main__':
    s = Story({'url': 'https://novelfull.com/' +
               'god-of-slaughter/chapter-119-the-devil-king-bo-xun.html',
               'verbosity': 0,
               'container': 'div.chapter-c > p',
               'next': 'a#next_chap'})

    s.add_style('black-style.css')

    count = 0
    next_url = s.add_chapter(s.initial_url)

    while next_url and count < 10:
        next_url = s.add_chapter(next_url)
        count += 1

    print(s.story.prettify())
