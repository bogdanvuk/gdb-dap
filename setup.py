from setuptools import setup, find_packages
import os

this_directory = os.path.abspath(os.path.dirname(__file__))


setup(
    name='gdb-dap',
    version='0.0.1',
    description='PyGears library for interfacing Vivado Xilinx tool',
    url='https://www.pygears.org',
    # download_url = '',
    author='Bogdan Vukobratovic',
    author_email='bogdan.vukobratovic@gmail.com',
    license='MIT',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Topic :: Scientific/Engineering :: Electronic Design Automation (EDA)',
        'License :: OSI Approved :: MIT License',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
    ],
    python_requires='>=3.6.0',
    install_requires=['pygdbmi'],
    setup_requires=['pygdbmi'],
    keywords=
    'PyGears functional hardware design Python simulator HDL ASIC FPGA control systems',
    packages=find_packages(exclude=['docs']),
)
