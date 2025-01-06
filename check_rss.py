import sqlite3
import logging
import json
import configparser
import requests

# 设置日志配置
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s', encoding='utf-8')
logger = logging.getLogger(__name__)

def read_config(config_path):
    """读取配置文件"""
    config = configparser.ConfigParser()
    config.read(config_path, encoding='utf-8')
    return config

def create_miss_movies_table(cursor):
    """创建MISS_MOVIES表（如果不存在）"""
    cursor.execute('''CREATE TABLE IF NOT EXISTS MISS_MOVIES (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        year INTEGER,
        UNIQUE(title, year)
    )''')

def create_miss_tvs_table(cursor):
    """创建MISS_TVS表（如果不存在）"""
    cursor.execute('''CREATE TABLE IF NOT EXISTS MISS_TVS (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        season INTEGER,
        missing_episodes TEXT,
        UNIQUE(title, season)
    )''')

def subscribe_movies(cursor):
    """订阅电影"""
    cursor.execute('SELECT title, year FROM RSS_MOVIES')
    rss_movies = cursor.fetchall()

    for title, year in rss_movies:
        if not cursor.execute('SELECT 1 FROM LIB_MOVIES WHERE title = ? AND year = ?', (title, year)).fetchone():
            cursor.execute('INSERT OR IGNORE INTO MISS_MOVIES (title, year) VALUES (?, ?)', (title, year))
            if cursor.rowcount > 0:
                logger.info(f"影片：{title}（{year}) 已添加订阅！")
                send_notification(f"影片：{title}（{year}) 已添加订阅！")
            else:
                logger.warning(f"影片：{title}（{year}) 已存在于订阅列表中，跳过插入。")
        else:
            logger.info(f"影片：{title}（{year}) 已入库，无需下载订阅！")

def subscribe_tvs(cursor):
    """订阅电视剧"""
    cursor.execute('SELECT title, season, episode, year FROM RSS_TVS')
    rss_tvs = cursor.fetchall()

    for title, season, total_episodes, year in rss_tvs:
        if total_episodes is None:
            logger.warning(f"电视剧：{title} 第{season}季 缺少总集数信息，跳过处理！")
            continue

        total_episodes = int(total_episodes)
        if not cursor.execute('SELECT 1 FROM LIB_TVS WHERE title = ? AND year = ?', (title, year)).fetchone():
            missing_episodes_str = ','.join(map(str, range(1, total_episodes + 1)))
            # 检查是否已经存在于 MISS_TVS 表中
            if not cursor.execute('SELECT 1 FROM MISS_TVS WHERE title = ? AND season = ?', (title, season)).fetchone():
                cursor.execute('INSERT INTO MISS_TVS (title, season, missing_episodes) VALUES (?, ?, ?)', (title, season, missing_episodes_str))
                logger.info(f"电视剧：{title} 第{season}季 已添加订阅！")
                send_notification(f"电视剧：{title} 第{season}季 已添加订阅！")
            else:
                logger.warning(f"电视剧：{title} 第{season}季 已存在于订阅列表中，跳过插入。")
        else:
            existing_episodes_str = cursor.execute('''
                SELECT episodes 
                FROM LIB_TV_SEASONS 
                WHERE tv_id = (SELECT id FROM LIB_TVS WHERE title = ? AND year = ?) AND season = ?
            ''', (title, year, season)).fetchone()

            if existing_episodes_str:
                existing_episodes = set(map(int, existing_episodes_str[0].split(',')))
                total_episodes_set = set(range(1, total_episodes + 1))
                missing_episodes = total_episodes_set - existing_episodes

                if missing_episodes:
                    pass
                else:
                    logger.info(f"电视剧：{title} 第{season}季 已入库，无需下载订阅！")

def update_subscriptions(cursor):
    """检查并更新当前订阅"""
    # 检查并删除已入库的电影
    cursor.execute('SELECT title, year FROM MISS_MOVIES')
    miss_movies = cursor.fetchall()

    for title, year in miss_movies:
        if cursor.execute('SELECT 1 FROM LIB_MOVIES WHERE title = ? AND year = ?', (title, year)).fetchone():
            cursor.execute('DELETE FROM MISS_MOVIES WHERE title = ? AND year = ?', (title, year))
            logger.info(f"影片：{title}（{year}) 已完成订阅！")
            send_notification(f"影片：{title}（{year}) 已完成订阅！")

    # 检查并删除已完整订阅的电视剧
    cursor.execute('SELECT title, season, missing_episodes FROM MISS_TVS')
    miss_tvs = cursor.fetchall()

    for title, season, missing_episodes in miss_tvs:
        existing_episodes_str = cursor.execute('''
            SELECT episodes 
            FROM LIB_TV_SEASONS 
            WHERE tv_id = (SELECT id FROM LIB_TVS WHERE title = ?) AND season = ?
        ''', (title, season)).fetchone()

        if existing_episodes_str:
            existing_episodes = set(map(int, existing_episodes_str[0].split(',')))
            if missing_episodes:
                missing_episodes_set = set(map(int, missing_episodes.split(',')))
            else:
                missing_episodes_set = set()

            total_episodes_set = existing_episodes | missing_episodes_set

            if len(total_episodes_set) == len(existing_episodes):
                cursor.execute('DELETE FROM MISS_TVS WHERE title = ? AND season = ?', (title, season))
                logger.info(f"电视剧：{title} 第{season}季 已完成订阅！")
                send_notification(f"电视剧：{title} 第{season}季 已完成订阅！")
            else:
                new_missing_episodes_str = ','.join(map(str, sorted(total_episodes_set - existing_episodes)))
                if new_missing_episodes_str != missing_episodes:  # 检查是否发生变化
                    cursor.execute('UPDATE MISS_TVS SET missing_episodes = ? WHERE title = ? AND season = ?', (new_missing_episodes_str, title, season))
                    logger.info(f"电视剧：{title} 第{season}季 缺失 {new_missing_episodes_str} 集，已更新订阅！")
                    send_notification(f"电视剧：{title} 第{season}季 缺失 {new_missing_episodes_str} 集，已更新订阅！")
                else:
                    logger.info(f"电视剧：{title} 第{season}季 订阅未发生变化！")

def send_notification(title_text):
    """发送通知"""
    api_key = config.get('notification', 'notification_api_key', fallback="")
    if not api_key:
        logger.error("通知API Key未在配置文件中找到，无法发送通知。")
        return
    api_url = f"https://api.day.app/{api_key}"
    data = {
        "title": "订阅通知",
        "body": title_text  # 使用 title_text 作为 body 内容
    }
    headers = {'Content-Type': 'application/json'}
    response = requests.post(api_url, data=json.dumps(data), headers=headers)
    if response.status_code == 200:
        logger.info("通知发送成功: %s", response.text)
    else:
        logger.error("通知发送失败: %s %s", response.status_code, response.text)

def main():
    # 读取配置文件
    config_path = '/config/config.ini'
    global config
    config = read_config(config_path)
    db_path = config['database']['db_path']

    # 连接到数据库
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    try:
        # 创建MISS_MOVIES表（如果不存在）
        create_miss_movies_table(cursor)

        # 创建MISS_TVS表（如果不存在）
        create_miss_tvs_table(cursor)

        # 订阅电影
        subscribe_movies(cursor)

        # 订阅电视剧
        subscribe_tvs(cursor)

        # 更新订阅
        update_subscriptions(cursor)

        # 提交事务
        conn.commit()
    except sqlite3.Error as e:
        logger.error(f"发生错误：{e}")
        conn.rollback()
    finally:
        # 关闭连接
        conn.close()

if __name__ == "__main__":
    main()