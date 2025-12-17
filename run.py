import os
import atexit
from apscheduler.triggers.interval import IntervalTrigger
from app import create_app
from app.extensions import scheduler
from app.services import process_and_cache_user_posts

app = create_app()

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

if __name__ == '__main__':
    # 确保数据库表在应用启动时存在
    with app.app_context():
        from app.extensions import db
        db.create_all()
        app.logger.info("数据库表已检查/创建。")

    # 如果启用了自动扫描且是 Flask 主进程
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

        atexit.register(lambda: scheduler.shutdown(wait=False))
    elif app.config.get('ENABLE_AUTO_SCAN'):
        app.logger.info("自动扫描已启用，但调度器未启动 (可能是重载子进程或直接 Python 执行)。")
    else:
        app.logger.info("config.py 中已禁用自动扫描。")

    app.run(host='0.0.0.0', port=5000, debug=False)
