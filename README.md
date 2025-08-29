# Twitter 存档浏览器 (Flask)

[![Python](https://img.shields.io/badge/Python-3.8%2B-blue.svg)](https://www.python.org/)
[![Flask](https://img.shields.io/badge/Flask-2.x-lightgrey.svg)](https://flask.palletsprojects.com/)
[![SQLAlchemy](https://img.shields.io/badge/SQLAlchemy-green.svg)](https://www.sqlalchemy.org/)
[![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一个基于 Flask 的本地 Web 应用，用于浏览通过 `gallery-dl` 等工具下载的 Twitter 用户存档。它提供了一个类似 Twitter Web 端的界面，支持无限滚动，并通过 SQLite 数据库进行数据缓存，以提高性能。

## ✨ 主要功能

*   **类似 Twitter 的用户界面：** 提供直观、美观的 Web 界面，浏览本地 Twitter 存档。
*   **用户列表：** 启动时显示所有已下载的用户列表，点击用户名即可查看其推文。
*   **无限滚动：** 在浏览用户推文时，支持类似社交媒体的无限滚动加载更多内容。
*   **持久化数据缓存：** 使用 SQLite 数据库存储用户和推文的元数据，首次加载后，后续访问速度极快。
*   **后台自动扫描：** 可配置定时任务 (APScheduler)，定期扫描 `ROOT_DATA_FOLDER` 中的新用户或新推文，并自动更新数据库。
*   **命令行工具 (CLI)：**
    *   `flask scan-all-users [--force-rescan]`: 扫描所有用户存档并更新数据库。`--force-rescan` 参数可强制删除旧数据并重新填充。
    *   `flask scan-user <username> [--force-rescan]`: 扫描指定用户的存档并更新数据库。
*   **媒体文件展示：** 正确加载和显示推文中的图片 (.jpg, .png, .gif, .webp) 和视频 (.mp4)。
*   **用户头像支持：** 支持根据用户名加载本地头像文件，若无则显示默认头像。
*   **相对时间显示：** 推文时间以“X 小时前”、“Y 天前”等格式显示。
*   **Bot 友好页面：** 提供 `/user/<username>/all` 路由，一次性渲染所有推文，方便自动化抓取。

## 🚀 快速开始

### 1. 克隆仓库

```bash
git clone https://github.com/Transwarpcom/Gallery-dl_twitter_webui.git
cd your-repo-name
```

### 2. 创建并激活虚拟环境

```bash
python -m venv venv
# Windows
.\venv\Scripts\activate
# Linux/macOS
source venv/bin/activate
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置项目

自行修改在项目根目录下名为 `config.py` 的文件。**务必修改 `ROOT_DATA_FOLDER` 和 `USER_AVATAR_FOLDER` 的路径为您本地的实际路径。**

**`config.py`**
```python
import os

# Flask 应用的根目录 (假设 config.py 与 app.py 在同一目录)
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# Twitter 存档数据根目录
# 重要: 请替换为您的实际根数据文件夹路径
# 示例: r"C:\Users\YourUser\Gallery-dl\twitter" 或 "/path/to/your/twitter/archive"
ROOT_DATA_FOLDER = r"D:\Gallery-dl\twitter" 

# 用户头像文件夹
# 重要: 请配置您的头像文件夹路径
# 示例: r"C:\Users\YourUser\images\avatars" 或 "/path/to/your/avatar/folder"
USER_AVATAR_FOLDER = r"D:\img" 
DEFAULT_AVATAR_FILENAME = "default_profile_normal.png" # 默认头像文件名 (在 USER_AVATAR_FOLDER 中)

# SQLite 数据库配置, 用于缓存已处理的帖子
# 数据库文件将在 BASE_DIR 中创建为 'twitter_archive.db'
SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(BASE_DIR, 'twitter_archive.db')
SQLALCHEMY_TRACK_MODIFICATIONS = False # 禁用跟踪修改以提高性能

# 日志配置
LOG_FILE = os.path.join(BASE_DIR, 'app.log') # 日志文件路径
LOG_LEVEL = 'INFO' # 日志级别 (DEBUG, INFO, WARNING, ERROR, CRITICAL)

# 分页配置
POSTS_PER_PAGE = 20 # 初始渲染和 API 调用每页显示的帖子数量

# 自动扫描配置
ENABLE_AUTO_SCAN = True # 设置为 False 以禁用后台自动扫描
AUTO_SCAN_INTERVAL_HOURS = 24 # 自动扫描的运行频率, 单位小时 (例如, 24 为每天一次)
```

### 5. 准备静态文件

*   **头像文件：** 将您的用户头像文件（例如 `username.jpg` 或 `username.png`）以及 `default_profile_normal.png` 放置在 `config.py` 中 `USER_AVATAR_FOLDER` 指定的路径下。

### 6. 初始化数据库与数据填充

**重要：** 第一次运行或模型更改后，您需要初始化数据库并填充数据。

a. **设置 Flask 应用环境变量：**
   ```bash
   # Windows (CMD)
   set FLASK_APP=app.py
   # Windows (PowerShell)
   $env:FLASK_APP="app.py"
   # Linux/macOS
   export FLASK_APP=app.py
   ```

b. **初始化数据库迁移环境：** (只需运行一次)
   ```bash
   flask db init
   ```

c. **创建初始迁移脚本：** (每次更改 `User` 或 `Post` 模型后运行)
   ```bash
   flask db migrate -m "Initial migration"
   ```
   如果之前运行过，并且删除了 `twitter_archive.db` 文件，这将重新创建新的迁移脚本。

d. **应用数据库迁移：** 这将创建 `twitter_archive.db` 文件并根据模型创建表。
   ```bash
   flask db upgrade
   ```

e. **扫描所有用户数据到数据库：** (初次填充或强制刷新)
   ```bash
   flask scan-all-users --force-rescan
   ```
   *   `--force-rescan`: 会删除数据库中所有现有数据，然后从文件系统重新扫描并填充所有用户的推文。**推荐第一次运行此命令。**
   *   不带 `--force-rescan`：只会扫描 `ROOT_DATA_FOLDER` 中尚未在数据库中的用户，或者已在数据库但没有推文的用户，并添加新推文。

### 7. 运行应用

```bash
flask run
```

然后，在您的浏览器中访问 `http://127.0.0.1:5000/`。

## ⚙️ 命令行工具 (CLI) 使用

在设置 `FLASK_APP=app.py` 环境变量后，您可以使用以下命令：

*   **扫描所有用户存档：**
    ```bash
    flask scan-all-users
    # 或强制重新扫描所有用户：
    flask scan-all-users --force-rescan
    ```

*   **扫描指定用户存档：**
    ```bash
    flask scan-user <username>
    # 例如：
    flask scan-user my_twitter_user
    # 或强制重新扫描指定用户：
    flask scan-user my_twitter_user --force-rescan
    ```

## 🔄 后台自动扫描

如果 `config.py` 中的 `ENABLE_AUTO_SCAN` 设置为 `True`，当您运行 `flask run` 启动 Web 应用时，一个后台任务调度器 (APScheduler) 会自动启动。它将按照 `AUTO_SCAN_INTERVAL_HOURS` 定义的周期，自动扫描 `ROOT_DATA_FOLDER` 中所有用户的存档，并将其内容（增量）更新到数据库。

## 💡 开发与维护

*   **数据库模式变更：** 如果您修改了 `app.py` 中 `User` 或 `Post` 模型，请务必执行以下步骤来更新数据库：
    1.  `flask db migrate -m "描述您的更改"`
    2.  `flask db upgrade`
*   **日志文件：** 应用日志将记录到 `config.py` 中 `LOG_FILE` 指定的文件 (默认为 `app.log`)。
*   **性能考量：** 对于非常大的存档，首次 `scan-all-users` 可能需要较长时间。无限滚动和数据库缓存已经极大优化了 Web 浏览体验。
