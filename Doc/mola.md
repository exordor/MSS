# SLAM without tf

command:
MOLA_LIDAR_TOPIC=/navi_lidar/points MOLA_IMU_TOPIC=/imu/data MOLA_GENERATE_SIMPLEMAP=true MOLA_SIMPLEMAP_OUTPUT=myMap.simplemap MOLA_SIMPLEMAP_GENERATE_LAZY_LOAD=true MOLA_USE_FIXED_LIDAR_POSE=true  mola-lo-gui-rosbag2 /home/eagrumo/mss_lecture/temp/rosbag2_20260105_165702

command with imu:
MOLA_LIDAR_TOPIC=/navi_lidar/points \
MOLA_IMU_TOPIC=/imu/data \
MOLA_GENERATE_SIMPLEMAP=true \
MOLA_SIMPLEMAP_OUTPUT=myMap_imu.simplemap \
MOLA_SIMPLEMAP_GENERATE_LAZY_LOAD=true \
MOLA_USE_FIXED_LIDAR_POSE=true \
MOLA_USE_FIXED_IMU_POSE=true \
mola-lo-gui-rosbag2 /rosbagpath

# check file

sm-cli info ./myMap.simplemap

# convert to mm

sm2mm -i ./myMap.simplemap -o myMap.mm --externals-dir ./myMap_Images

# view mm

mm-viewer ./myMap.mm

# ply
mm2ply -i myMap.mm -o myMap.ply

# export twist in map
sm-cli export-keyframes myMap.simplemap --output traj.tum --output-twist twist.txt