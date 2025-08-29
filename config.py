import os

# Flask 应用的根目录 (假设 config.py 与 app.py 在同一目录)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Twitter 存档数据根目录
# 重要: 请替换为您的实际根数据文件夹路径
ROOT_DATA_FOLDER = r"D:\Gallery-dl\twitter" # 示例: r"C:\Users\YourUser\Gallery-dl\twitter"

# 用户头像文件夹
# 重要: 请配置您的头像文件夹路径
USER_AVATAR_FOLDER = r"D:\img" # 示例: r"C:\Users\YourUser\images\avatars"
DEFAULT_AVATAR_FILENAME = "default_profile_normal.png"

# SQLite 数据库配置, 用于缓存已处理的帖子
# 数据库文件将在 BASE_DIR 中创建
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'twitter_archive.db')
SQLALCHEMY_TRACK_MODIFICATIONS = False

# 日志配置
LOG_FILE = os.path.join(BASE_DIR, 'app.log')
LOG_LEVEL = 'INFO' # 选项: DEBUG, INFO, WARNING, ERROR, CRITICAL

# 分页
POSTS_PER_PAGE = 20 # 初始渲染和 API 调用每页显示的帖子数量

# 自动扫描配置
ENABLE_AUTO_SCAN = True # 设置为 False 以禁用后台自动扫描
AUTO_SCAN_INTERVAL_HOURS = 24 # 自动扫描的运行频率, 单位小时 (例如, 24 为每天一次)