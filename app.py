import os
import json
import re
from datetime import datetime, timedelta
from collections import defaultdict
from typing import List, Optional, Dict, Any, Tuple
import logging
import atexit

# Flask Web 应用相关导入
from flask import Flask, render_template, url_for, abort, send_from_directory, Response, request, jsonify, redirect
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
import click # 用于 Flask CLI 命令

# 可选: 用于 EXIF 数据 (优先级 3)。需要 'Pillow' 库。
# 如果您想使用 EXIF，请安装: pip install Pillow
# 然后取消下面相关代码的注释。
try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    HAS_PILLOW = True
except ImportError:
    HAS_PILLOW = False

# --- Flask 应用设置 ---
app = Flask(__name__)

# 从 config.py 加载配置
app.config.from_pyfile('config.py')

# --- 日志配置 ---
# 获取 config.py 中定义的日志级别字符串
log_level_str = app.config.get('LOG_LEVEL', 'INFO').upper()
# 将字符串转换为对应的 logging 模块级别常量
log_level = getattr(logging, log_level_str, logging.INFO)

# 配置根记录器
logging.basicConfig(level=log_level,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    handlers=[
                        logging.FileHandler(app.config['LOG_FILE']),
                        logging.StreamHandler()
                    ])

# 将 Flask 应用自身的记录器级别设置为配置值
app.logger.setLevel(log_level)

# 确保 Werkzeug 记录器也遵循配置的级别 (仅在非调试模式下)
if not app.debug:
    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(log_level)


db = SQLAlchemy(app)
migrate = Migrate(app, db) # 初始化 Flask-Migrate

# 将常量添加到 Jinja2 全局变量，以便在所有模板中可用
app.jinja_env.globals['IMAGE_EXTENSIONS'] = ('.jpg', '.jpeg', '.png', '.gif', '.webp')
app.jinja_env.globals['VIDEO_EXTENSIONS'] = ('.mp4',)
app.jinja_env.globals['MEDIA_EXTENSIONS'] = app.jinja_env.globals['IMAGE_EXTENSIONS'] + app.jinja_env.globals['VIDEO_EXTENSIONS']

# --- 用于持久化缓存的数据库模型 ---
class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    
    # 新增或修改的用户元数据字段
    name = db.Column(db.String(120), nullable=True)        # 例如: "__Inty__"
    nick = db.Column(db.String(120), nullable=True)        # 例如: "Inty热点新闻"
    location = db.Column(db.String(120), nullable=True)    # 用户位置
    description = db.Column(db.Text, nullable=True)        # 用户简介
    verified = db.Column(db.Boolean, nullable=True)        # 是否认证
    profile_image_url = db.Column(db.String(255), nullable=True) # 用户头像的 URL (如果 JSON 提供)
    favourites_count = db.Column(db.Integer, nullable=True) # 喜欢的推文数 (原 JSON中是 'favourites_count')
    followers_count = db.Column(db.Integer, nullable=True) # 粉丝数
    friends_count = db.Column(db.Integer, nullable=True)   # 关注数 (Twitter/X 称之为 following)
    listed_count = db.Column(db.Integer, nullable=True)    # 所在列表数
    media_count = db.Column(db.Integer, nullable=True)     # 媒体推文数
    statuses_count = db.Column(db.Integer, nullable=True)  # 推文总数
    
    posts = db.relationship('Post', backref='user', lazy=True, cascade="all, delete-orphan")

    def __repr__(self):
        return f'<用户 {self.username}>'

    # 将 User 对象序列化为字典，用于 JSON 响应或模板渲染
    def to_dict(self):
        return {
            'username': self.username,
            'name': self.name,
            'nick': self.nick,
            'location': self.location,
            'description': self.description,
            'verified': self.verified,
            'profile_image_url': self.profile_image_url,
            'favourites_count': self.favourites_count,
            'followers_count': self.followers_count,
            'friends_count': self.friends_count,
            'listed_count': self.listed_count,
            'media_count': self.media_count,
            'statuses_count': self.statuses_count,
        }


class Post(db.Model):
    id = db.Column(db.String(20), primary_key=True) # 推文 ID (字符串形式)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, nullable=True, index=True) # 时间戳仍用于潜在的未来时间排序和过滤
    text_content = db.Column(db.Text, nullable=True)
    media_files_json = db.Column(db.Text, nullable=True) # 将媒体文件列表存储为 JSON 字符串
    retweet_count = db.Column(db.Integer, nullable=True)
    reply_count = db.Column(db.Integer, nullable=True)
    favorite_count = db.Column(db.Integer, nullable=True)
    bookmark_count = db.Column(db.Integer, nullable=True)
    
    raw_json_data_text = db.Column(db.Text, nullable=True)

    def __repr__(self):
        return f'<推文 {self.id} 来自 {self.user.username}>'

    @property
    def media_files(self) -> List[str]:
        if self.media_files_json:
            try:
                return json.loads(self.media_files_json)
            except json.JSONDecodeError as e:
                app.logger.error(f"解析帖子 {self.id} 的 media_files_json 失败: {e}")
                return []
        return []

    @property
    def raw_json_data(self) -> Optional[Dict[str, Any]]:
        if self.raw_json_data_text:
            try:
                return json.loads(self.raw_json_data_text)
            except json.JSONDecodeError as e:
                app.logger.error(f"解析帖子 {self.id} 的 raw_json_data_text 失败: {e}")
                return None
        return None

    def to_dict(self):
        # 在 Post.to_dict 中也包含 User 的详细信息，以便前端 JS 可以访问
        user_info = self.user.to_dict() if self.user else {}
        return {
            'id': self.id,
            'username': self.user.username,
            'user_info': user_info, # 将完整的用户信息作为嵌套对象传递
            'timestamp': self.timestamp.strftime('%Y-%m-%d %H:%M:%S') if self.timestamp else None,
            'text_content': self.text_content,
            'media_files': self.media_files,
            'retweet_count': self.retweet_count,
            'reply_count': self.reply_count,
            'favorite_count': self.favorite_count,
            'bookmark_count': self.bookmark_count,
        }

# --- 核心数据结构和工具函数 ---

def extract_tweet_id_from_filename(filename: str) -> Optional[str]:
    """
    从文件名中提取推文 ID (假定 ID 是文件名的数字前缀)。
    """
    match = re.match(r'^(\d+)', filename)
    if match:
        return match.group(1)
    return None

def parse_timestamp(
    post_id: str,
    user_folder_path: str,
    files_for_post: List[str]
) -> Optional[datetime]:
    """
    根据优先级从不同来源解析推文的发布时间戳。
    优先级顺序: .json 文件中的 'date' 字段 -> .txt 文件内容的第一行 -> 文件名中的 Unix 时间戳 -> 文件系统修改时间。
    """
    timestamp = None
    
    # 优先级 1: 从 .json 文件 'date' 字段
    json_file_name = next((f for f in files_for_post if f.endswith('.json')), None)
    if json_file_name:
        json_path = os.path.join(user_folder_path, json_file_name)
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                json_data = json.load(f)
                date_str = json_data.get('date')
                if date_str:
                    try:
                        # 假设格式为 "YYYY-MM-DD HH:MM:SS"
                        timestamp = datetime.strptime(date_str, '%Y-%m-%d %H:%M:%S')
                        return timestamp
                    except ValueError:
                        app.logger.debug(f"JSON 文件 '{json_file_name}' 的 'date' 字段 '{date_str}' 对于帖子 {post_id} 不是 YYYY-MM-DD HH:MM:%S 格式。")
                        pass
        except json.JSONDecodeError as e:
            app.logger.warning(f"解析 JSON 文件 '{json_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
        except Exception as e:
            app.logger.warning(f"读取 JSON 文件 '{json_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
            pass

    # 优先级 2:从 .txt 文件内容的第一行
    txt_file = next((f for f in files_for_post if f.endswith('.txt')), None)
    if txt_file:
        txt_path = os.path.join(user_folder_path, txt_file)
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                first_line = f.readline().strip()
                try:
                    timestamp = datetime.strptime(first_line, '%Y-%m-%d %H:%M:%S')
                    return timestamp
                except ValueError:
                    app.logger.debug(f"TXT 文件 '{txt_file}' 第一行 '{first_line}' 对于帖子 {post_id} 不是 YYYY-MM-DD HH:MM:%S 格式。")
                    pass
        except Exception as e:
            app.logger.warning(f"读取或解析 TXT 文件 '{txt_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
            pass

    # 优先级 3: 从文件名解析 (Unix 时间戳)
    for filename in files_for_post:
        # 匹配 9-11 位数字 (常见的 Unix 时间戳长度，单位秒)
        match_ts_in_name = re.search(r'(\d{9,11})', os.path.splitext(filename)[0])
        if match_ts_in_name:
            ts_str = match_ts_in_name.group(1)
            try:
                ts_int = int(ts_str)
                # 基本合理性检查: 时间戳在 ~2000-01-01 和 ~2050-01-01 之间
                if 946684800 <= ts_int < 2524608000:
                    timestamp = datetime.fromtimestamp(ts_int)
                    return timestamp
            except (ValueError, OSError) as e:
                app.logger.debug(f"文件名 '{filename}' 包含无效的 Unix 时间戳 '{ts_str}' (帖子 {post_id}): {e}")
                pass

    # 优先级 4: 文件系统修改时间
    if files_for_post:
        first_file_path = os.path.join(user_folder_path, files_for_post[0])
        try:
            mod_time = os.path.getmtime(first_file_path)
            timestamp = datetime.fromtimestamp(mod_time)
            return timestamp
        except OSError as e:
            app.logger.warning(f"无法获取文件 '{first_file_path}' 的修改时间 (帖子 {post_id}): {e}")
            pass
    
    app.logger.debug(f"未能从任何来源为帖子 {post_id} 确定时间戳。")
    return None


def process_and_cache_user_posts(username: str, force_rescan: bool = False) -> Tuple[int, int]:
    """
    处理某个用户的所有文件，并保存到数据库。
    如果 force_rescan 为 True，则在重新扫描之前删除该用户的所有现有帖子。
    返回 (新增帖子数量, 已删除帖子数量)。
    """
    root_data_folder = app.config['ROOT_DATA_FOLDER']
    user_folder_path = os.path.join(root_data_folder, username)
    
    if not os.path.isdir(user_folder_path):
        app.logger.error(f"用户文件夹 '{user_folder_path}' 未找到。")
        return 0, 0

    db_user = User.query.filter_by(username=username).first()
    if not db_user:
        db_user = User(username=username)
        db.session.add(db_user)
        db.session.commit() # 提交以获取 db_user.id
        app.logger.info(f"在数据库中创建了新用户 '{username}'。")
    
    # --- 收集和更新用户 JSON 元数据 ---
    user_json_data = {}
    json_files_in_folder = [f for f in os.listdir(user_folder_path) if f.endswith('.json')]
    
    if json_files_in_folder:
        # 尝试从最新的 JSON 文件中提取用户元数据
        # (通常 gallery-dl 会按时间顺序下载，所以取文件名最大的可能更合理)
        for json_file_name in sorted(json_files_in_folder, reverse=True): 
            json_path = os.path.join(user_folder_path, json_file_name)
            try:
                with open(json_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # 优先使用 'author' 字段，如果没有则尝试 'user' 字段
                    user_info = data.get('author') or data.get('user')
                    # 确保提取的用户信息是当前要处理的用户
                    # Gallery-dl的JSON文件通常将文件名中的ID作为tweet_id，而用户的id可能是不同的长整数
                    # 这里尝试匹配 nick 或 name，但最可靠的是直接使用文件夹名作为 username
                    if user_info and (user_info.get('nick') == username or user_info.get('name') == username or data.get('author',{}).get('nick') == username or data.get('user',{}).get('nick') == username): # 更好的匹配逻辑
                        user_json_data = user_info
                        app.logger.debug(f"从 '{json_file_name}' 提取了用户 '{username}' 的元数据。")
                        break # 找到信息后退出循环
            except (json.JSONDecodeError, Exception) as e:
                app.logger.warning(f"读取或解析 '{json_path}' 中的用户元数据失败: {e}")
                
    # 更新 db_user 的字段，只更新非 None 的值
    db_user.name = user_json_data.get('name', db_user.name)
    db_user.nick = user_json_data.get('nick', db_user.nick)
    db_user.location = user_json_data.get('location', db_user.location)
    db_user.description = user_json_data.get('description', db_user.description)
    db_user.verified = user_json_data.get('verified', db_user.verified)
    db_user.profile_image_url = user_json_data.get('profile_image', db_user.profile_image_url)
    db_user.favourites_count = user_json_data.get('favourites_count', db_user.favourites_count)
    db_user.followers_count = user_json_data.get('followers_count', db_user.followers_count)
    db_user.friends_count = user_json_data.get('friends_count', db_user.friends_count)
    db_user.listed_count = user_json_data.get('listed_count', db_user.listed_count)
    db_user.media_count = user_json_data.get('media_count', db_user.media_count)
    db_user.statuses_count = user_json_data.get('statuses_count', db_user.statuses_count)
    
    # 提交用户元数据更新
    try:
        db.session.add(db_user) # 重新添加到会话以确保更新被跟踪
        db.session.commit()
        app.logger.info(f"已更新用户 @{username} 的元数据。")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"更新用户 @{username} 元数据失败: {e}")


    posts_deleted = 0
    if force_rescan:
        app.logger.info(f"强制重新扫描 @{username}。正在删除现有帖子...")
        deleted_count = db.session.query(Post).filter_by(user_id=db_user.id).delete()
        db.session.commit()
        posts_deleted = deleted_count
        app.logger.info(f"删除了 @{username} 的 {deleted_count} 条现有帖子。")
    else:
        if db_user.posts: 
            app.logger.info(f"@{username} 的帖子已存在于数据库中。无需重新扫描现有帖子。")
            return 0, 0

    app.logger.info(f"正在启动 @{username} 的完整文件扫描 (填充数据库缓存)...")
    
    files_by_tweet_id: Dict[str, List[str]] = defaultdict(list)
    
    try:
        for filename in os.listdir(user_folder_path):
            file_path = os.path.join(user_folder_path, filename)
            if os.path.isfile(file_path):
                tweet_id = extract_tweet_id_from_filename(filename)
                if tweet_id:
                    files_by_tweet_id[tweet_id].append(filename)
    except Exception as e:
        app.logger.error(f"列出 '{user_folder_path}' 中的文件时出错: {e}")
        return 0, posts_deleted

    newly_added_posts_count = 0
    for tweet_id, associated_files in files_by_tweet_id.items():
        if db.session.get(Post, tweet_id):
            app.logger.debug(f"帖子 {tweet_id} (用户 {username}) 已存在于数据库中，跳过。")
            continue

        temp_post_data = {
            'id': tweet_id,
            'user_id': db_user.id,
            'timestamp': None,
            'text_content': None,
            'media_files': [],
            'retweet_count': None,
            'reply_count': None,
            'favorite_count': None,
            'bookmark_count': None,
            'raw_json_data': None,
        }

        # 专门处理 JSON 数据以获取 'date' 字段和 raw_json_data_text
        json_file_path = next((os.path.join(user_folder_path, f) for f in associated_files if f.endswith('.json')), None)
        json_data = None
        if json_file_path and os.path.exists(json_file_path):
            try:
                with open(json_file_path, 'r', encoding='utf-8') as f:
                    json_data = json.load(f)
                    temp_post_data['raw_json_data'] = json.dumps(json_data)
                    temp_post_data['retweet_count'] = json_data.get('retweet_count')
                    temp_post_data['favorite_count'] = json_data.get('favorite_count')
                    temp_post_data['reply_count'] = json_data.get('reply_count')
                    temp_post_data['bookmark_count'] = json_data.get('bookmark_count')
                    # 优先使用 'full_text', 'content', 'text' 作为推文文本
                    if not temp_post_data['text_content'] and ('full_text' in json_data or 'content' in json_data or 'text' in json_data):
                        temp_post_data['text_content'] = json_data.get('full_text') or json_data.get('content') or json_data.get('text')
            except json.JSONDecodeError as e:
                app.logger.warning(f"解析 JSON 文件 {json_file_path} (帖子 {tweet_id}) 失败: {e}")
            except Exception as e:
                app.logger.warning(f"读取 JSON 文件 {json_file_path} (帖子 {tweet_id}) 失败: {e}")
                pass

        txt_file = next((f for f in associated_files if f.endswith('.txt')), None)
        if txt_file:
            txt_path = os.path.join(user_folder_path, txt_file)
            try:
                with open(txt_path, 'r', encoding='utf-8') as f:
                    lines = f.readlines()
                    if lines:
                        first_line = lines[0].strip()
                        try:
                            datetime.strptime(first_line, '%Y-%m-%d %H:%M:%S')
                            if not temp_post_data['text_content']: # 只有在 JSON 中没有提供文本时才从 TXT 获取
                                temp_post_data['text_content'] = "".join(lines[1:]).strip()
                        except ValueError:
                            if not temp_post_data['text_content']: # 只有在 JSON 中没有提供文本时才从 TXT 获取
                                temp_post_data['text_content'] = "".join(lines).strip()
            except Exception as e:
                app.logger.warning(f"读取或解析 TXT 文件 {txt_path} (帖子 {tweet_id}) 失败: {e}")
                pass

        for filename in associated_files:
            if filename.lower().endswith(app.jinja_env.globals['MEDIA_EXTENSIONS']):
                temp_post_data['media_files'].append(os.path.join(username, filename).replace('\\', '/'))

        temp_post_data['timestamp'] = parse_timestamp(tweet_id, user_folder_path, associated_files)
        
        db_post = Post(
            id=temp_post_data['id'],
            user_id=db_user.id,
            timestamp=temp_post_data['timestamp'],
            text_content=temp_post_data['text_content'],
            media_files_json=json.dumps(temp_post_data['media_files']),
            retweet_count=temp_post_data['retweet_count'],
            reply_count=temp_post_data['reply_count'],
            favorite_count=temp_post_data['favorite_count'],
            bookmark_count=temp_post_data['bookmark_count'],
            raw_json_data_text=temp_post_data['raw_json_data']
        )
        db.session.add(db_post)
        newly_added_posts_count += 1
    
    try:
        db.session.commit()
        app.logger.info(f"成功处理并向数据库添加了 @{username} 的 {newly_added_posts_count} 条新帖子。")
    except Exception as e:
        db.session.rollback()
        app.logger.error(f"未能将 @{username} 的帖子提交到数据库: {e}")
    
    return newly_added_posts_count, posts_deleted

# --- Jinja2 自定义相对时间过滤器 ---
@app.template_filter('relative_time')
def relative_time_filter(dt: datetime) -> str:
    if not dt:
        return "时间未知"
    
    now = datetime.now()
    diff = now - dt

    if diff.days > 365:
        years = diff.days // 365
        return f"{years} 年前"
    elif diff.days > 30:
        months = diff.days // 30
        return f"{months} 月前"
    elif diff.seconds > 3600:
        hours = diff.seconds // 3600
        return f"{hours} 小时前"
    elif diff.seconds > 60:
        minutes = diff.seconds // 60
        return f"{minutes} 分钟前"
    else:
        return "刚刚"

# --- Jinja2 过滤器: 格式化大数字 (例如 12345 -> 12.3K) ---
@app.template_filter('format_large_number')
def format_large_number_filter(num):
    if num is None:
        return '0'
    num = int(num)
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.1f}B"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.1f}M"
    if num >= 1_000:
        return f"{num / 1_000:.1f}K"
    return str(num)


# --- 路由 ---

@app.route('/')
def index():
    """
    显示所有用户名的列表。
    """
    user_folders = []
    root_data_folder = app.config['ROOT_DATA_FOLDER']
    if os.path.isdir(root_data_folder):
        user_folders = sorted([
            d for d in os.listdir(root_data_folder)
            if os.path.isdir(os.path.join(root_data_folder, d))
        ])
    else:
        app.logger.error(f"根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")
        
    return render_template('index.html', users=user_folders)

@app.route('/user/<username>')
def user_posts(username):
    """
    显示特定用户的推文列表的第一页，为无限滚动做准备。
    """
    user_folder_path = os.path.join(app.config['ROOT_DATA_FOLDER'], username)
    if not os.path.isdir(user_folder_path):
        app.logger.warning(f"尝试访问不存在的用户文件夹: {user_folder_path}")
        abort(404, description=f"用户 '{username}' 不存在。")

    db_user = User.query.filter_by(username=username).first()
    
    # 检查用户或其帖子是否在数据库中，如果没有，则进行处理
    if not db_user or not db_user.posts: # 如果用户不存在，或者用户存在但没有关联的帖子
        app.logger.info(f"用户 '{username}' 或其帖子在数据库中未找到。正在初始化处理。")
        _, _ = process_and_cache_user_posts(username)
        # 处理后重新从数据库中获取用户，以确保关联的帖子已加载
        db_user = User.query.filter_by(username=username).first()
    
    if not db_user: # 如果处理后仍然没有用户 (例如，文件夹是空的或存在问题)
        app.logger.error(f"处理后未能从数据库中检索到用户 '{username}'。")
        abort(500, description="内部服务器错误: 无法加载用户数据。")

    base_query = Post.query.filter_by(user_id=db_user.id)
    
    per_page = app.config.get('POSTS_PER_PAGE', 20)
    pagination = base_query.order_by(Post.id.desc())\
                               .paginate(page=1, per_page=per_page, error_out=False)

    return render_template('user_posts.html', 
                           username=username, 
                           posts=pagination.items,
                           user_details=db_user.to_dict(), # 传递用户详情到模板
                           has_next=pagination.has_next,
                           next_page=pagination.next_num,
                           total_posts=pagination.total)

@app.route('/api/user/<username>/posts')
def api_user_posts(username):
    """
    API 端点，以 JSON 格式返回分页的帖子数据，用于无限滚动。
    """
    db_user = User.query.filter_by(username=username).first()
    if not db_user:
        app.logger.warning(f"API 请求的用户 '{username}' 不存在。")
        return jsonify({'error': '用户未找到'}), 404

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', app.config.get('POSTS_PER_PAGE', 20), type=int)

    base_query = Post.query.filter_by(user_id=db_user.id)

    pagination = base_query.order_by(Post.id.desc())\
                               .paginate(page=page, per_page=per_page, error_out=False)

    posts_data = [post.to_dict() for post in pagination.items]

    return jsonify({
        'posts': posts_data,
        'has_next': pagination.has_next,
        'next_page': pagination.next_num,
        'current_page': pagination.page,
        'total_pages': pagination.pages,
        'total_posts': pagination.total
    })

@app.route('/user/<username>/all')
def user_posts_all(username):
    """
    机器人友好界面: 在单个页面上渲染某个用户的所有帖子。无分页/JS。
    """
    user_folder_path = os.path.join(app.config['ROOT_DATA_FOLDER'], username)
    if not os.path.isdir(user_folder_path):
        app.logger.warning(f"尝试为机器人界面访问不存在的用户文件夹: {user_folder_path}")
        abort(404, description=f"用户 '{username}' 不存在。")

    db_user = User.query.filter_by(username=username).first()
    
    if not db_user or not db_user.posts:
        app.logger.info(f"用户 '{username}' 或其帖子在数据库中未找到 (为机器人界面)。正在初始化处理。")
        _, _ = process_and_cache_user_posts(username)
        db_user = User.query.filter_by(username=username).first()
    
    if not db_user:
        app.logger.error(f"处理后未能从数据库中检索到用户 '{username}' (为机器人界面)。")
        abort(500, description="内部服务器错误: 无法加载用户数据。")

    base_query = Post.query.filter_by(user_id=db_user.id)
    
    all_posts = base_query.order_by(Post.id.desc()).all()

    return render_template('user_posts_all.html',
                           username=username,
                           posts=all_posts,
                           user_details=db_user.to_dict(), # 传递用户详情到模板
                           total_posts=len(all_posts))


@app.route('/media/<path:filename>')
def serve_media(filename):
    """
    用于从 ROOT_DATA_FOLDER 的子目录提供媒体文件的静态路由。
    """
    safe_filename = os.path.normpath(filename)
    if safe_filename.startswith('..') or os.path.isabs(safe_filename):
        app.logger.warning(f"媒体请求中检测到路径遍历尝试: {filename}")
        abort(400)

    parts = safe_filename.split(os.sep)
    if len(parts) < 2:
        app.logger.warning(f"无效的媒体文件名格式: {filename}")
        abort(404)

    user_dirname = parts[0]
    media_basename = os.sep.join(parts[1:])

    actual_user_dir = os.path.join(app.config['ROOT_DATA_FOLDER'], user_dirname)
    
    full_file_path = os.path.join(actual_user_dir, media_basename)
    if os.path.isdir(actual_user_dir) and os.path.exists(full_file_path):
        response = send_from_directory(actual_user_dir, media_basename)
        response.headers['Cache-Control'] = 'public, max-age=3600' # 1 小时缓存
        return response
    else:
        app.logger.warning(f"媒体文件未找到: {full_file_path}")
        abort(404)

@app.route('/avatar/<username>')
def serve_avatar(username):
    """
    根据用户名提供用户头像。
    如果找不到特定用户的头像，则返回默认头像。
    """
    user_avatar_folder = app.config['USER_AVATAR_FOLDER']
    default_avatar_filename = app.config['DEFAULT_AVATAR_FILENAME']

    user_avatar_path_jpg = os.path.join(user_avatar_folder, f"{username}.jpg")
    user_avatar_path_png = os.path.join(user_avatar_folder, f"{username}.png")
    
    avatar_to_serve = None
    if os.path.exists(user_avatar_path_jpg):
        avatar_to_serve = f"{username}.jpg"
    elif os.path.exists(user_avatar_path_png):
        avatar_to_serve = f"{username}.png"
    elif os.path.exists(os.path.join(user_avatar_folder, default_avatar_filename)):
        avatar_to_serve = default_avatar_filename
    else:
        app.logger.error(f"默认头像文件 '{default_avatar_filename}' 在 '{user_avatar_folder}' 中缺失。")
        abort(404, description="默认头像文件也缺失。")

    response = send_from_directory(user_avatar_folder, avatar_to_serve)
    response.headers['Cache-Control'] = 'public, max-age=86400' # 24 小时缓存
    return response

# --- CLI 命令: 扫描所有用户 ---
@app.cli.command("scan-all-users")
@click.option('--force-rescan', is_flag=True, help='强制对所有用户进行完整的重新扫描和重新填充，删除现有数据。')
def scan_all_users_command(force_rescan):
    """扫描所有用户存档文件夹并填充/更新数据库。"""
    with app.app_context(): # 确保 CLI 命令在 Flask 应用上下文中运行
        app.logger.info(f"CLI scan-all-users 命令已调用。强制重新扫描: {force_rescan}")
        root_data_folder = app.config['ROOT_DATA_FOLDER']
        if not os.path.isdir(root_data_folder):
            app.logger.error(f"扫描失败: 根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")
            click.echo(f"错误: 根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")
            return

        user_dirs = [d for d in os.listdir(root_data_folder) if os.path.isdir(os.path.join(root_data_folder, d))]
        
        if not user_dirs:
            app.logger.info(f"在 '{root_data_folder}' 中未找到任何用户目录。")
            click.echo(f"在 '{root_data_folder}' 中未找到任何用户目录。")
            return

        total_new_posts = 0
        total_deleted_posts = 0

        for username in user_dirs:
            click.echo(f"正在处理用户 @{username}...")
            new_count, deleted_count = process_and_cache_user_posts(username, force_rescan=force_rescan)
            total_new_posts += new_count
            total_deleted_posts += deleted_count
            click.echo(f"  @{username}: 添加了 {new_count} 条帖子, 删除了 {deleted_count} 条帖子。")

        click.echo(f"\n--- 扫描完成 ---")
        click.echo(f"总共添加的新帖子: {total_new_posts}")
        click.echo(f"总共删除的帖子: {total_deleted_posts}")
        app.logger.info(f"CLI scan-all-users 命令完成。添加了 {total_new_posts} 条，删除了 {total_deleted_posts} 条。")

# --- CLI 命令: 扫描指定用户 ---
@app.cli.command("scan-user")
@click.argument('username') # 接收一个强制性的 username 参数
@click.option('--force-rescan', is_flag=True, help='强制对指定用户进行完整的重新扫描和重新填充，删除现有数据。')
def scan_user_command(username, force_rescan):
    """扫描指定的用户存档文件夹并填充/更新数据库。"""
    with app.app_context(): # 确保 CLI 命令在 Flask 应用上下文中运行
        app.logger.info(f"CLI scan-user 命令已调用。用户: @{username}。强制重新扫描: {force_rescan}")
        root_data_folder = app.config['ROOT_DATA_FOLDER']
        user_folder_path = os.path.join(root_data_folder, username)
        
        if not os.path.isdir(user_folder_path):
            app.logger.error(f"扫描失败: 用户文件夹 '{user_folder_path}' 不存在或不是一个目录。")
            click.echo(f"错误: 用户文件夹 '{user_folder_path}' 不存在或不是一个目录。")
            return

        click.echo(f"正在处理用户 @{username}...")
        new_count, deleted_count = process_and_cache_user_posts(username, force_rescan=force_rescan)
        
        click.echo(f"\n--- 用户 @{username} 扫描完成 ---")
        click.echo(f"添加了 {new_count} 条帖子。")
        click.echo(f"删除了 {deleted_count} 条帖子。")
        app.logger.info(f"CLI scan-user 命令完成。用户 @{username}: 添加了 {new_count} 条，删除了 {deleted_count} 条。")


# --- 用于自动扫描的后台任务 ---
scheduler = BackgroundScheduler()

def auto_scan_all_users_job():
    """
    后台任务，自动扫描所有用户文件夹并更新数据库。
    """
    with app.app_context(): # 在后台线程中运行 Flask-SQLAlchemy 所必需
        app.logger.info("正在启动所有用户的计划自动扫描...")
        root_data_folder = app.config['ROOT_DATA_FOLDER']
        if not os.path.isdir(root_data_folder):
            app.logger.error(f"自动扫描失败: 根数据文件夹 '{root_data_folder}' 不存在。")
            return

        user_dirs = [d for d in os.listdir(root_data_folder) if os.path.isdir(os.path.join(root_data_folder, d))]
        total_new_posts = 0
        total_deleted_posts = 0
        
        for username in user_dirs:
            new_count, deleted_count = process_and_cache_user_posts(username, force_rescan=False)
            total_new_posts += new_count
            total_deleted_posts += deleted_count

        app.logger.info(f"计划自动扫描完成。总共添加了 {total_new_posts} 条新帖子，删除了 {total_deleted_posts} 条帖子 (预期为 0)。")

# --- 脚本入口点 ---
if __name__ == '__main__':
    # 确保数据库表在应用启动时存在，以避免 'no such table' 错误
    with app.app_context():
        # 如果数据库文件不存在，db.create_all() 会创建它
        # 如果数据库文件存在但表不存在，db.create_all() 会创建缺失的表
        # 这对于第一次运行应用或在未运行 flask db upgrade 的情况下运行非常有用
        db.create_all()
        app.logger.info("数据库表已检查/创建。")

    # 如果启用了自动扫描且是 Flask 主进程，则初始化并启动调度器
    # WERKZEUG_RUN_MAIN 由 Flask reloader 设置，用于区分主进程和重载子进程
    if app.config.get('ENABLE_AUTO_SCAN') and os.environ.get('WERKZEUG_RUN_MAIN') == 'true':
        app.logger.info("调度器已启用。正在主 Flask 进程中添加自动扫描任务。")
        scheduler.add_job(
            func=auto_scan_all_users_job,
            trigger=IntervalTrigger(hours=app.config.get('AUTO_SCAN_INTERVAL_HOURS', 24)),
            id='auto_scan_all_users',
            name='自动扫描所有用户存档',
            replace_existing=True
        )
        scheduler.start()
        app.logger.info(f"调度器已启动。自动扫描将每 {app.config.get('AUTO_SCAN_INTERVAL_HOURS', 24)} 小时运行一次。")

        # 在应用退出时优雅地关闭调度器
        atexit.register(lambda: scheduler.shutdown(wait=False))
    elif app.config.get('ENABLE_AUTO_SCAN'):
        app.logger.info("自动扫描已启用，但调度器未启动 (可能是重载子进程或直接 Python 执行)。")
    else:
        app.logger.info("config.py 中已禁用自动扫描。")

    app.run(host='0.0.0.0', port=5000, debug=False) # 更改了 host, port, debug 参数
