import os
import xml.etree.ElementTree as ET
import configparser
import logging
import requests
import time
import random

# 配置文件路径
CONFIG_FILE = '/config/config.ini'

# 已处理文件列表文件路径
PROCESSED_FILES_FILE = '/config/processed_nfo_files.txt'

# 日志配置
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# 创建配置解析器
config = configparser.ConfigParser()

# 读取配置文件，如果不存在则创建
if not os.path.exists(CONFIG_FILE):
    # 创建配置文件并写入默认值
    config['douban'] = {
        'api_key': '0ac44ae016490db2204ce0a042db2916',
        'cookie': 'your_cookie',
        'rss_url': 'https://www.douban.com/feed/people/user-id/interests'
    }
    config['nfo'] = {
        'exclude_dirs': 'Season,Movie,Music,Unknown',
        'excluded_filenames': 'season.nfo,video1.nfo',
        'excluded_subdir_keywords': 'Season,Music,Unknown,backdrops'
    }
    with open(CONFIG_FILE, 'w') as configfile:
        config.write(configfile)
else:
    # 读取配置文件
    config.read(CONFIG_FILE)

# 从配置文件中读取值
key = config.get('douban', 'api_key')
cookie = config.get('douban', 'cookie')
directory = config.get('mediadir', 'directory')
excluded_filenames = config.get('nfo', 'excluded_filenames').split(',')
excluded_subdir_keywords = config.get('nfo', 'excluded_subdir_keywords').split(',')

class DoubanAPI:
    def __init__(self, key: str, cookie: str) -> None:
        self.host = "https://frodo.douban.com/api/v2"
        self.key = key
        self.cookie = cookie
        self.mobileheaders = {
            "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148 MicroMessenger/8.0.27(0x18001b33) NetType/WIFI Language/zh_CN",
            "Referer": "https://servicewechat.com/wx2f9b06c1de1ccfca/85/page-frame.html",
            "content-type": "application/json",
            "Connection": "keep-alive",
        }
        self.pcheaders = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/105.0.0.0 Safari/537.36 Edg/105.0.1343.27",
            "Referer": "https://movie.douban.com/",
            "Cookie": self.cookie,
            "Connection": "keep-alive",
        }

    def get_douban_id(self, title: str, year: str = None, media_type: str = 'tv') -> list:
        url = f"https://movie.douban.com/j/subject_suggest?q={title}"
        try:
            response = requests.get(url, headers=self.pcheaders)
            response.raise_for_status()  # 检查请求是否成功
            data = response.json()

            if data and isinstance(data, list):
                if len(data) == 1:  # 如果请求返回只有一个结果，直接使用这个结果
                    item = data[0]
                    logger.info("请求返回只有一个结果，直接使用")
                    return [item.get('id')] if item else []

                # 初步筛选：根据 media_type 和 episode 字段
                matches = []
                for item in data:
                    if media_type == 'movie' and not item.get('episode'):
                        matches.append(item)
                    elif media_type == 'tv' and item.get('episode'):
                        matches.append(item)

                if len(matches) == 1:
                    # 如果只有一个匹配项，直接使用这个结果
                    logger.info("找到一个匹配项")
                    return [matches[0].get('id')]
                elif len(matches) > 1:
                    # 如果有多个匹配项，选择标题相同或匹配度最高的结果，并且需要匹配年份
                    best_match = None
                    highest_match_score = 0
                    for match in matches:
                        match_score = self.calculate_match_score(title, match.get('title', ''))
                        if match.get('year') == year and match_score > highest_match_score:
                            highest_match_score = match_score
                            best_match = match
                    if best_match:
                        logger.info("找到一个最佳匹配项")
                        return [best_match.get('id')]
                    else:
                        logger.warning(f"未找到标题为 {title} 且年份为 {year} 的最佳匹配项")
                else:
                    logger.warning(f"未找到标题为 {title} 的匹配项")
            else:
                logger.warning(f"未找到标题为 {title} 的结果")
        except Exception as e:
            logger.error(f"获取豆瓣 ID 失败，标题: {title}，错误: {e}")
        return []

    def calculate_match_score(self, title1: str, title2: str) -> int:
        # 简单的匹配度计算，可以根据需要进行更复杂的实现
        return sum(title1.lower() in part for part in title2.lower().split())

    def imdb_get_douban_id(self, imdb_id: str) -> str:
        url = f"https://movie.douban.com/j/subject_suggest?q={imdb_id}"
        try:
            response = requests.get(url, headers=self.pcheaders)
            response.raise_for_status()  # 检查请求是否成功
            data = response.json()
            if data and isinstance(data, list) and len(data) > 0:
                # 直接提取第一个结果的豆瓣 ID
                douban_id = data[0].get('id')
                if douban_id:
                    logger.info(f"找到 IMDb ID 为 {imdb_id} 的豆瓣 ID: {douban_id}")
                    return douban_id
                else:
                    logger.warning(f"未找到 IMDb ID 为 {imdb_id} 的豆瓣 ID")
            else:
                logger.warning(f"未找到 IMDb ID 为 {imdb_id} 的结果")
        except Exception as e:
            logger.error(f"通过 IMDb ID 获取豆瓣 ID 失败，IMDb ID: {imdb_id}，错误: {e}")
        return None

    def get_celebrities(self, douban_id: str, media_type: str) -> dict:
        if media_type == 'movie':
            url = f"{self.host}/movie/{douban_id}/celebrities?apikey={self.key}"
        elif media_type == 'tv':
            url = f"{self.host}/tv/{douban_id}/celebrities?apikey={self.key}"
        else:
            logger.warning(f"不支持的媒体类型: {media_type}")
            return {}

        try:
            response = requests.get(url, headers=self.mobileheaders)
            response.raise_for_status()  # 检查请求是否成功
            data = response.json()
            if 'directors' in data or 'actors' in data:
                simplified_data = {
                    'directors': [],
                    'actors': []
                }
                
                for key in ['directors', 'actors']:
                    if key in data:
                        simplified_data[key] = [
                            {
                                'name': celeb.get('name', ''),
                                'roles': celeb.get('roles', []),
                                'character': celeb.get('character', ''),
                                'large': celeb.get('avatar', {}).get('large', ''),
                                'latin_name': celeb.get('latin_name', '')
                            }
                            for celeb in data[key]
                        ]
                return simplified_data
            else:
                logger.warning(f"未找到媒体类型为 {media_type} 的豆瓣 ID {douban_id} 的演职人员")
                return {}
        except Exception as e:
            logger.error(f"获取演职人员失败，媒体类型: {media_type}，豆瓣 ID: {douban_id}，错误: {e}")
            return {}
        finally:
            # 随机休眠一段时间，避免频繁请求
            sleep_time = random.uniform(15, 30)  # 随机休眠15到30秒
            logger.info(f"获取演职人员完成，随机休眠 {sleep_time:.2f} 秒")
            time.sleep(sleep_time)

def read_nfo_file(file_path):
    # 尝试打开并解析nfo文件
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 判断是电影还是电视剧
        media_type = None
        if root.tag == 'movie':
            logger.info(f"这是电影 nfo 文件: {file_path}")
            media_type = 'movie'
        elif root.tag == 'tvshow':
            logger.info(f"这是电视剧 nfo 文件: {file_path}")
            media_type = 'tv'
        else:
            logger.warning(f"未知文件类型: {file_path}")
            return None, None, None, None
        
        # 查找并获取标题和年份
        title = None
        year = None
        for element in root.findall('.//title'):
            title = element.text
            break  # 只需要第一个匹配到的标题
        for element in root.findall('.//year'):
            year = element.text
            break  # 只需要第一个匹配到的年份
        
        # 查找并获取 IMDb ID
        imdb_id = None
        for element in root.findall('.//uniqueid[@type="imdb"]'):
            imdb_id = element.text
            break  # 只需要第一个匹配到的 IMDb ID
        
        if title:
            logger.info(f"标题: {title}, 年份: {year}, IMDb ID: {imdb_id}")
            return media_type, title, year, imdb_id
        else:
            logger.warning(f"未找到文件 {file_path} 中的标题")
            return None, None, None, None
    except Exception as e:
        logger.error(f"读取 nfo 文件 {file_path} 时出错: {e}")
        return None, None, None, None

def update_nfo_file(file_path, directors, actors):
    # 尝试打开并解析nfo文件
    try:
        tree = ET.parse(file_path)
        root = tree.getroot()
        
        # 更新<director>标签
        director_elements = root.findall('.//director')
        for director_element in director_elements:
            original_name = director_element.text.strip().lower()
            matched_director = next(
                (d for d in directors if d['name'].lower() == original_name or d['latin_name'].lower() == original_name),
                None
            )
            if matched_director:
                director_element.text = matched_director['name']
        
        # 更新<actor>标签
        actor_elements = root.findall('.//actor')
        for actor_element in actor_elements:
            name_element = actor_element.find('name')
            if name_element is not None:
                original_name = name_element.text.strip().lower()
                matched_actor = next(
                    (a for a in actors if a['name'].lower() == original_name or a['latin_name'].lower() == original_name),
                    None
                )
                if matched_actor:
                    # 更新<name>
                    name_element.text = matched_actor['name']
                    # 更新<role>
                    role_element = actor_element.find('role')
                    if role_element is not None:
                        role_element.text = matched_actor['character']
                    else:
                        role_element = ET.SubElement(actor_element, 'role')
                        role_element.text = matched_actor['character']
        
        # 写回修改后的内容
        tree.write(file_path, encoding='utf-8', xml_declaration=True)
        logger.info(f"更新文件: {file_path}")
    except Exception as e:
        logger.error(f"更新 nfo 文件 {file_path} 时出错: {e}")

def load_processed_files():
    """加载已处理的文件列表"""
    processed_files = set()
    if os.path.exists(PROCESSED_FILES_FILE):
        with open(PROCESSED_FILES_FILE, 'r', encoding='utf-8') as f:
            processed_files = set(line.strip() for line in f)
    return processed_files

def save_processed_file(file_path):
    """保存已处理的文件"""
    with open(PROCESSED_FILES_FILE, 'a+', encoding='utf-8') as f:
        f.write(file_path + '\n')

def should_exclude_file(file_path):
    """检查文件是否应被排除"""
    file_name = os.path.basename(file_path)
    if file_name in excluded_filenames:
        logger.debug(f"排除文件: {file_name}")
        return True
    return False

def should_exclude_directory(dir_path):
    """检查目录是否应被排除"""
    for keyword in excluded_subdir_keywords:
        if keyword in dir_path:
            logger.debug(f"排除目录: {dir_path}")
            return True
    return False

def process_nfo_files(directory, douban_api):
    # 加载已处理的文件列表
    processed_files = load_processed_files()
    
    # 遍历指定目录及其所有子目录下的所有.nfo文件
    for root, dirs, files in os.walk(directory):
        # 检查当前目录是否应被排除
        if should_exclude_directory(root):
            continue
        
        for filename in files:
            if filename.endswith('.nfo'):
                file_path = os.path.join(root, filename)
                # 检查文件是否应被排除
                if should_exclude_file(file_path):
                    continue
                
                if file_path in processed_files:
                    #logger.info(f"已处理文件: {file_path}，跳过")
                    continue
                
                logger.info(f"正在处理文件: {file_path}")
                
                # 读取nfo文件信息
                media_type, title, year, imdb_id = read_nfo_file(file_path)
                if media_type is None:
                    # 如果 media_type 为 None，则表示文件类型未知，直接跳过
                    logger.warning(f"未知文件类型: {file_path}，跳过")
                    continue
                
                if title:
                    if media_type == 'movie':
                        douban_ids = douban_api.get_douban_id(title, year, media_type)
                    else:
                        douban_ids = douban_api.get_douban_id(title, media_type=media_type)
                    
                    if not douban_ids and imdb_id:
                        # 随机休眠一段时间，避免频繁请求
                        sleep_time = random.uniform(15, 30)  # 随机休眠15到30秒
                        logger.info(f"随机休眠 {sleep_time:.2f} 秒")
                        time.sleep(sleep_time)
                        logger.info(f"尝试通过 IMDb ID 获取豆瓣 ID，IMDb ID: {imdb_id}")
                        douban_id = douban_api.imdb_get_douban_id(imdb_id)
                        if douban_id:
                            douban_ids = [douban_id]
                    
                    if douban_ids:
                        logger.info(f"提取到的豆瓣 IDs 是: {douban_ids}")
                        all_directors = []
                        all_actors = []
                        for douban_id in douban_ids:
                            celebs_data = douban_api.get_celebrities(douban_id, media_type)
                            all_directors.extend(celebs_data.get('directors', []))
                            all_actors.extend(celebs_data.get('actors', []))
                        
                        if all_directors or all_actors:
                            update_nfo_file(file_path, all_directors, all_actors)
                            save_processed_file(file_path)
                    else:
                        logger.warning(f"未能提取豆瓣 ID 对于文件: {file_path}")
                else:
                    logger.warning(f"未能提取标题 对于文件: {file_path}")

                # 随机休眠一段时间，避免频繁请求
                sleep_time = random.uniform(15, 30)  # 随机休眠15到30秒
                logger.info(f"处理完成，随机休眠 {sleep_time:.2f} 秒")
                time.sleep(sleep_time)

if __name__ == "__main__":
    douban_api = DoubanAPI(key, cookie)
    process_nfo_files(directory, douban_api)