#!/usr/bin/env python3
"""
ROS2 Logging Configuration Loader
Load logging configuration from YAML file and export as environment variables
"""
import sys
import os


def load_logging_config(config_file, profile=None, export_format=True):
    """
    Load logging configuration from YAML file

    Args:
        config_file: Path to YAML configuration file
        profile: Profile name to use
        export_format: Whether to output in bash export format
    """
    try:
        import yaml
    except ImportError:
        print("# Error: PyYAML not installed. Run: pip install pyyaml", file=sys.stderr)
        print("# Using default values", file=sys.stderr)
        return get_default_exports() if export_format else get_default_config()

    if not os.path.exists(config_file):
        print(f"# Warning: Config file not found: {config_file}", file=sys.stderr)
        print("# Using default values", file=sys.stderr)
        return get_default_exports() if export_format else get_default_config()

    try:
        with open(config_file, 'r') as f:
            data = yaml.safe_load(f)
    except Exception as e:
        print(f"# Error loading config: {e}", file=sys.stderr)
        return get_default_exports() if export_format else get_default_config()

    # Get default profile
    if not profile:
        profile = data.get('default_profile', 'dev')

    profiles = data.get('profiles', {})

    # If specified profile not found, fall back to dev or first available
    if profile not in profiles:
        print(f"# Warning: Profile '{profile}' not found, using 'dev'", file=sys.stderr)
        profile = 'dev' if 'dev' in profiles else next(iter(profiles.keys()), 'dev')

    config = profiles.get(profile, {})

    if export_format:
        return format_exports(profile, config)
    else:
        return format_config_dict(profile, config, config_file)


def get_default_exports():
    """Return default configuration in export format"""
    return [
        "export LOGGING_ACTIVE_PROFILE='default'",
        "export RCUTILS_LOGGING_USE_STDOUT='1'",
        "export RCUTILS_COLORIZED_OUTPUT='0'",
        "export RCUTILS_CONSOLE_OUTPUT_FORMAT='[{time}] [{severity}] [{name}] {message}'",
        "export RCUTILS_LOGGING_BUFFERED_STREAM='0'",
        "export RCUTILS_LOG_LEVEL='info'",
        "export PYTHONUNBUFFERED='1'",
    ]


def get_default_config():
    """Return default configuration in dictionary format"""
    return {
        'profile': 'default',
        'rcutils': {
            'use_stdout': 1,
            'colorized_output': 0,
            'console_output_format': '[{time}] [{severity}] [{name}] {message}',
            'buffered_stream': 0,
            'log_level': 'info',
        },
        'python': {
            'unbuffered': 1,
            'verbose': 0,
        }
    }


def format_exports(profile, config):
    """Format as bash export statements"""
    rcutils = config.get('rcutils', {})
    python = config.get('python', {})

    exports = [
        f"export LOGGING_ACTIVE_PROFILE='{profile}'",
        f"export RCUTILS_LOGGING_USE_STDOUT='{rcutils.get('use_stdout', 1)}'",
        f"export RCUTILS_COLORIZED_OUTPUT='{rcutils.get('colorized_output', 0)}'",
        f"export RCUTILS_CONSOLE_OUTPUT_FORMAT='{rcutils.get('console_output_format', '[{time}] [{severity}] [{name}] {message}')}'",
        f"export RCUTILS_LOGGING_BUFFERED_STREAM='{rcutils.get('buffered_stream', 0)}'",
        f"export RCUTILS_LOG_LEVEL='{rcutils.get('log_level', 'info')}'",
        f"export PYTHONUNBUFFERED='{python.get('unbuffered', 1)}'",
    ]
    return exports


def format_config_dict(profile, config, config_file):
    """Format as configuration dictionary"""
    rcutils = config.get('rcutils', {})
    python = config.get('python', {})

    return {
        'profile': profile,
        'config_file': config_file,
        'rcutils': {
            'use_stdout': rcutils.get('use_stdout', 1),
            'colorized_output': rcutils.get('colorized_output', 0),
            'console_output_format': rcutils.get('console_output_format', '[{time}] [{severity}] [{name}] {message}'),
            'buffered_stream': rcutils.get('buffered_stream', 0),
            'log_level': rcutils.get('log_level', 'info'),
        },
        'python': {
            'unbuffered': python.get('unbuffered', 1),
            'verbose': python.get('verbose', 0),
        }
    }


def main():
    """CLI entry point"""
    if len(sys.argv) < 2:
        print("Usage: load_logging_config.py <config_file> [profile]", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print("  LOG_PROFILE - override profile", file=sys.stderr)
        print("  LOGGING_CONFIG - override config file", file=sys.stderr)
        sys.exit(1)

    # Get config file path (supports environment variable override)
    config_file = os.getenv('LOGGING_CONFIG', sys.argv[1])

    # Get profile (priority: CLI argument > environment variable > YAML default)
    profile = None
    if len(sys.argv) > 2:
        profile = sys.argv[2]
    elif 'LOG_PROFILE' in os.environ:
        profile = os.environ['LOG_PROFILE']

    # Load and output configuration
    exports = load_logging_config(config_file, profile, export_format=True)
    for line in exports:
        print(line)


if __name__ == '__main__':
    main()
