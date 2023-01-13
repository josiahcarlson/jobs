#!/usr/bin/env python

from setuptools import setup
#from distutils.core import setup

try:
    long_description = open('README.rst').read()
except IOError:
    long_description = ''

try:
    version = open('VERSION').read()
except:
    version= '??'

setup(
    name='jobspy',
    version=version,
    description='Use Redis as a job input/output coordinator.',
    author='Josiah Carlson',
    author_email='josiah.carlson@gmail.com',
    url='https://github.com/josiahcarlson/jobs',
    py_modules=['jobs'],
    classifiers=[
        'Development Status :: 5 - Production/Stable',
        'License :: OSI Approved :: GNU Library or Lesser General Public License (LGPL)',
        'Programming Language :: Python',
        'Topic :: Software Development :: Libraries :: Python Modules',
        'Programming Language :: Python',
        'Programming Language :: Python :: 2.7',
        'Programming Language :: Python :: 3.5',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'Programming Language :: Python :: 3.8',
        'Programming Language :: Python :: 3.9',
        'Programming Language :: Python :: 3.10',
        'Programming Language :: Python :: 3.11',
    ],
    license='GNU LGPL v2.1',
    long_description=long_description,
    install_requires=['redis>=3.0.0'],
)
