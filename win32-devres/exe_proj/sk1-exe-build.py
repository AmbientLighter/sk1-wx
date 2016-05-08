import sys

if len(sys.argv) == 1:
	sys.argv += ['py2exe', ]

from distutils.core import setup
import py2exe

from glob import glob
data_files = [("Microsoft.VC90.CRT",
glob(r'C:\Program Files\Microsoft Visual Studio 9.0\VC\redist\x86\Microsoft.VC90.CRT\*.*'))]

setup(
	options={'py2exe': {'bundle_files': 2,
						'compressed': True,
'includes':['base64', 'cgi', 'colorsys', 'copy', 'datetime', 'errno', 'inspect',
'math', 'new', 'numbers', 'os', 'platform', 'shutil', 'StringIO', 'cStringIO',
'struct', 'sys', 'tempfile', 'time', 'traceback', 'types', 'fractions',
'unicodedata', 'urllib2', 'webbrowser', 'xml.sax', 'zipfile', 'zlib', ],
						}},
	windows=[{'script': "src\\sk1.py",
			"icon_resources": [(1, "src\\sk1.ico")]
			}],
	data_files=data_files,
	zipfile=None,
	)