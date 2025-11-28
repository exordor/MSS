from setuptools import setup, find_packages

package_name = 'thruster_control'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=('test', 'tests')),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['pyserial'],
    zip_safe=False,
    author='EAGRUMO',
    maintainer='EAGRUMO',
    description='ROS2 package to control Arduino thruster via serial',
    entry_points={'console_scripts': ['thruster_node = thruster_control.thruster_node:main']},
)
