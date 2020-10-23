#!/usr/bin/env python3

import requests
import re
from bs4 import BeautifulSoup, NavigableString
from urllib.parse import urlparse
from argparse import ArgumentParser
import os
import sys
import subprocess
import email
import smtplib
from getpass import getpass
import yaml


class Story():
    def __init__(self, args):
        self.initial_url = args['url']

        # get base url of site
        parsed_url = urlparse(self.initial_url)
        self.base_url = parsed_url.scheme + '://' + parsed_url.hostname
        self.debug = args.get('verbosity', 0)
        self.container = args.get('container', 'div.chapter-content')
        self.next = args.get('next', 'a#next_chap')
        self.chap_title_css = args.get('detect_title', False)
        self.title = args.get('title', 'ebook')
        self.filename = args.get('filename', self.title.replace(' ', ''))
        self.cwd = os.path.dirname(sys.argv[0])
        self.html_folder = os.path.join(self.cwd, 'html')
        self.ebook_folder = os.path.join(self.cwd, 'mobi')
        self.html_file = os.path.join(self.html_folder,
                                      self.filename + '.html')
        self.ebook_file = os.path.join(self.ebook_folder,
                                       self.filename + '.mobi')
        self.style = args.get('style', 'white-style.css')
        self.args = args
        self.story = self.init_story()
        self.current_chapter = 0

    def init_story(self, template_file='template.html'):
        with open(template_file, 'r') as f:
            return BeautifulSoup(f, features='lxml')

    def load_webpage(self, url):
        headers = {'User-Agent': 'Mozilla/5.0 (X11; Ubuntu; Linux i686; \
                    rv:24.0) Gecko/20100101 Firefox/24.0'}
        response = requests.get(url, headers=headers)

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

    def process_story_content(self, soup, container=None, detect_title=False):
        if not container:
            container = self.container

        # filter chapter content
        filtered = soup.select(container)

        # add div wrapper to each chapter
        # add chapter content to story
        if len(filtered) < 1:
            print('Chapter content not found.')
            return False

        chapter = soup.new_tag('div')
        chapter['class'] = 'chp'

        title = self.get_chapter_title(soup)
        chapter.append(title)

        for tag in filtered:
            chapter.append(tag)

        if self.debug > 2:
            print(chapter.prettify())

        self.story.body.append(chapter)

    def get_chapter_title(self, soup):
        heading = soup.new_tag('h2')
        heading['class'] = 'chapter-heading'
        title = ''

        if self.chap_title_css:
            tag = soup.select_one(self.chap_title_css)
            title = re.sub(r'chapter\s(\d+)\s+[:-]+\s+', '', tag.string,
                           flags=re.IGNORECASE)

        self.current_chapter += 1
        chap_title = 'Chapter ' + str(self.current_chapter)
        chap_title += (' - ' + title) if title else ''
        heading.string = NavigableString(chap_title)

        if self.debug:
            print(chap_title)

        return heading

    def get_next_url(self, soup):
        try:
            next_url = soup.select(self.next)[0].get('href')
        except IndexError:
            print(f'Could not locate {self.next}.')
            if self.debug > 1:
                print('\n' + soup.prettify() + '\n')
            return ''

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

    def add_script(self, script_file):
        script = self.story.new_tag('script')
        script['src'] = script_file
        self.story.head.append(script)

    def write(self, filename=None):
        if filename:
            self.html_file = os.path.join(self.html_folder, self.filename)
        if '.html' not in self.html_file:
            self.html_file += '.html'
        with open(self.html_file, 'w') as f:
            f.write(self.story.prettify())

    def convert(self, from_file=None, to_file=None):
        if not from_file:
            from_file = self.html_file
        if not to_file:
            to_file = self.ebook_file
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

    def download_ebook(self, num_chapters=None, filename=None,
                       script_files=None, html_attrs=None):
        self.add_style(self.style)
        if script_files:
            for script in script_files:
                self.add_script(script)

        if html_attrs:
            for element in html_attrs:
                for attr, val in element.items():
                    self.story[element][attr] = val

        count = 0
        next_url = self.add_chapter(s.initial_url)

        try:
            while self._condition(next_url, count, num_chapters):
                try:
                    next_url = self.add_chapter(next_url)
                except IndexError:
                    next_url = False
                count += 1
        except KeyboardInterrupt:
            pass

        self.write(filename)

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


class Args(ArgumentParser):
    def __init__(self):
        super().__init__()
        args = self.get_args()
        self.story = self.load_story_args(args)
        self.extras = {}

        for key, val in args.__dict__.items():
            if key not in self.story:
                self.extras[key] = val

    def load_story_args(self, args={}):
        sargs = args.__dict__.copy()
        for key, item in self.get_template(sargs['input_template']).items():
            if not sargs[key]:
                sargs[key] = item

        extras = ['input_template', 'no_download', 'no_convert', 'no_email']
        for e in extras:
            del sargs[e]

        return sargs

    def get_args(self):
        story = self.add_argument_group('story')
        debug = self.add_argument_group('debug')
        actions = self.add_argument_group('actions')
        story.add_argument('-u', '--url', help='URL of first chapter')
        story.add_argument('-i', '--input-template',
                           help='Specify template of arguments')
        story.add_argument('-t', '--title', help='Ebook title', default='book')
        story.add_argument('-c', '--container', help='Chapter container CSS')
        story.add_argument('-n', '--next', help='Next chapter CSS')
        story.add_argument('-d', '--detect-title', default=False,
                           help='CSS selector for chapter title')

        debug.add_argument('-v', dest='verbosity', action='count', default=0,
                           help='Specify verbose output')

        actions.add_argument('--no-download', action='store_true',
                             default=False, help='Do not download ebook')
        actions.add_argument('--no-convert', action='store_true',
                             default=False, help='Do not convert html to mobi')
        actions.add_argument('--no-email', action='store_true',
                             default=False, help='Do not send to kindle')

        args = self.parse_args()

        if not args.url:
            exit('Please specify a URL for the first chapter.')

        return args

    def get_template(self, filename):
        template_dir = os.path.join(os.path.dirname(sys.argv[0]), 'templates')

        def check_files(files=[]):
            for f in files:
                if os.path.isfile(f):
                    return f

            return ''

        files = [filename, os.path.join(template_dir, filename),
                 os.path.join(template_dir, filename + '.yml'),
                 os.path.join(template_dir, filename + '.yaml')]
        template = check_files(files)

        try:
            with open(template, 'r') as f:
                tmp = yaml.full_load(f)
        except Exception as e:
            print(e)
            exit(f'Failed to load template values from {template}.')

        return tmp


if __name__ == '__main__':
    cmdargs = Args()
    s = Story(cmdargs.story)

    if cmdargs.story['verbosity'] > 1:
        print(cmdargs.__dict__)

    if not cmdargs.no_download:
        s.download_ebook()
    if not cmdargs.extras['no_convert']:
        s.convert()
    if not cmdargs.extras['no_email']:
        s.send_ebook(pwfile='.ps')
