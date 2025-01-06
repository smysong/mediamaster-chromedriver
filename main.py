import os
import subprocess
import time
import logging
import sys
import configparser
import signal

# 配置日志
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s', encoding='utf-8')

# 创建默认配置文件
def create_default_config():
    default_config = """
[database]
db_path = /config/data.db

[notification]
notification_api_key = your_bark_key

[nfo]
exclude_dirs = Season,Movie,Music,Unknown,backdrops
excluded_filenames = season.nfo,video1.nfo
excluded_subdir_keywords = Season,Music,Unknown,backdrops

[mediadir]
directory = /Your_media_path
movies_path = /Media/Your_movie_path
episodes_path = /Media/Your_episodes_path

[downloadtransfer]
directory = /Downloads
action = copy
excluded_filenames = 【更多高清

[douban]
api_key = 0ac44ae016490db2204ce0a042db2916
cookie = your_douban_cookie_here
rss_url = https://www.douban.com/feed/people/user-id/interests

[tmdb]
base_url = https://api.tmdb.org/3
api_key = your_tmdb_key

[emby]
emby_api_key = your_emby_key
emby_refresh_url = http://your_emby_ip:port/Library/Refresh

[tmm]
tmm_api_key = your_tmm_key
tmm_url = http://your_tmm_ip:7878/api/

[download_mgmt]
download_mgmt = False
download_mgmt_url = http://your_transmission_url:port

[resources]
login_username = username
login_password = password
preferred_resolution = 2160p
fallback_resolution = 1080p
exclude_keywords = 60帧,高码版

[urls]
movie_login_url = https://100.tudoutudou.top/member.php?mod=logging&action=login
tv_login_url = https://200.tudoutudou.top/member.php?mod=logging&action=login
movie_search_url = https://100.tudoutudou.top/search.php?mod=forum
tv_search_url = https://200.tudoutudou.top/search.php?mod=forum

[running]
run_interval_hours = 6
"""
    config_path = '/config/config.ini'
    try:
        with open(config_path, 'w', encoding='utf-8') as config_file:
            config_file.write(default_config)
        logging.info(f"配置文件 '{config_path}' 已创建，请修改默认配置并重启程序。")
    except IOError as e:
        logging.error(f"无法创建配置文件: {e}")
        sys.exit(1)

def load_config(config_path='/config/config.ini'):
    config = configparser.ConfigParser()
    try:
        config.read(config_path, encoding='utf-8')
        return config
    except (IOError, configparser.Error) as e:
        logging.error(f"无法加载配置文件: {e}")
        sys.exit(1)

def check_config(config, section, required_keys):
    if not all(key in config[section] for key in required_keys):
        logging.error(f"配置文件缺少必要的键值，请检查并确保所有必需的设置都已提供。缺失的键值在 [{section}] 部分。")
        sys.exit(1)

def run_script(script_name):
    try:
        result = subprocess.run(['python', script_name], check=True)
        logging.debug(f"{script_name} 已执行完毕。")
    except subprocess.CalledProcessError as e:
        logging.error(f"{script_name} 执行失败，退出程序。错误信息: {e}")
        sys.exit(1)

def start_app():
    try:
        with open(os.devnull, 'w') as devnull:
            process = subprocess.Popen(['python', 'app.py'], stdout=devnull, stderr=devnull)
            logging.info("WEB管理已启动。")
            return process.pid
    except Exception as e:
        logging.error(f"无法启动WEB管理程序: {e}")
        sys.exit(1)

def start_sync():
    try:
        process = subprocess.Popen(['python', 'sync.py'])
        logging.info("目录监控服务已启动。")
        return process.pid
    except Exception as e:
        logging.error(f"无法启动目录监控服务: {e}")
        sys.exit(1)

# 全局变量，用于控制主循环
running = True
app_pid = None
sync_pid = None

# 定义信号处理器函数
def shutdown_handler(signum, frame):
    global running, app_pid, sync_pid
    logging.info(f"收到信号 {signum}，正在关闭程序...")

    # 停止主循环
    running = False

    # 终止子进程
    if app_pid:
        logging.info(f"终止 app.py 进程 (PID: {app_pid})")
        try:
            os.kill(app_pid, signal.SIGTERM)
        except ProcessLookupError:
            logging.warning(f"进程 {app_pid} 不存在，跳过终止操作。")

    if sync_pid:
        logging.info(f"终止 sync.py 进程 (PID: {sync_pid})")
        try:
            os.kill(sync_pid, signal.SIGTERM)
        except ProcessLookupError:
            logging.warning(f"进程 {sync_pid} 不存在，跳过终止操作。")

    # 等待子进程优雅地关闭
    time.sleep(5)  # 可以根据实际情况调整等待时间

    logging.info("程序已关闭。")
    sys.exit(0)

# 注册信号处理器
signal.signal(signal.SIGTERM, shutdown_handler)
signal.signal(signal.SIGINT, shutdown_handler)

def main():
    global app_pid, sync_pid, running
    config_path = '/config/config.ini'
    if not os.path.exists(config_path):
        create_default_config()
    
    config = load_config(config_path)
    
    required_keys_douban = ["api_key", "cookie", "rss_url"]
    required_keys_running = ["run_interval_hours"]
    
    check_config(config, 'douban', required_keys_douban)
    check_config(config, 'running', required_keys_running)

    run_interval_hours = int(config.get('running', 'run_interval_hours', fallback=6))  # 默认每6小时运行一次
    run_interval_seconds = run_interval_hours * 3600

    # 检查用户名和密码是否为默认值或空值
    should_run_downloaders = (config.get('resources', 'login_username', fallback='') != 'username' and
                              config.get('resources', 'login_password', fallback='') != 'password')

    # 检查 RSS URL 是否为默认值或空值
    should_run_rss = config.get('douban', 'rss_url', fallback='') != 'https://www.douban.com/feed/people/user-id/interests'

    # 检查 TMDB API Key 是否为默认值或空值
    should_run_sync = config.get('tmdb', 'api_key', fallback='') != 'your_tmdb_key'

    # 检查 media directory 是否为默认值或空值
    should_run_media_scripts = (config.get('mediadir', 'directory', fallback='') != '/Your_media_path' and
                                config.get('mediadir', 'movies_path', fallback='') != '/Media/Your_movie_path' and
                                config.get('mediadir', 'episodes_path', fallback='') != '/Media/Your_episodes_path')

    # 启动 app.py
    app_pid = start_app()
    # 根据条件启动 sync.py
    if should_run_sync:
        sync_pid = start_sync()

    while running:
        if should_run_media_scripts:
            run_script('scan_media.py')
            logging.info("-" * 80)
            logging.info("扫描媒体库，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

            run_script('tmdb_id.py')
            logging.info("-" * 80)
            logging.info("更新数据库TMDB_ID，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

        if should_run_rss:
            run_script('rss.py')
            logging.info("-" * 80)
            logging.info("获取最新豆瓣订阅，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

            run_script('check_rss.py')
            logging.info("-" * 80)
            logging.info("检查是否有新增订阅，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

        if should_run_downloaders:
            run_script('tvshow_downloader.py')
            logging.info("-" * 80)
            logging.info("电视剧检索下载，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

            run_script('movie_downloader.py')
            logging.info("-" * 80)
            logging.info("电影检索下载，已执行完毕，等待10秒...")
            logging.info("-" * 80)
            time.sleep(10)

        if should_run_media_scripts:
            run_script('actor_nfo.py')
            logging.info("-" * 80)
            logging.info("更新电视剧演职人员中文信息，已执行完毕。")
            logging.info("-" * 80)

            run_script('episodes_nfo.py')
            logging.info("-" * 80)
            logging.info("更新每集演职人员中文信息，已执行完毕。")
            logging.info("-" * 80)

        logging.info(f"所有任务已完成，等待 {run_interval_hours} 小时后再次运行...")
        time.sleep(run_interval_seconds)

if __name__ == "__main__":
    main()