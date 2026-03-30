from setuptools import setup

package_name = 'ptp_time_publisher'

setup(
    name=package_name,
    version='1.0.0',
    packages=[package_name],
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['config/zda_publisher.yaml']),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='eagrumo',
    maintainer_email='eagrumo@todo.todo',
    description='ROS2 package for publishing PTP-synchronized time as NMEA ZDA sentences via UART',
    license='TODO: License declaration',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'zda_publisher_node = ptp_time_publisher.zda_publisher_node:main'
        ],
    },
)
