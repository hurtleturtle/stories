from setuptools import setup, find_packages


setup(
    name='story-scraper',
    version='0.1.1',
    description='Scrape stories from websites and send them to kindle',
    author='Jono Nicholas',
    packages=find_packages(),
    install_requires=[
        'bs4',
        'lxml',
        'pyyaml',
        'requests',
        'flask',
        'flask-wtf'
    ]
)