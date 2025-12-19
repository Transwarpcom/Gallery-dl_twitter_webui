from typing import List, Optional, Dict, Any
import json
import logging
from functools import cached_property
from app.extensions import db

logger = logging.getLogger(__name__)

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

    __table_args__ = (
        db.Index('idx_post_user_id_id', 'user_id', 'id'),
    )

    def __repr__(self):
        return f'<推文 {self.id} 来自 {self.user.username}>'

    @cached_property
    def media_files(self) -> List[str]:
        # Cached to avoid repeated JSON parsing on every access
        if self.media_files_json:
            try:
                return json.loads(self.media_files_json)
            except json.JSONDecodeError as e:
                logger.error(f"解析帖子 {self.id} 的 media_files_json 失败: {e}")
                return []
        return []

    @cached_property
    def raw_json_data(self) -> Optional[Dict[str, Any]]:
        # Cached to avoid repeated JSON parsing on every access
        if self.raw_json_data_text:
            try:
                return json.loads(self.raw_json_data_text)
            except json.JSONDecodeError as e:
                logger.error(f"解析帖子 {self.id} 的 raw_json_data_text 失败: {e}")
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
