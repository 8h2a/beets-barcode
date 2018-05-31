from setuptools import setup

setup(
    name='beets-barcode',
    version='0.0.1',
    description='beets plugin to support barcodes and catalogue numbers',
    long_description=open('README.md').read(),
    author='8h2a',
    author_email='0x000000000000002a@gmail.com',
    url='https://github.com/8h2a/beets-barcode',
    license='MIT',
    platforms='ALL',

    packages=['beetsplug'],

    install_requires=[
        'beets>=1.4.7',
        'pyzbar>=0.1.7',
        'Pillow>=3.4.2',
    ],
)
