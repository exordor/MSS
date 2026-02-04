#!/usr/bin/env python3
"""
CharUco Camera Calibration Script (OpenCV 4.7+ version)
Camera intrinsic calibration using CharUco board images
Supports user-specified parameter configuration:
- Board: 9x7
- Dictionary: DICT_7X7_250
- Square length: 0.1m (10cm)
- Marker length: 0.08m (8cm)
- Image preprocessing: contrast enhancement, CLAHE, Gaussian blur
"""

import cv2
import numpy as np
import glob
import os

# ROS2 related imports (optional import, skip if ROS2 is not installed)
try:
    import rclpy
    from rclpy.node import Node
    from rclpy.qos import QoSProfile, ReliabilityPolicy, HistoryPolicy
    from sensor_msgs.msg import Image, CompressedImage
    from cv_bridge import CvBridge
    ROS2_AVAILABLE = True
except ImportError:
    ROS2_AVAILABLE = False
    print("Warning: ROS2 or cv_bridge not installed, ROS2 real-time calibration mode unavailable")

import argparse
import threading
from datetime import datetime

def draw_detected_charuco(image, charuco_corners, charuco_ids, marker_corners, marker_ids):
    """
    Draw detected CharUco markers and corners on image
    """
    output = image.copy()

    # Draw ArUco marker borders (green)
    if marker_corners is not None and marker_ids is not None:
        for corners, marker_id in zip(marker_corners, marker_ids):
            corners = corners.astype(int).reshape(-1, 2)
            cv2.polylines(output, [corners], True, (0, 255, 0), 2)
            center = corners.mean(axis=0).astype(int)
            cv2.putText(output, f"M{marker_id[0]}", tuple(center),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)

    # Draw CharUco corners (red dots)
    if charuco_corners is not None and charuco_ids is not None:
        for corner, corner_id in zip(charuco_corners, charuco_ids):
            pt = tuple(corner[0].astype(int))
            cv2.circle(output, pt, 5, (0, 0, 255), -1)
            cv2.putText(output, f"C{corner_id[0]}",
                       (pt[0] + 5, pt[1] - 5),
                       cv2.FONT_HERSHEY_SIMPLEX, 0.4, (0, 0, 255), 1)

    return output

def preprocess_image(image):
    """
    Preprocess image to improve corner detection
    Reference user-provided preprocessing pipeline
    """
    # Contrast enhancement
    image = cv2.convertScaleAbs(image, alpha=2.0, beta=50)

    # Convert to grayscale
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)

    # Use CLAHE (adaptive histogram equalization) to improve contrast
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    enhanced = clahe.apply(gray)

    # Gaussian blur to reduce noise
    enhanced = cv2.GaussianBlur(enhanced, (5, 5), 0)

    return enhanced

def _build_detector_params(cfg=None):
    """
    Build advanced detection parameters
    Supports more marker detection and fine-tuning
    """
    if cfg is None:
        cfg = {}

    params = cv2.aruco.DetectorParameters()

    # Adaptive threshold window size
    params.adaptiveThreshWinSizeMin = 3
    params.adaptiveThreshWinSizeMax = cfg.get("winMax", 53)
    params.adaptiveThreshWinSizeStep = cfg.get("step", 10)

    # Adaptive threshold constant
    params.adaptiveThreshConstant = cfg.get("tc", 7.0)

    # Minimum perimeter ratio for marker detection
    params.minMarkerPerimeterRate = cfg.get("mp", 0.010)

    # Maximum allowed erroneous bit ratio
    params.maxErroneousBitsInBorderRate = cfg.get("merr", 0.20)

    # Minimum distance to border
    params.minDistanceToBorder = cfg.get("mdb", 3)

    # Polygon approximation accuracy
    params.polygonalApproxAccuracyRate = cfg.get("pa", 0.02)

    # Minimum corner distance ratio
    params.minCornerDistanceRate = 0.03

    # Minimum marker distance ratio
    params.minMarkerDistanceRate = 0.03

    # Marker border bits
    params.markerBorderBits = 1

    # Corner refinement method: subpixel refinement
    params.cornerRefinementMethod = cv2.aruco.CORNER_REFINE_SUBPIX

    # Corner refinement window size
    params.cornerRefinementWinSize = cfg.get("rwin", 9)

    # Corner refinement max iterations
    params.cornerRefinementMaxIterations = max(300, cfg.get("rmax", 300))

    # Corner refinement min accuracy
    params.cornerRefinementMinAccuracy = 1e-4

    return params

def _detect_charuco_with_advanced_params(gray, board, dictionary, cfg=None):
    """
    Detect CharUco markers using advanced parameters
    Can detect more marker points
    """
    if cfg is None:
        cfg = {}

    # Build detector with advanced parameters
    detector_params = _build_detector_params(cfg)
    aruco_detector = cv2.aruco.ArucoDetector(dictionary, detector_params)

    # Detect ArUco markers
    corners, ids, rejected = aruco_detector.detectMarkers(gray)

    if ids is None or len(ids) == 0:
        return None, None, None, None

    # Create CharUco detection parameters
    charuco_params = cv2.aruco.CharucoParameters()
    charuco_params.tryRefineMarkers = True

    # Create CharUco detector and detect
    charuco_detector = cv2.aruco.CharucoDetector(board, charuco_params, detector_params)
    charuco_corners, charuco_ids, marker_corners, marker_ids = charuco_detector.detectBoard(gray)

    return charuco_corners, charuco_ids, marker_corners, marker_ids

def calibrate_camera_charuco(image_dir, output_dir="calibration_results", viz_output_dir="detection_viz"):
    """
    Camera calibration using CharUco board
    """

    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(viz_output_dir, exist_ok=True)

    # CharUco parameters - based on user configuration
    SQUARES_X = 9
    SQUARES_Y = 7
    SQUARE_LENGTH = 0.10
    MARKER_LENGTH = 0.08

    print("╔" + "═"*58 + "╗")
    print("║" + " "*16 + "CharUco Camera Calibration Tool" + " "*18 + "║")
    print("║" + " "*14 + "(OpenCV 4.7+ New API Version)" + " "*20 + "║")
    print("╚" + "═"*58 + "╝")

    print("\n[Configuration]")
    print(f"  • Board size: {SQUARES_X}x{SQUARES_Y}")
    print(f"  • Square length: {SQUARE_LENGTH}m (10cm)")
    print(f"  • Marker length: {MARKER_LENGTH}m (8cm)")
    print(f"  • Marker dictionary: DICT_7X7_250")
    print(f"  • Corner refinement: CORNER_REFINE_SUBPIX")

    # Initialize CharUco detector
    CHARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_7X7_250)
    BOARD = cv2.aruco.CharucoBoard((SQUARES_X, SQUARES_Y), SQUARE_LENGTH, MARKER_LENGTH, CHARUCO_DICT)

    # Configure advanced detection parameters
    detection_config = {
        "winMax": 53,      # Adaptive threshold window max value
        "step": 10,        # Window size step
        "tc": 7.0,         # Threshold constant
        "mp": 0.010,       # Minimum marker perimeter ratio (lower to detect smaller markers)
        "merr": 0.20,      # Maximum erroneous bit ratio
        "mdb": 3,          # Minimum distance to border
        "pa": 0.02,        # Polygon approximation accuracy
        "rwin": 9,         # Corner refinement window size
        "rmax": 300,       # Corner refinement max iterations
    }

    # Get all calibration images (support PNG, JPG, JPEG formats)
    image_files = sorted(glob.glob(os.path.join(image_dir, "*.png")) +
                        glob.glob(os.path.join(image_dir, "*.jpg")) +
                        glob.glob(os.path.join(image_dir, "*.jpeg")))

    if not image_files:
        print(f"\nError: No PNG images found in {image_dir}!")
        return

    print(f"\n[Detecting Images]")
    print(f"  • Found {len(image_files)} calibration images")
    print(f"  • Files: {', '.join([os.path.basename(f) for f in image_files])}")

    # Store all valid corners
    all_charuco_corners = []
    all_charuco_ids = []
    image_size = None

    # Process each image
    print(f"\n[Processing Images]")
    for idx, image_file in enumerate(image_files):
        print(f"  [{idx+1}/{len(image_files)}] {os.path.basename(image_file)}", end="")

        # Read image
        image = cv2.imread(image_file)
        if image is None:
            print(" Failed to read")
            continue

        # Record image size
        if image_size is None:
            image_size = (image.shape[1], image.shape[0])

        # Preprocess image
        gray = preprocess_image(image)

        # Detect CharUco markers using advanced parameters
        charuco_corners, charuco_ids, marker_corners, marker_ids = _detect_charuco_with_advanced_params(
            gray, BOARD, CHARUCO_DICT, detection_config
        )

        if charuco_corners is None or charuco_ids is None:
            print(" No CharUco corners detected")
            continue

        charuco_count = len(charuco_ids)
        if charuco_count < 10:
            print(f" Only {charuco_count} corners detected (need >=10)")
            continue

        marker_count = len(marker_ids) if marker_ids is not None else 0
        print(f" Detected {charuco_count} CharUco corners (from {marker_count} markers)")

        # Draw detection results and save (save as PNG format)
        viz_image = draw_detected_charuco(image, charuco_corners, charuco_ids,
                                         marker_corners, marker_ids)
        base_name = os.path.splitext(os.path.basename(image_file))[0]
        viz_file = os.path.join(viz_output_dir, f"detected_{base_name}.png")
        cv2.imwrite(viz_file, viz_image)

        # Save comparison image (original vs detection result)
        h, w = image.shape[:2]
        comparison = np.hstack([image, viz_image])
        comp_file = os.path.join(viz_output_dir, f"comparison_{os.path.basename(image_file)}")
        cv2.imwrite(comp_file, comparison)

        all_charuco_corners.append(charuco_corners)
        all_charuco_ids.append(charuco_ids)

    # Use reusable calibration logic
    return perform_calibration(
        all_charuco_corners, all_charuco_ids, BOARD, image_size,
        output_dir, viz_output_dir
    )

def save_calibration_yaml(filename, camera_matrix, dist_coeffs, image_size, reprojection_error):
    """Save calibration results to YAML format"""
    with open(filename, 'w', encoding='utf-8') as f:
        f.write("# CharUco Camera Calibration Results\n")
        f.write("# Camera Calibration Results\n\n")
        
        f.write(f"image_width: {image_size[0]}\n")
        f.write(f"image_height: {image_size[1]}\n")
        f.write(f"reprojection_error: {reprojection_error:.6f}\n\n")
        
        f.write("camera_matrix: |\n")
        for row in camera_matrix:
            f.write(f"  [{row[0]:.10f}, {row[1]:.10f}, {row[2]:.10f}]\n")
        
        f.write("\ndistortion_coefficients: |\n")
        for val in dist_coeffs.flatten():
            f.write(f"  {val:.10f}\n")

def verify_calibration(charuco_corners_list, charuco_ids_list, board,
                      camera_matrix, dist_coeffs):
    """Verify calibration results"""
    print(f"\n[Calibration Verification]")

    reprojection_errors = []

    for idx, (charuco_corners, charuco_ids) in enumerate(zip(charuco_corners_list, charuco_ids_list)):
        obj_points, ids = board.matchImagePoints(charuco_corners, charuco_ids)

        if obj_points is None or ids is None:
            continue

        success, rvec, tvec = cv2.solvePnP(
            obj_points, charuco_corners, camera_matrix, dist_coeffs,
            useExtrinsicGuess=False, flags=cv2.SOLVEPNP_ITERATIVE
        )

        if not success:
            continue

        reprojected_points, _ = cv2.projectPoints(
            obj_points, rvec, tvec, camera_matrix, dist_coeffs
        )

        error = np.sqrt(
            np.sum((charuco_corners.reshape(-1, 2) - reprojected_points.reshape(-1, 2)) ** 2, axis=1)
        ).mean()

        reprojection_errors.append(error)
        print(f"  • Image {idx + 1} reprojection error: {error:.4f} px")

    if reprojection_errors:
        mean_error = np.mean(reprojection_errors)
        std_error = np.std(reprojection_errors)
        print(f"\n  • Mean error: {mean_error:.4f} ± {std_error:.4f} px")

        if mean_error < 1.0:
            print("  • Calibration quality: Excellent ★★★★★")
        elif mean_error < 2.0:
            print("  • Calibration quality: Good ★★★★☆")
        else:
            print("  • Calibration quality: Fair ★★★☆☆")

def perform_calibration(all_charuco_corners, all_charuco_ids, board, image_size,
                        output_dir="calibration_results", viz_output_dir="detection_viz"):
    """
    Perform camera calibration (reusable calibration logic)
    """
    if len(all_charuco_corners) < 3:
        print(f"\nError: Too few valid calibration images (need >=3, have {len(all_charuco_corners)})")
        return None, None

    # Create output directories
    os.makedirs(output_dir, exist_ok=True)
    os.makedirs(viz_output_dir, exist_ok=True)

    print(f"\n  • Valid calibration images: {len(all_charuco_corners)} ✓")
    print(f"  • Image resolution: {image_size[0]}x{image_size[1]}")

    # Perform camera calibration
    print(f"\n[Calibration Computation]")
    print(f"  • Performing calibration...", end="", flush=True)

    # Prepare 3D and 2D points for calibration
    objpoints = []  # 3D points
    imgpoints = []  # 2D points

    for charuco_corners, charuco_ids in zip(all_charuco_corners, all_charuco_ids):
        # Get 3D coordinates of CharUco board points
        obj_points, ids = board.matchImagePoints(charuco_corners, charuco_ids)

        if obj_points is not None and ids is not None:
            objpoints.append(obj_points)
            imgpoints.append(charuco_corners)

    if len(objpoints) < 3:
        print(" Failed")
        print("Error: Calibration failed - not enough valid images")
        return None, None

    # Perform camera calibration (using standard 5-parameter distortion model)
    ret, camera_matrix, dist_coeffs, rvecs, tvecs = cv2.calibrateCamera(
        objpoints, imgpoints, image_size,
        None, None,
        flags=0
    )

    if not ret:
        print(" Failed")
        print("Error: Calibration failed!")
        return None, None

    print(" Done")
    print(f"  • Reprojection error: {ret:.6f} pixels")

    # Print calibration results
    print("\n╔" + "═"*58 + "╗")
    print("║" + " "*20 + "[Calibration Results]" + " "*20 + "║")
    print("╚" + "═"*58 + "╝")

    print("\n[Camera Matrix]")
    print(camera_matrix)

    print(f"\n[Focal Length and Optical Center]")
    print(f"  • fx (x focal) = {camera_matrix[0, 0]:.4f}")
    print(f"  • fy (y focal) = {camera_matrix[1, 1]:.4f}")
    print(f"  • cx (x center) = {camera_matrix[0, 2]:.4f}")
    print(f"  • cy (y center) = {camera_matrix[1, 2]:.4f}")

    print(f"\n[Distortion Coefficients]")
    dist_flat = dist_coeffs.flatten()
    print(f"  • k1 (radial 1) = {dist_flat[0]:.8f}")
    print(f"  • k2 (radial 2) = {dist_flat[1]:.8f}")
    print(f"  • p1 (tangential 1) = {dist_flat[2]:.8f}")
    print(f"  • p2 (tangential 2) = {dist_flat[3]:.8f}")
    if len(dist_flat) >= 5:
        print(f"  • k3 (radial 3) = {dist_flat[4]:.8f}")

    # Save results
    print(f"\n[Saving Results]")

    # NPZ format
    output_npz = os.path.join(output_dir, "camera_calibration.npz")
    np.savez(
        output_npz,
        camera_matrix=camera_matrix,
        dist_coeffs=dist_coeffs,
        rvecs=rvecs,
        tvecs=tvecs,
        image_size=image_size,
        reprojection_error=ret
    )
    print(f"  • NPZ format: {output_npz}")

    # YAML format
    output_yaml = os.path.join(output_dir, "camera_calibration.yaml")
    save_calibration_yaml(output_yaml, camera_matrix, dist_coeffs, image_size, ret)
    print(f"  • YAML format: {output_yaml}")

    # Run verification
    verify_calibration(all_charuco_corners, all_charuco_ids, board,
                      camera_matrix, dist_coeffs)

    return camera_matrix, dist_coeffs

class CharucoCalibrationNode(Node):
    """
    ROS2 CharUco camera calibration node
    Supports real-time image subscription and interactive calibration
    """

    def __init__(self, image_topic, use_compressed=True,
                 output_dir="calibration_results",
                 viz_output_dir="detection_viz"):
        super().__init__('charuco_calibration_node')

        # Parameters
        self.use_compressed = use_compressed
        self.output_dir = output_dir
        self.viz_output_dir = viz_output_dir

        # CharUco parameters
        self.SQUARES_X = 9
        self.SQUARES_Y = 7
        self.SQUARE_LENGTH = 0.10
        self.MARKER_LENGTH = 0.08

        # Initialize CharUco detector
        self.CHARUCO_DICT = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_7X7_250)
        self.BOARD = cv2.aruco.CharucoBoard(
            (self.SQUARES_X, self.SQUARES_Y),
            self.SQUARE_LENGTH,
            self.MARKER_LENGTH,
            self.CHARUCO_DICT
        )

        # Detection configuration
        self.detection_config = {
            "winMax": 53,
            "step": 10,
            "tc": 7.0,
            "mp": 0.010,
            "merr": 0.20,
            "mdb": 3,
            "pa": 0.02,
            "rwin": 9,
            "rmax": 300,
        }

        # Store captured data
        self.all_charuco_corners = []
        self.all_charuco_ids = []
        self.all_images = []  # Store original images for visualization
        self.image_size = None

        # CvBridge
        self.bridge = CvBridge()

        # QoS configuration
        qos = QoSProfile(
            reliability=ReliabilityPolicy.BEST_EFFORT,
            history=HistoryPolicy.KEEP_LAST,
            depth=10
        )

        # Subscribe to image
        if self.use_compressed:
            self.image_sub = self.create_subscription(
                CompressedImage,
                image_topic,
                self.compressed_callback,
                qos
            )
            self.get_logger().info(f"Subscribed to compressed image: {image_topic}")
        else:
            self.image_sub = self.create_subscription(
                Image,
                image_topic,
                self.raw_callback,
                qos
            )
            self.get_logger().info(f"Subscribed to raw image: {image_topic}")

        # Minimum valid image count
        self.min_images = 3

        # Calibration status
        self.calibration_done = False
        self.calibration_result = None

        # Display window control
        self.display_window = True
        self.current_image = None
        self.current_viz = None
        self.detection_info = ""

        # Print configuration info
        print("\n╔" + "═"*58 + "╗")
        print("║" + " "*16 + "CharUco Camera Calibration Tool" + " "*14 + "║")
        print("║" + " "*10 + "ROS2 Real-time Calibration Mode" + " "*16 + "║")
        print("╚" + "═"*58 + "╝")

        print("\n[Configuration]")
        print(f"  • Board size: {self.SQUARES_X}x{self.SQUARES_Y}")
        print(f"  • Square length: {self.SQUARE_LENGTH}m (10cm)")
        print(f"  • Marker length: {self.MARKER_LENGTH}m (8cm)")
        print(f"  • Marker dictionary: DICT_7X7_250")
        print(f"  • Image topic: {image_topic}")
        print(f"  • Use compressed image: {self.use_compressed}")
        print(f"  • Minimum image count: {self.min_images}")

        print("\n[Instructions]")
        print("  • [SPACE] - Capture current image (need >=10 corners detected)")
        print("  • [c]     - Run camera calibration (need >=3 valid images)")
        print("  • [s]     - Save current detection result")
        print("  • [q]     - Quit program")
        print("\n[Status Information]")
        
    def compressed_callback(self, msg):
        """Handle compressed image"""
        if self.calibration_done:
            return

        try:
            np_arr = np.frombuffer(msg.data, np.uint8)
            image = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
            if image is not None:
                self.process_image(image)
        except Exception as e:
            self.get_logger().error(f"Failed to process compressed image: {e}")

    def raw_callback(self, msg):
        """Handle raw image"""
        if self.calibration_done:
            return

        try:
            image = self.bridge.imgmsg_to_cv2(msg, desired_encoding='bgr8')
            self.process_image(image)
        except Exception as e:
            self.get_logger().error(f"Failed to process raw image: {e}")

    def process_image(self, image):
        """Process image and display detection results"""
        self.current_image = image.copy()

        # Record image size
        if self.image_size is None:
            self.image_size = (image.shape[1], image.shape[0])

        # Preprocess
        gray = preprocess_image(image)

        # Detect CharUco
        charuco_corners, charuco_ids, marker_corners, marker_ids = \
            _detect_charuco_with_advanced_params(gray, self.BOARD,
                                                  self.CHARUCO_DICT,
                                                  self.detection_config)

        # Draw detection results
        self.current_viz = draw_detected_charuco(image, charuco_corners,
                                                 charuco_ids,
                                                 marker_corners,
                                                  marker_ids)

        # Update detection info
        if charuco_corners is not None and charuco_ids is not None:
            charuco_count = len(charuco_ids)
            marker_count = len(marker_ids) if marker_ids is not None else 0

            if charuco_count >= 10:
                self.detection_info = f"Detected {charuco_count} corners (from {marker_count} markers) - [SPACE] capture"
                color = (0, 255, 0)  # Green
            else:
                self.detection_info = f"Only {charuco_count} corners detected (need >=10)"
                color = (0, 165, 255)  # Orange
        else:
            self.detection_info = "No CharUco markers detected"
            color = (0, 0, 255)  # Red

        # Draw status info on image
        self._draw_status_info(self.current_viz, color)

        # Display image
        if self.display_window:
            cv2.imshow('CharUco Calibration', self.current_viz)

            # Handle keyboard input
            key = cv2.waitKey(1) & 0xFF
            self._handle_key_input(key, charuco_corners, charuco_ids)

    def _draw_status_info(self, image, color):
        """Draw status information on image"""
        h, w = image.shape[:2]

        # Semi-transparent background
        overlay = image.copy()
        cv2.rectangle(overlay, (0, 0), (w, 180), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, image, 0.4, 0, image)

        # Text info
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 0.6
        font_color = (255, 255, 255)
        line_height = 30
        y = 30

        cv2.putText(image, f\"Captured: {len(self.all_charuco_corners)} / {self.min_images}+\",
                   (10, y), font, font_scale, font_color, 2)
        y += line_height

        cv2.putText(image, self.detection_info,
                   (10, y), font, font_scale, color, 2)
        y += line_height

        cv2.putText(image, \"[SPACE] Capture [c] Calibrate [s] Save [q] Quit\",
                   (10, y), font, font_scale, font_color, 1)
        y += line_height

        cv2.putText(image, f\"Resolution: {self.image_size[0]}x{self.image_size[1]}\",
                   (10, y), font, font_scale, font_color, 1)

    def _handle_key_input(self, key, charuco_corners, charuco_ids):
        """Handle keyboard input"""
        if key == ord(' '):  # SPACE key - capture image
            self._capture_image(charuco_corners, charuco_ids)
        elif key == ord('c') or key == ord('C'):  # C key - run calibration
            self._run_calibration()
        elif key == ord('s') or key == ord('S'):  # S key - save detection result
            self._save_current_detection()
        elif key == ord('q') or key == ord('Q') or key == 27:  # Q key or ESC - quit
            self._shutdown()

    def _capture_image(self, charuco_corners, charuco_ids):
        """Capture image"""
        if charuco_corners is None or charuco_ids is None:
            print("  Cannot capture: No CharUco corners detected")
            return

        charuco_count = len(charuco_ids)
        if charuco_count < 10:
            print(f"  Cannot capture: Only {charuco_count} corners detected (need >=10)")
            return

        # Save data
        self.all_charuco_corners.append(charuco_corners.copy())
        self.all_charuco_ids.append(charuco_ids.copy())
        self.all_images.append(self.current_image.copy())

        print(f"  Captured image {len(self.all_charuco_corners)} ({charuco_count} corners)")

        # Save detection visualization
        os.makedirs(self.viz_output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        viz_file = os.path.join(self.viz_output_dir, f"captured_{timestamp}.png")
        cv2.imwrite(viz_file, self.current_viz)

    def _run_calibration(self):
        """Run calibration"""
        if len(self.all_charuco_corners) < self.min_images:
            print(f"\nError: Not enough images (need >= {self.min_images}, have {len(self.all_charuco_corners)})")
            return

        print("\n" + "="*60)
        print("Starting camera calibration...")
        print("="*60)

        # Run calibration
        camera_matrix, dist_coeffs = perform_calibration(
            self.all_charuco_corners,
            self.all_charuco_ids,
            self.BOARD,
            self.image_size,
            self.output_dir,
            self.viz_output_dir
        )

        if camera_matrix is not None and dist_coeffs is not None:
            self.calibration_done = True
            self.calibration_result = (camera_matrix, dist_coeffs)

            print("\n" + "="*60)
            print("Calibration complete!")
            print("="*60)

            # Wait for user to confirm quit
            print("\nPress any key to quit...")
            cv2.waitKey(0)
            self._shutdown()

    def _save_current_detection(self):
        """Save current detection result"""
        if self.current_viz is None:
            print("  No detection result to save")
            return

        os.makedirs(self.viz_output_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        viz_file = os.path.join(self.viz_output_dir, f"saved_{timestamp}.png")
        cv2.imwrite(viz_file, self.current_viz)
        print(f"  Saved to: {viz_file}")

    def _shutdown(self):
        """Shutdown node"""
        self.display_window = False
        cv2.destroyAllWindows()
        print("\nExiting...")
        self.destroy_node()
        rclpy.shutdown()
        import sys
        sys.exit(0)

def run_ros_calibration(image_topic="/image_raw/compressed", use_compressed=True,
                       output_dir="calibration_results", viz_output_dir="detection_viz"):
    """
    Run ROS2 real-time calibration
    """
    if not ROS2_AVAILABLE:
        print("\nError: ROS2 environment not configured, real-time calibration mode unavailable")
        print("Please install ROS2 and cv_bridge packages:")
        print("  sudo apt install ros-humble-cv-bridge ros-humble-sensor-msgs")
        return None, None

    # Initialize ROS2
    rclpy.init()

    # Create calibration node
    node = CharucoCalibrationNode(image_topic, use_compressed, output_dir, viz_output_dir)

    # Spin node
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        node.destroy_node()
        rclpy.shutdown()

    return node.calibration_result if node.calibration_done else (None, None)

if __name__ == "__main__":
    import sys

    # Parse command line arguments
    parser = argparse.ArgumentParser(
        description='CharUco Camera Calibration Tool',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Usage examples:
  # ROS2 real-time calibration mode (uses compressed images by default)
  python calib.py --ros

  # ROS2 real-time calibration mode (uses raw images)
  python calib.py --ros --topic /image_raw --no-compressed

  # Directory calibration mode
  python calib.py --dir /path/to/calibration/images

  # Custom output directories
  python calib.py --ros --output my_results --viz my_viz
"""
    )

    # Mode selection (mutually exclusive)
    mode_group = parser.add_mutually_exclusive_group(required=True)
    mode_group.add_argument('--ros', action='store_true',
                           help='Use ROS2 real-time calibration mode')
    mode_group.add_argument('--dir', type=str, metavar='DIRECTORY',
                           help='Calibrate from images in specified directory')

    # ROS2 related parameters
    parser.add_argument('--topic', type=str, default='/image_raw/compressed',
                       help='Image topic name (default: /image_raw/compressed)')
    parser.add_argument('--no-compressed', action='store_true',
                       help='Do not use compressed images, subscribe to raw image topic')

    # Output parameters
    parser.add_argument('--output', type=str, default='calibration_results',
                       help='Calibration result output directory (default: calibration_results)')
    parser.add_argument('--viz', type=str, default='detection_viz',
                       help='Detection result visualization output directory (default: detection_viz)')

    args = parser.parse_args()

    print("\n" + "="*60)
    print("CharUco Camera Calibration Tool")
    print("="*60)

    if args.ros:
        # ROS2 real-time calibration mode
        print("\nMode: ROS2 Real-time Calibration")
        use_compressed = not args.no_compressed

        if use_compressed:
            image_topic = args.topic if 'compressed' in args.topic else args.topic + '/compressed'
            print(f"  • Image topic: {image_topic} (compressed)")
        else:
            image_topic = args.topic
            print(f"  • Image topic: {image_topic} (raw)")

        print(f"  • Output directory: {args.output}")
        print(f"  • Visualization directory: {args.viz}")

        run_ros_calibration(
            image_topic=image_topic,
            use_compressed=use_compressed,
            output_dir=args.output,
            viz_output_dir=args.viz
        )

    elif args.dir:
        # Directory calibration mode
        print("\nMode: Directory Calibration")
        image_directory = args.dir

        if not os.path.exists(image_directory):
            print(f"\nError: Directory {image_directory} does not exist!")
            sys.exit(1)

        print(f"  • Image directory: {image_directory}")
        print(f"  • Output directory: {args.output}")
        print(f"  • Visualization directory: {args.viz}")

        calibrate_camera_charuco(
            image_directory,
            output_dir=args.output,
            viz_output_dir=args.viz
        )

    print("\n" + "="*60)
    print("Calibration complete!")
    print("="*60)