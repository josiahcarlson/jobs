#!/usr/bin/env python

from distutils.core import setup

try:
    long_description = open('README.rst').read()
except IOError:
    long_description = ''

try:
    version = open('VERSION').read()
except:
    version = '??'

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
        'Programming Language :: Python :: 3.3',
        'Programming Language :: Python :: 3.4',
        'Programming Language :: Python :: 3.5',
    ],
    license='GNU LGPL v2.1',
    long_description=long_description,
    requires=['redis'],
)
