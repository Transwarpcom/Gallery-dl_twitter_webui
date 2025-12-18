import os
import re
from flask import Blueprint, render_template, request, abort, jsonify, send_from_directory, current_app
from app.models import User, Post
from app.services import process_and_cache_user_posts
from datetime import datetime

bp = Blueprint('main', __name__)

def is_valid_username(username):
    # 仅允许字母、数字和下划线，防止路径遍历
    return re.match(r'^[a-zA-Z0-9_]+$', username) is not None

# --- Jinja2 自定义相对时间过滤器 ---
@bp.app_template_filter('relative_time')
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
@bp.app_template_filter('format_large_number')
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

@bp.route('/')
def index():
    """
    显示所有用户名的列表。
    """
    user_folders = []
    root_data_folder = current_app.config['ROOT_DATA_FOLDER']
    if os.path.isdir(root_data_folder):
        user_folders = sorted([
            d for d in os.listdir(root_data_folder)
            if os.path.isdir(os.path.join(root_data_folder, d))
        ])
    else:
        current_app.logger.error(f"根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")

    return render_template('index.html', users=user_folders)

@bp.route('/user/<username>')
def user_posts(username):
    """
    显示特定用户的推文列表的第一页，为无限滚动做准备。
    """
    if not is_valid_username(username):
        current_app.logger.warning(f"检测到无效的用户名格式: {username}")
        abort(400, description="无效的用户名")

    user_folder_path = os.path.join(current_app.config['ROOT_DATA_FOLDER'], username)
    if not os.path.isdir(user_folder_path):
        current_app.logger.warning(f"尝试访问不存在的用户文件夹: {user_folder_path}")
        abort(404, description=f"用户 '{username}' 不存在。")

    db_user = User.query.filter_by(username=username).first()

    # 检查用户或其帖子是否在数据库中，如果没有，则进行处理
    if not db_user or not db_user.posts: # 如果用户不存在，或者用户存在但没有关联的帖子
        current_app.logger.info(f"用户 '{username}' 或其帖子在数据库中未找到。正在初始化处理。")
        _, _ = process_and_cache_user_posts(username)
        # 处理后重新从数据库中获取用户，以确保关联的帖子已加载
        db_user = User.query.filter_by(username=username).first()

    if not db_user: # 如果处理后仍然没有用户 (例如，文件夹是空的或存在问题)
        current_app.logger.error(f"处理后未能从数据库中检索到用户 '{username}'。")
        abort(500, description="内部服务器错误: 无法加载用户数据。")

    base_query = Post.query.filter_by(user_id=db_user.id)

    per_page = current_app.config.get('POSTS_PER_PAGE', 20)
    pagination = base_query.order_by(Post.id.desc())\
                               .paginate(page=1, per_page=per_page, error_out=False)

    return render_template('user_posts.html',
                           username=username,
                           posts=pagination.items,
                           user_details=db_user.to_dict(), # 传递用户详情到模板
                           has_next=pagination.has_next,
                           next_page=pagination.next_num,
                           total_posts=pagination.total)

@bp.route('/api/user/<username>/posts')
def api_user_posts(username):
    """
    API 端点，以 JSON 格式返回分页的帖子数据，用于无限滚动。
    """
    if not is_valid_username(username):
        return jsonify({'error': '无效的用户名'}), 400

    db_user = User.query.filter_by(username=username).first()
    if not db_user:
        current_app.logger.warning(f"API 请求的用户 '{username}' 不存在。")
        return jsonify({'error': '用户未找到'}), 404

    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', current_app.config.get('POSTS_PER_PAGE', 20), type=int)

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

@bp.route('/user/<username>/all')
def user_posts_all(username):
    """
    机器人友好界面: 在单个页面上渲染某个用户的所有帖子。无分页/JS。
    """
    if not is_valid_username(username):
        abort(400, description="无效的用户名")

    user_folder_path = os.path.join(current_app.config['ROOT_DATA_FOLDER'], username)
    if not os.path.isdir(user_folder_path):
        current_app.logger.warning(f"尝试为机器人界面访问不存在的用户文件夹: {user_folder_path}")
        abort(404, description=f"用户 '{username}' 不存在。")

    db_user = User.query.filter_by(username=username).first()

    if not db_user or not db_user.posts:
        current_app.logger.info(f"用户 '{username}' 或其帖子在数据库中未找到 (为机器人界面)。正在初始化处理。")
        _, _ = process_and_cache_user_posts(username)
        db_user = User.query.filter_by(username=username).first()

    if not db_user:
        current_app.logger.error(f"处理后未能从数据库中检索到用户 '{username}' (为机器人界面)。")
        abort(500, description="内部服务器错误: 无法加载用户数据。")

    base_query = Post.query.filter_by(user_id=db_user.id)

    all_posts = base_query.order_by(Post.id.desc()).all()

    return render_template('user_posts_all.html',
                           username=username,
                           posts=all_posts,
                           user_details=db_user.to_dict(), # 传递用户详情到模板
                           total_posts=len(all_posts))


@bp.route('/media/<path:filename>')
def serve_media(filename):
    """
    用于从 ROOT_DATA_FOLDER 的子目录提供媒体文件的静态路由。
    """
    safe_filename = os.path.normpath(filename)
    if safe_filename.startswith('..') or os.path.isabs(safe_filename):
        current_app.logger.warning(f"媒体请求中检测到路径遍历尝试: {filename}")
        abort(400)

    parts = safe_filename.split(os.sep)
    if len(parts) < 2:
        current_app.logger.warning(f"无效的媒体文件名格式: {filename}")
        abort(404)

    user_dirname = parts[0]
    media_basename = os.sep.join(parts[1:])

    actual_user_dir = os.path.join(current_app.config['ROOT_DATA_FOLDER'], user_dirname)

    full_file_path = os.path.join(actual_user_dir, media_basename)
    if os.path.isdir(actual_user_dir) and os.path.exists(full_file_path):
        response = send_from_directory(actual_user_dir, media_basename)
        response.headers['Cache-Control'] = 'public, max-age=3600' # 1 小时缓存
        return response
    else:
        current_app.logger.warning(f"媒体文件未找到: {full_file_path}")
        abort(404)

@bp.route('/avatar/<username>')
def serve_avatar(username):
    """
    根据用户名提供用户头像。
    如果找不到特定用户的头像，则返回默认头像。
    """
    user_avatar_folder = current_app.config['USER_AVATAR_FOLDER']
    default_avatar_filename = current_app.config['DEFAULT_AVATAR_FILENAME']

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
        current_app.logger.error(f"默认头像文件 '{default_avatar_filename}' 在 '{user_avatar_folder}' 中缺失。")
        abort(404, description="默认头像文件也缺失。")

    response = send_from_directory(user_avatar_folder, avatar_to_serve)
    response.headers['Cache-Control'] = 'public, max-age=86400' # 24 小时缓存
    return response
