import configparser

CONFIG_FILE = '/config/config.ini'

def read_config():
    """读取配置文件"""
    config = configparser.ConfigParser()
    config.read(CONFIG_FILE)
    return {s: dict(config.items(s)) for s in config.sections()}

def write_config(data):
    """写入配置文件"""
    config = configparser.ConfigParser()
    for section, options in data.items():
        if not config.has_section(section):
            config.add_section(section)
        for key, values in options.items():
            if isinstance(values, list):
                value = ','.join(values)  # 将列表转换为字符串，用逗号分隔
            else:
                value = values
            config.set(section, key, value)
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)