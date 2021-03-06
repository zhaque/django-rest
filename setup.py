#!/usr/bin/env python

from distutils.core import setup

setup(name='django-rest',
      version='0.4',
      description='XML backed models queried from external REST apis',
      author='Chris Tarttelin and Cam McHugh',
      author_email='ctarttelin@point2.com',
      url='http://djangorestmodel.sourceforge.net/',
      packages=['rest_client', 'xml_models', 'xpath'],
     )
