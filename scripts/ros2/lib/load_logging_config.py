#!/usr/bin/env python3
"""
ROS2 日志配置加载器
从 YAML 文件加载日志配置并导出为环境变量
"""
import sys
import os


def load_logging_config(config_file, profile=None, export_format=True):
    """
    从 YAML 文件加载日志配置

    Args:
        config_file: YAML 配置文件路径
        profile: 要使用的 profile 名称
        export_format: 是否输出 bash export 格式
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

    # 获取默认 profile
    if not profile:
        profile = data.get('default_profile', 'dev')

    profiles = data.get('profiles', {})

    # 如果指定的 profile 不存在，使用 dev 或第一个可用的
    if profile not in profiles:
        print(f"# Warning: Profile '{profile}' not found, using 'dev'", file=sys.stderr)
        profile = 'dev' if 'dev' in profiles else next(iter(profiles.keys()), 'dev')

    config = profiles.get(profile, {})

    if export_format:
        return format_exports(profile, config)
    else:
        return format_config_dict(profile, config, config_file)


def get_default_exports():
    """返回默认配置的 export 格式"""
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
    """返回默认配置的字典格式"""
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
    """格式化为 bash export 语句"""
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
    """格式化为配置字典"""
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
    """命令行入口"""
    if len(sys.argv) < 2:
        print("Usage: load_logging_config.py <config_file> [profile]", file=sys.stderr)
        print("Environment variables:", file=sys.stderr)
        print("  LOG_PROFILE - override profile", file=sys.stderr)
        print("  LOGGING_CONFIG - override config file", file=sys.stderr)
        sys.exit(1)

    # 获取配置文件路径（支持环境变量覆盖）
    config_file = os.getenv('LOGGING_CONFIG', sys.argv[1])

    # 获取 profile（优先级：命令行参数 > 环境变量 > YAML 中默认值）
    profile = None
    if len(sys.argv) > 2:
        profile = sys.argv[2]
    elif 'LOG_PROFILE' in os.environ:
        profile = os.environ['LOG_PROFILE']

    # 加载并输出配置
    exports = load_logging_config(config_file, profile, export_format=True)
    for line in exports:
        print(line)


if __name__ == '__main__':
    main()
