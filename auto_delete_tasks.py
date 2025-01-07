import configparser
import requests
import logging

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s', encoding='utf-8')
logger = logging.getLogger(__name__)

# 配置文件路径
CONFIG_FILE = '/config/config.ini'

# 创建ConfigParser对象
config = configparser.ConfigParser()

# 读取配置文件
config.read(CONFIG_FILE, encoding='utf-8')

# 获取download_mgmt部分的信息
download_mgmt = config.getboolean('download_mgmt', 'download_mgmt')
internal_download_mgmt_url = config.get('download_mgmt', 'download_mgmt_url')

# 用于存储传输会话ID
session_id = ''

# 后端URL
backend_url = f'{internal_download_mgmt_url}/transmission/rpc'

def get_torrents():
    global session_id
    try:
        headers = {
            'Content-Type': 'application/json',
            'X-Transmission-Session-Id': session_id
        }
        payload = {
            'method': 'torrent-get',
            'arguments': {
                'fields': ['id', 'name', 'percentDone', 'status', 'rateDownload', 'rateUpload', 'magnetLink']
            }
        }
        response = requests.post(backend_url, headers=headers, json=payload)

        if 'X-Transmission-Session-Id' in response.headers:
            session_id = response.headers['X-Transmission-Session-Id']

        if response.status_code == 409:
            # 如果是409错误，重新尝试
            logger.debug('收到409错误，重新尝试获取任务列表')
            return get_torrents()

        response.raise_for_status()

        data = response.json()
        torrents = data['arguments']['torrents']
        
        if not torrents:
            logger.info('任务列表为空')
        else:
            delete_stopped_torrents(torrents)
    except requests.exceptions.RequestException as e:
        logger.error(f'获取任务列表失败: {e}')

def delete_stopped_torrents(torrents):
    global session_id
    for torrent in torrents:
        if torrent['status'] == 0:  # 0 表示停止状态
            try:
                headers = {
                    'Content-Type': 'application/json',
                    'X-Transmission-Session-Id': session_id
                }
                payload = {
                    'method': 'torrent-remove',
                    'arguments': {
                        'ids': [torrent['id']],
                        'delete-local-data': True
                    }
                }
                response = requests.post(backend_url, headers=headers, json=payload)

                if 'X-Transmission-Session-Id' in response.headers:
                    session_id = response.headers['X-Transmission-Session-Id']

                response.raise_for_status()

                logger.info(f'任务 {torrent["name"]} 已删除')
            except requests.exceptions.RequestException as e:
                logger.error(f'删除任务失败: {e}')

# 执行一次任务获取和删除操作
get_torrents()