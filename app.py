import sqlite3
import subprocess
import threading
from flask import Flask, g, render_template, request, redirect, url_for, jsonify, session, flash, session, send_from_directory, Response
from werkzeug.security import check_password_hash, generate_password_hash
from functools import wraps
from werkzeug.exceptions import InternalServerError
from manual_search import MediaDownloader  # 导入 MediaDownloader 类
from datetime import timedelta
from werkzeug.middleware.proxy_fix import ProxyFix
import os
import time
import settings
import configparser
import requests

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1, x_prefix=1)
# 定义版本号
APP_VERSION = '1.7.7 (20250214)'
downloader = MediaDownloader()
app.secret_key = 'mediamaster'  # 设置一个密钥，用于会话管理
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=24)  # 设置会话有效期为24小时
app.config['SESSION_COOKIE_NAME'] = 'mediamaster'  # 设置会话 cookie 名称为 mediamaster
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'  # 设置会话 cookie 的 SameSite 属性
DATABASE = '/config/data.db'

# 存储进程ID的字典
running_services = {}

def get_db():
    db = getattr(g, '_database', None)
    if db is None:
        db = g._database = sqlite3.connect(DATABASE)
        db.row_factory = sqlite3.Row
    return db

@app.teardown_appcontext
def close_connection(exception):
    db = getattr(g, '_database', None)
    if db is not None:
        db.close()

def init_db():
    with app.app_context():
        db = get_db()
        db.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL
            )
        ''')
        
        # 插入默认管理员账户
        default_username = 'admin'
        default_password = 'P@ssw0rd'
        hashed_password = generate_password_hash(default_password)
        
        # 检查是否已经存在管理员账户
        existing_admin = db.execute('SELECT id FROM users WHERE username = ?', (default_username,)).fetchone()
        if not existing_admin:
            db.execute('INSERT INTO users (username, password) VALUES (?, ?)', (default_username, hashed_password))
        
        db.commit()

def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

@app.route('/login', methods=('GET', 'POST'))
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        db = get_db()
        error = None
        user = db.execute(
            'SELECT * FROM users WHERE username = ?', (username,)
        ).fetchone()

        if user is None:
            error = '用户名或密码错误！'
        elif not check_password_hash(user['password'], password):
            error = '用户名或密码错误！'

        if error is None:
            session.permanent = True  # 设置会话为永久
            session.clear()
            session['user_id'] = user['id']
            # 手动设置会话有效期
            session['_permanent'] = True
            session.modified = True
            # 返回登录成功的响应
            response = jsonify(success=True, message='登录成功。', redirect_url=url_for('index'))
            return response

        return jsonify(success=False, message=error)

    return render_template('login.html', version=APP_VERSION)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if 'user_id' not in session:
        return jsonify(success=False, message='请先登录。', redirect_url=url_for('login'))

    user_id = session['user_id']

    if request.method == 'POST':
        old_password = request.form['old_password']
        new_password = request.form['new_password']
        
        # 获取数据库连接
        db = get_db()
        
        # 查询用户是否存在
        user = db.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
        
        if user and check_password_hash(user['password'], old_password):
            # 密码验证成功，更新密码
            new_hashed_password = generate_password_hash(new_password)
            db.execute('UPDATE users SET password = ? WHERE id = ?', (new_hashed_password, user_id))
            db.commit()
            
            return jsonify(success=True, message='您的密码已成功更新。', redirect_url=url_for('index'))
        else:
            return jsonify(success=False, message='旧密码错误。', redirect_url=url_for('change_password'))
    
    return render_template('change_password.html', version=APP_VERSION)

@app.errorhandler(InternalServerError)
def handle_500(error):
    app.logger.error(f"服务器错误: {error}")
    return render_template('500.html'), 500

@app.route('/')
@login_required
def index():
    try:
        db = get_db()
        page = int(request.args.get('page', 1))
        per_page = 24
        offset = (page - 1) * per_page
        media_type = request.args.get('type', 'movies')

        # 获取电影或电视剧的总数
        total_movies = db.execute('SELECT COUNT(*) FROM LIB_MOVIES').fetchone()[0]
        total_tvs = db.execute('SELECT COUNT(DISTINCT id) FROM LIB_TVS').fetchone()[0]

        if media_type == 'movies':
            movies = db.execute('SELECT id, title, year, tmdb_id FROM LIB_MOVIES ORDER BY year DESC LIMIT ? OFFSET ?', (per_page, offset)).fetchall()
            tv_data = []
        elif media_type == 'tvs':
            movies = []
            # 查询电视剧基本信息
            tv_ids = db.execute('SELECT id FROM LIB_TVS ORDER BY year DESC LIMIT ? OFFSET ?', (per_page, offset)).fetchall()
            tv_ids = [tv['id'] for tv in tv_ids]

            # 获取这些电视剧的所有季信息
            tv_seasons = db.execute('''
                SELECT t1.id, t1.title, t2.season, t2.episodes, t1.year, t1.tmdb_id
                FROM LIB_TVS AS t1 
                JOIN LIB_TV_SEASONS AS t2 ON t1.id = t2.tv_id 
                WHERE t1.id IN ({})
                ORDER BY t1.year DESC, t1.id, t2.season 
            '''.format(','.join(['?'] * len(tv_ids))), tv_ids).fetchall()

            # 将相同电视剧的季信息合并，并计算总集数
            tv_data = {}
            for tv in tv_seasons:
                if tv['id'] not in tv_data:
                    tv_data[tv['id']] = {
                        'id': tv['id'],
                        'title': tv['title'],
                        'year': tv['year'],
                        'tmdb_id': tv['tmdb_id'],
                        'seasons': [],
                        'total_episodes': 0
                    }
                
                # 解析 episodes 字符串，计算总集数
                episodes_list = tv['episodes'].split(',')
                num_episodes = len(episodes_list)

                tv_data[tv['id']]['seasons'].append({
                    'season': tv['season'],
                    'episodes': num_episodes  # 季的集数
                })
                tv_data[tv['id']]['total_episodes'] += num_episodes  # 累加总集数
            tv_data = list(tv_data.values())
        else:
            movies = []
            tv_data = []

        return render_template('index.html', 
                               movies=movies, 
                               tv_data=tv_data, 
                               page=page, 
                               per_page=per_page, 
                               total_movies=total_movies, 
                               total_tvs=total_tvs, 
                               media_type=media_type, 
                               version=APP_VERSION)
    except Exception as e:
        app.logger.error(f"发生错误: {e}")
        raise InternalServerError("发生意外错误，请稍后再试。")

@app.route('/subscriptions')
@login_required
def subscriptions():
    db = get_db()
    miss_movies = db.execute('SELECT * FROM MISS_MOVIES').fetchall()
    miss_tvs = db.execute('SELECT * FROM MISS_TVS').fetchall()
    return render_template('subscriptions.html', miss_movies=miss_movies, miss_tvs=miss_tvs, version=APP_VERSION)

@app.route('/douban_subscriptions')
@login_required
def douban_subscriptions():
    db = get_db()
    rss_movies = db.execute('SELECT * FROM RSS_MOVIES').fetchall()
    rss_tvs = db.execute('SELECT * FROM RSS_TVS').fetchall()
    return render_template('douban_subscriptions.html', rss_movies=rss_movies, rss_tvs=rss_tvs, version=APP_VERSION)

@app.route('/search', methods=['GET'])
@login_required
def search():
    db = get_db()
    query = request.args.get('q', '').strip()
    results = []

    if query:
        # 查询电影并按年份排序
        movies = db.execute('SELECT * FROM LIB_MOVIES WHERE title LIKE ? ORDER BY year ASC', ('%' + query + '%',)).fetchall()
        
        # 查询电视剧并获取其季信息
        tvs = db.execute('SELECT * FROM LIB_TVS WHERE title LIKE ? ORDER BY title ASC', ('%' + query + '%',)).fetchall()

        # 合并结果
        for movie in movies:
            results.append({
                'type': 'movie',
                'id': movie['id'],
                'title': movie['title'],
                'year': movie['year']
            })

        for tv in tvs:
            # 获取该电视剧的所有季信息，并按季数排序
            seasons = db.execute('SELECT season, episodes FROM LIB_TV_SEASONS WHERE tv_id = ? ORDER BY season ASC', (tv['id'],)).fetchall()
            tv_data = {
                'type': 'tv',
                'id': tv['id'],
                'title': tv['title'],
                'seasons': seasons
            }
            results.append(tv_data)

    return render_template('search_results.html', query=query, results=results, version=APP_VERSION)

@app.route('/edit_subscription/<type>/<int:id>', methods=['GET', 'POST'])
@login_required
def edit_subscription(type, id):
    db = get_db()
    if type == 'movie':
        subscription = db.execute('SELECT * FROM MISS_MOVIES WHERE id = ?', (id,)).fetchone()
    elif type == 'tv':
        subscription = db.execute('SELECT * FROM MISS_TVS WHERE id = ?', (id,)).fetchone()
    else:
        return "Invalid subscription type", 400

    if request.method == 'POST':
        title = request.form['title']
        year = request.form['year'] if type == 'movie' else None
        season = request.form['season'] if type == 'tv' else None
        missing_episodes = request.form['missing_episodes'] if type == 'tv' else None

        if type == 'movie':
            db.execute('UPDATE MISS_MOVIES SET title = ?, year = ? WHERE id = ?', (title, year, id))
        elif type == 'tv':
            db.execute('UPDATE MISS_TVS SET title = ?, season = ?, missing_episodes = ? WHERE id = ?', (title, season, missing_episodes, id))
        db.commit()
        return redirect(url_for('subscriptions'))

    return render_template('edit_subscription.html', subscription=subscription, type=type, version=APP_VERSION)

@app.route('/delete_subscription/<type>/<int:id>', methods=['POST'])
@login_required
def delete_subscription(type, id):
    db = get_db()
    if type == 'movie':
        db.execute('DELETE FROM MISS_MOVIES WHERE id = ?', (id,))
    elif type == 'tv':
        db.execute('DELETE FROM MISS_TVS WHERE id = ?', (id,))
    else:
        return "Invalid subscription type", 400
    db.commit()
    return redirect(url_for('subscriptions'))

@app.route('/service_control')
@login_required
def service_control():
    return render_template('service_control.html', version=APP_VERSION)

def run_script_and_cleanup(process, log_file_path):
    process.wait()  # 等待子进程完成
    if os.path.exists(log_file_path):
        os.remove(log_file_path)  # 删除日志文件

@app.route('/run_service', methods=['POST'])
@login_required
def run_service():
    data = request.get_json()
    service = data.get('service')
    try:
        log_file_path = f'/tmp/{service}.log'
        with open(log_file_path, 'w', encoding='utf-8') as log_file:
            process = subprocess.Popen(['python3', f'/app/{service}.py'], stdout=log_file, stderr=log_file)
            pid = process.pid
            running_services[service] = pid
            
            # 启动后台线程处理日志文件
            threading.Thread(target=run_script_and_cleanup, args=(process, log_file_path)).start()
            
        return jsonify({"message": "服务运行成功！", "pid": pid}), 200
    except Exception as e:
        return jsonify({"message": str(e)}), 500

@app.route('/realtime_log/<string:service>')
@login_required
def realtime_log(service):
    def generate():
        log_file_path = f'/tmp/{service}.log'
        if not os.path.exists(log_file_path):
            yield 'data: 当前没有实时运行日志，请检查服务是否正在运行！\n\n'.encode('utf-8')
            return
        
        with open(log_file_path, 'r', encoding='utf-8') as log_file:
            while True:
                line = log_file.readline()
                if not line:
                    time.sleep(0.1)  # 避免CPU占用过高
                    continue
                yield f'data: {line}\n\n'
    
    return Response(generate(), mimetype='text/event-stream', content_type='text/event-stream; charset=utf-8')

# 新增手动搜索和下载接口
@app.route('/manual_search')
@login_required
def manual_search():
    return render_template('manual_search.html', version=APP_VERSION)

@app.route('/api/search_movie', methods=['POST'])
@login_required
def api_search_movie():
    data = request.json
    keyword = data.get('keyword')
    year = data.get('year')
    if not keyword:
        return jsonify({'error': '缺少关键词'}), 400

    results = downloader.search_movie(keyword, year)
    return jsonify(results)

@app.route('/api/search_tv_show', methods=['POST'])
@login_required
def api_search_tv_show():
    data = request.json
    keyword = data.get('keyword')
    year = data.get('year')
    if not keyword:
        return jsonify({'error': '缺少关键词'}), 400

    results = downloader.search_tv_show(keyword, year)
    return jsonify(results)

@app.route('/api/download_movie', methods=['GET'])
@login_required
def api_download_movie():
    link = request.args.get('link')
    title = request.args.get('title')
    year = request.args.get('year')
    if not link or not title or not year:
        return jsonify({'error': '缺少参数'}), 400

    success = downloader.download_movie(link, title, year)
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False}), 400
    
@app.route('/api/download_tv_show', methods=['GET'])
@login_required
def api_download_tv_show():
    link = request.args.get('link')
    title = request.args.get('title')
    year = request.args.get('year')
    if not link or not title or not year:
        return jsonify({'error': '缺少参数'}), 400

    success = downloader.download_tv_show(link, title, year)
    if success:
        return jsonify({'success': True})
    else:
        return jsonify({'success': False}), 400

# 配置节的中文标题
section_titles = {
    'database': '数据库设置',
    'notification': '通知设置',
    'nfo': '演职人员汉化设置',
    'mediadir': '媒体目录设置',
    'downloadtransfer': '下载转移设置',
    'douban': '豆瓣设置',
    'tmdb': 'TMDB设置',
    'emby': 'Emby设置',
    'tmm': 'TMM设置',
    'download_mgmt': '下载管理设置',
    'resources': '资源站点设置',
    'urls': '站点URL设置',
    'running': '程序运行设置'
}

# 配置项描述字典
config_descriptions = {
    'database': {
        'db_path': '数据库路径',
    },
    'notification': {
        'notification_api_key': '通知API密钥',
    },
    'nfo': {
        'exclude_dirs': '排除的目录',
        'excluded_filenames': '排除的文件名',
        'excluded_subdir_keywords': '排除的子目录关键字',
    },
    'mediadir': {
        'directory': '媒体根目录',
        'movies_path': '电影库目录',
        'episodes_path': '剧集库目录',
    },
    'downloadtransfer': {
        'directory': '下载监听目录',
        'action': '动作（复制或移动）',
        'excluded_filenames': '排除的文件名',
    },
    'douban': {
        'api_key': '豆瓣API密钥',
        'cookie': '豆瓣Cookie',
        'rss_url': '豆瓣订阅URL',
    },
    'tmdb': {
        'base_url': 'TMDB API接口',
        'api_key': 'TMDB API密钥',
    },
    'emby': {
        'emby_api_key': 'Emby API密钥',
        'emby_refresh_url': 'Emby 扫描接口',
    },
    'tmm': {
        'tmm_api_key': 'TMM API密钥',
        'tmm_url': 'TMM API接口',
    },
    'download_mgmt': {
        'download_mgmt': '是否启用下载管理',
        'download_mgmt_url': '下载器URL',
    },
    'resources': {
        'login_username': '登录用户名',
        'login_password': '登录密码',
        'preferred_resolution': '首选分辨率',
        'fallback_resolution': '备用分辨率',
        'exclude_keywords': '排除的关键字',
    },
    'urls': {
        'movie_login_url': '电影登录URL',
        'tv_login_url': '电视剧登录URL',
        'movie_search_url': '电影搜索URL',
        'tv_search_url': '电视剧搜索URL',
    },
    'running': {
        'run_interval_hours': '运行间隔（小时）',
    }
}

@app.route('/settings')
@login_required
def settings_page():
    # 从配置文件读取数据并传递给模板
    config_data = settings.read_config()
    return render_template('settings.html', config=config_data, descriptions=config_descriptions, section_titles=section_titles, version=APP_VERSION)

@app.route('/save_set', methods=['POST'])
@login_required
def save_settings():
    try:
        # 获取表单数据并保存到配置文件
        form_data = request.form.to_dict(flat=False)  # 使用 flat=False 处理多值字段
        new_config = {}

        # 将表单数据转换为配置文件所需的格式
        for key, value in form_data.items():
            section, option = key.split('[', 1)
            option = option.rstrip(']')
            if section not in new_config:
                new_config[section] = {}
            new_config[section][option] = value[0] if len(value) == 1 else value

        settings.write_config(new_config)
        flash('配置保存成功！', 'success')
    except Exception as e:
        flash(f'保存配置时发生错误：{str(e)}', 'danger')
    return redirect(url_for('settings_page'))

# 配置文件路径
CONFIG_FILE = '/config/config.ini'

# 创建ConfigParser对象
config = configparser.ConfigParser()

# 读取配置文件
config.read(CONFIG_FILE)

# 获取download_mgmt部分的信息
download_mgmt = config.getboolean('download_mgmt', 'download_mgmt')
internal_download_mgmt_url = config.get('download_mgmt', 'download_mgmt_url')

# 定义一个函数来生成代理URL
def get_proxy_url():
    # 获取当前请求的协议
    scheme = request.scheme
    # 假设代理服务器将 /proxy/download_mgmt 开头的请求转发到内部网络
    default_path = ''  # 默认路径为空字符串
    proxy_base_url = url_for('proxy_download_mgmt', path=default_path, _external=True, _scheme=scheme)
    return proxy_base_url

@app.route('/download_mgmt')
@login_required
def download_mgmt_page():
    # 获取代理后的URL
    download_mgmt_url = get_proxy_url()
    
    # 将信息传递给模板
    return render_template('download_mgmt.html', version=APP_VERSION, download_mgmt=download_mgmt, download_mgmt_url=download_mgmt_url)

@app.route('/proxy/download_mgmt/<path:path>', methods=['GET', 'POST'])
def proxy_download_mgmt(path):
    
    # 获取内部URL
    internal_url = f"{internal_download_mgmt_url}/{path}"
    
    # 转发请求到内部URL
    response = requests.request(
        method=request.method,
        url=internal_url,
        headers={key: value for key, value in request.headers if key != 'Host'},
        data=request.get_data(),
        cookies=request.cookies,
        allow_redirects=False
    )
    
    # 返回响应
    excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
    headers = [(name, value) for (name, value) in response.raw.headers.items() if name.lower() not in excluded_headers]
    return response.content, response.status_code, headers

if __name__ == '__main__':
    init_db()  # 初始化数据库
    app.run(host='0.0.0.0', port=8888, debug=False)