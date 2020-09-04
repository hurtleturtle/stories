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


class StoryHTML():
    def __init__(self, args, verbosity=0):
        self.initial_url = args['url']
        self.debug = verbosity

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
