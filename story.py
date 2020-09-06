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
from getpass import getpass


class Story():
    def __init__(self, args):
        self.initial_url = args['url']

        # get base url of site
        parsed_url = urlparse(self.initial_url)
        self.base_url = parsed_url.scheme + '://' + parsed_url.hostname
        self.debug = args.get('verbosity', 0)
        self.container = args.get('container', 'div.chapter-content')
        self.next = args.get('next', 'a#next_chap')
        self.title = args.get('title', 'ebook')
        self.filename = args.get('filename', self.title.replace(' ', ''))
        self.style = args.get('style', 'white-style.css')
        self.args = args
        self.story = self.init_story()

    def init_story(self, template_file='template.html'):
        with open(template_file, 'r') as f:
            return BeautifulSoup(f, features='lxml')

    def load_webpage(self, url):
        response = requests.get(url)

        if self.debug > 1:
            print(response.status_code, response.reason)
        if self.debug > 2:
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
                tag = self.add_chapter_title(tag)
                self.story.body.append(tag)

    def add_chapter_title(self, tag):
        if tag.string and (re.search(r'Chapter\s+\d+', tag.text,
                           re.IGNORECASE) is not None):
            tag.name = 'h2'
            tag['class'] = 'chapter'
            if self.debug:
                print(tag.string)

            return tag

    def get_next_url(self, soup):
        next_url = soup.select(self.next)[0].get('href')

        if next_url:
            return self.base_url + next_url
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

    def write(self, filename=None):
        if not filename:
            filename = self.filename
        if '.html' not in filename:
            filename += '.html'
        with open(filename, 'w') as f:
            f.write(self.story.prettify())
        self.html_file = filename

    def convert(self, from_file=None, to_file=None):
        if not from_file:
            from_file = self.html_file
        if not to_file:
            to_file = self.filename
        if '.mobi' not in to_file[5:]:
            to_file += '.mobi'

        params = ['--title', self.title, '--linearize-tables']
        subprocess.run(['ebook-convert', from_file, to_file] + params)
        self.ebook_file = to_file

    def _condition(self, next_url, count, num_chaps):
        if num_chaps:
            return next_url and count < num_chaps
        else:
            return next_url

    def download_ebook(self, num_chapters=None):
        s.add_style(self.style)

        count = 0
        next_url = s.add_chapter(s.initial_url)

        while self._condition(next_url, count, num_chapters):
            next_url = s.add_chapter(next_url)
            count += 1

        self.write()

    def send_ebook(self, title=None, filepath=None, pwfile=None):
        if not title:
            title = self.title
        if not filepath:
            filepath = self.ebook_file

        eml = Email(title, filepath, pwfile)
        eml.send_ebook()


class Email():
    def __init__(self, title, filepath, passfile=None):
        self.title = title
        self.filepath = filepath
        self.askpass = (passfile is None)
        self.passfile = passfile

    def load_pass(self):
        if self.askpass:
            return getpass('Input password for ' + self.msg['From'] + ': ')
        else:
            if os.path.isfile(self.passfile):
                with open(self.passfile) as f:
                    return f.read().strip()
            else:
                print('Could not retrieve email password.')
                return False

    def create_message(self):
        self.msg = email.message.EmailMessage()
        self.msg['From'] = 'jono.nicholas@hotmail.co.uk'
        self.msg['To'] = 'jono.nicholas_kindle@kindle.com'
        self.msg['Subject'] = self.title
        with open(self.filepath, 'rb') as f:
            self.msg.add_attachment(f.read(), maintype='application',
                                    subtype='x-mobipocket-ebook',
                                    filename=self.filepath)

    def send_message(self):
        session = smtplib.SMTP('smtp.office365.com')
        session.ehlo()
        session.starttls()
        session.login(self.msg['From'], self.load_pass())
        session.send_message(self.msg)
        session.quit()
        print('Email sent to ' + self.msg['To'] + '.')

    def send_ebook(self):
        self.create_message()
        self.send_message()


if __name__ == '__main__':
    s = Story({'url': 'https://novelfull.com/' +
               'god-of-slaughter/chapter-1-reborn-in-another-world.html',
               'verbosity': 1,
               'container': 'div.chapter-c > p',
               'next': 'a#next_chap',
               'title': 'God of Slaughter'})

    s.download_ebook()
    s.convert()
    s.send_ebook()
