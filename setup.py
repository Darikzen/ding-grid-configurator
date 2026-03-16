from setuptools import setup, find_packages

setup(
    name='ding-grid-configurator',
    version='1.0.0',
    description='GTK4 GUI for customising the DING desktop icon grid',
    author='darikzen',
    author_email='darikzen@gmail.com',
    url='https://github.com/darikzen/ding-grid-configurator',
    license='MIT',
    packages=find_packages(),
    package_data={
        'ding_grid_configurator': ['pkexec_helper.sh'],
    },
    python_requires='>=3.12',
    entry_points={
        'console_scripts': [
            'ding-grid-configurator=ding_grid_configurator.main:main',
        ],
    },
    classifiers=[
        'License :: OSI Approved :: MIT License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python :: 3',
        'Environment :: X11 Applications :: GTK',
        'Topic :: Desktop Environment :: Gnome',
    ],
)
