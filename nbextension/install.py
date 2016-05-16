from notebook.nbextensions import validate_nbextension, enable_nbextension, install_nbextension
import sys
import os

install_nbextension(os.path.dirname(os.path.abspath(__file__)) + '/imathics', user=True)
enable_nbextension(section='notebook', require='imathics/imathics')
validate_nbextension('imathics')

