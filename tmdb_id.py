import os
import re
import sqlite3
import xml.etree.ElementTree as ET
import logging
import configparser
import requests

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s', encoding='utf-8')

def read_config(config_file):
    """从配置文件中读取信息"""
    logging.debug(f"读取配置文件: {config_file}")
    config = configparser.ConfigParser()
    config.read(config_file)
    return config

def parse_nfo(file_path):
    """解析NFO文件，返回title, year和tmdb id"""
    logging.debug(f"解析NFO文件: {file_path}")
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 查找<title>元素
        title_element = root.find('title')
        title = title_element.text.strip().lower() if title_element is not None else None
        
        # 查找<year>元素
        year_element = root.find('year')
        year = year_element.text.strip() if year_element is not None else None
        
        # 查找<uniqueid type="tmdb">元素
        tmdb_id_element = root.find(".//uniqueid[@type='tmdb']")
        tmdb_id = tmdb_id_element.text.strip() if tmdb_id_element is not None else None
        
        logging.debug(f"解析结果: 标题: {title}, 年份: {year}, tmdb_id: {tmdb_id}")
        return title, year, tmdb_id
    except Exception as e:
        logging.error(f"解析 {file_path} 时出错: {e}")
        return None, None, None

def find_and_parse_nfo_files(directory, title, year):
    """在给定目录中查找所有NFO文件并解析它们，返回匹配的tmdb_id"""
    logging.info(f"在目录 {directory} 中查找所有NFO文件，标题: {title}, 年份: {year}")
    title = title.lower().strip()
    year = str(year).strip()  # 确保 year 是字符串类型
    for root, dirs, files in os.walk(directory):
        for file in files:
            if file.endswith('.nfo'):
                file_path = os.path.join(root, file)
                parsed_title, parsed_year, tmdb_id = parse_nfo(file_path)
                if parsed_title == title and parsed_year == year:
                    logging.info(f"找到匹配的NFO文件: {file_path}, tmdb_id: {tmdb_id}")
                    return tmdb_id
                else:
                    logging.debug(f"不匹配的NFO文件: {file_path}, 解析标题: {parsed_title}, 解析年份: {parsed_year}")
    logging.info(f"未找到匹配的NFO文件，标题: {title}, 年份: {year}")
    return None

def query_tmdb_api(title, year, media_type, config):
    """通过TMDB API查询获取tmdb_id"""
    TMDB_API_KEY = config['tmdb']['api_key']
    TMDB_BASE_URL = config['tmdb']['base_url']
    url = f"{TMDB_BASE_URL}/search/{media_type}"
    params = {
        'api_key': TMDB_API_KEY,
        'query': title,
        'language': 'zh-CN',
        'include_adult': 'false'
    }
    logging.info(f"通过TMDB API查询 {title} 获取tmdb_id")
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        search_results = response.json().get('results', [])
        for result in search_results:
            if media_type == 'movie':
                release_date = result.get('release_date', '')
                if release_date and release_date.startswith(str(year)):
                    logging.info(f"找到匹配的电影, tmdb_id: {result.get('id')}")
                    return result.get('id')
            elif media_type == 'tv':
                first_air_date = result.get('first_air_date', '')
                if first_air_date and first_air_date.startswith(str(year)):
                    logging.info(f"找到匹配的电视剧, tmdb_id: {result.get('id')}")
                    return result.get('id')
    except Exception as e:
        logging.error(f"查询TMDB API时出错: {e}")
    logging.info(f"未找到匹配的tmdb_id, 标题: {title}, 年份: {year}")
    return None

def update_database(db_path, table, title, year, tmdb_id):
    """更新数据库中的tmdb_id字段"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    
    # 检查是否存在tmdb_id字段，如果不存在则创建
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [column[1] for column in cursor.fetchall()]
    if 'tmdb_id' not in columns:
        cursor.execute(f"ALTER TABLE {table} ADD COLUMN tmdb_id TEXT")
        logging.info(f"在表 {table} 中添加了 tmdb_id 字段")
    
    # 查询是否存在相同的title和year
    cursor.execute(f"SELECT tmdb_id FROM {table} WHERE title = ? AND year = ?", (title, year))
    row = cursor.fetchone()
    
    if row:
        existing_tmdb_id = row[0]
        if existing_tmdb_id:
            logging.debug(f"跳过处理：标题 '{title}'，年份 '{year}' 和 tmdb_id '{existing_tmdb_id}'")
            return
        
        # 更新tmdb_id字段
        cursor.execute(f"UPDATE {table} SET tmdb_id = ? WHERE title = ? AND year = ?", (tmdb_id, title, year))
        conn.commit()
        logging.info(f"更新数据库记录：标题: {title}, 年份: {year}, tmdb_id: {tmdb_id}")
    else:
        logging.info(f"在表 {table} 中未找到标题 '{title}' 和年份 '{year}'")
    
    conn.close()

def fetch_data_without_tmdb_id(db_path, table):
    """从数据库中获取没有tmdb_id的数据"""
    logging.debug(f"从数据库 {db_path} 获取没有tmdb_id的数据, 表: {table}")
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()
    cursor.execute(f"SELECT title, year FROM {table} WHERE tmdb_id IS NULL OR tmdb_id = ''")
    rows = cursor.fetchall()
    conn.close()
    logging.debug(f"获取到 {len(rows)} 条没有tmdb_id的数据")
    return rows

def main():
    # 从配置文件中读取路径信息
    config = read_config('/config/config.ini')
    db_path = config['database']['db_path']
    movies_path = config['mediadir']['movies_path']
    episodes_path = config['mediadir']['episodes_path']

    # 获取数据库中没有tmdb_id的电影记录
    movies_without_tmdb_id = fetch_data_without_tmdb_id(db_path, 'LIB_MOVIES')

    # 获取数据库中没有tmdb_id的电视剧记录
    episodes_without_tmdb_id = fetch_data_without_tmdb_id(db_path, 'LIB_TVS')

    # 处理电影记录
    for title, year in movies_without_tmdb_id:
        logging.info(f"处理电影记录, 标题: {title}, 年份: {year}")
        # 尝试从NFO文件中读取tmdb_id
        tmdb_id = find_and_parse_nfo_files(movies_path, title, year)
        if not tmdb_id:
            # 调用TMDB API获取tmdb_id
            tmdb_id = query_tmdb_api(title, year, 'movie', config)
        update_database(db_path, 'LIB_MOVIES', title, year, tmdb_id)

    # 处理电视剧记录
    for title, year in episodes_without_tmdb_id:
        logging.info(f"处理电视剧记录, 标题: {title}, 年份: {year}")
        # 尝试从NFO文件中读取tmdb_id
        tmdb_id = find_and_parse_nfo_files(episodes_path, title, year)
        if not tmdb_id:
            # 调用TMDB API获取tmdb_id
            tmdb_id = query_tmdb_api(title, year, 'tv', config)
        update_database(db_path, 'LIB_TVS', title, year, tmdb_id)

if __name__ == "__main__":
    main()