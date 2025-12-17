import os
import json
import logging
from collections import defaultdict
from typing import Dict, List, Tuple
from datetime import datetime
from flask import current_app

from app.extensions import db
from app.models import User, Post
from app.utils import extract_tweet_id_from_filename, parse_timestamp

logger = logging.getLogger(__name__)

def process_and_cache_user_posts(username: str, force_rescan: bool = False) -> Tuple[int, int]:
    """
    处理某个用户的所有文件，并保存到数据库。
    如果 force_rescan 为 True，则在重新扫描之前删除该用户的所有现有帖子。
    返回 (新增帖子数量, 已删除帖子数量)。
    """
    # Need to access config from current_app context
    root_data_folder = current_app.config['ROOT_DATA_FOLDER']
    user_folder_path = os.path.join(root_data_folder, username)

    if not os.path.isdir(user_folder_path):
        logger.error(f"用户文件夹 '{user_folder_path}' 未找到。")
        return 0, 0

    db_user = User.query.filter_by(username=username).first()
    if not db_user:
        db_user = User(username=username)
        db.session.add(db_user)
        db.session.commit() # 提交以获取 db_user.id
        logger.info(f"在数据库中创建了新用户 '{username}'。")

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
                        logger.debug(f"从 '{json_file_name}' 提取了用户 '{username}' 的元数据。")
                        break # 找到信息后退出循环
            except (json.JSONDecodeError, Exception) as e:
                logger.warning(f"读取或解析 '{json_path}' 中的用户元数据失败: {e}")

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
        logger.info(f"已更新用户 @{username} 的元数据。")
    except Exception as e:
        db.session.rollback()
        logger.error(f"更新用户 @{username} 元数据失败: {e}")


    posts_deleted = 0
    if force_rescan:
        logger.info(f"强制重新扫描 @{username}。正在删除现有帖子...")
        deleted_count = db.session.query(Post).filter_by(user_id=db_user.id).delete()
        db.session.commit()
        posts_deleted = deleted_count
        logger.info(f"删除了 @{username} 的 {deleted_count} 条现有帖子。")
    else:
        if db_user.posts:
            logger.info(f"@{username} 的帖子已存在于数据库中。无需重新扫描现有帖子。")
            return 0, 0

    logger.info(f"正在启动 @{username} 的完整文件扫描 (填充数据库缓存)...")

    files_by_tweet_id: Dict[str, List[str]] = defaultdict(list)

    try:
        for filename in os.listdir(user_folder_path):
            file_path = os.path.join(user_folder_path, filename)
            if os.path.isfile(file_path):
                tweet_id = extract_tweet_id_from_filename(filename)
                if tweet_id:
                    files_by_tweet_id[tweet_id].append(filename)
    except Exception as e:
        logger.error(f"列出 '{user_folder_path}' 中的文件时出错: {e}")
        return 0, posts_deleted

    newly_added_posts_count = 0

    from app.constants import MEDIA_EXTENSIONS

    for tweet_id, associated_files in files_by_tweet_id.items():
        if db.session.get(Post, tweet_id):
            logger.debug(f"帖子 {tweet_id} (用户 {username}) 已存在于数据库中，跳过。")
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
                logger.warning(f"解析 JSON 文件 {json_file_path} (帖子 {tweet_id}) 失败: {e}")
            except Exception as e:
                logger.warning(f"读取 JSON 文件 {json_file_path} (帖子 {tweet_id}) 失败: {e}")
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
                logger.warning(f"读取或解析 TXT 文件 {txt_path} (帖子 {tweet_id}) 失败: {e}")
                pass

        for filename in associated_files:
            if filename.lower().endswith(MEDIA_EXTENSIONS):
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
        logger.info(f"成功处理并向数据库添加了 @{username} 的 {newly_added_posts_count} 条新帖子。")
    except Exception as e:
        db.session.rollback()
        logger.error(f"未能将 @{username} 的帖子提交到数据库: {e}")

    return newly_added_posts_count, posts_deleted
