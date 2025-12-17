import os
import click
from flask import current_app
from flask.cli import with_appcontext
from app.services import process_and_cache_user_posts

# --- CLI 命令: 扫描所有用户 ---
@click.command("scan-all-users")
@click.option('--force-rescan', is_flag=True, help='强制对所有用户进行完整的重新扫描和重新填充，删除现有数据。')
@with_appcontext
def scan_all_users_command(force_rescan):
    """扫描所有用户存档文件夹并填充/更新数据库。"""
    current_app.logger.info(f"CLI scan-all-users 命令已调用。强制重新扫描: {force_rescan}")
    root_data_folder = current_app.config['ROOT_DATA_FOLDER']
    if not os.path.isdir(root_data_folder):
        current_app.logger.error(f"扫描失败: 根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")
        click.echo(f"错误: 根数据文件夹 '{root_data_folder}' 不存在或不是一个目录。")
        return

    user_dirs = [d for d in os.listdir(root_data_folder) if os.path.isdir(os.path.join(root_data_folder, d))]

    if not user_dirs:
        current_app.logger.info(f"在 '{root_data_folder}' 中未找到任何用户目录。")
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
    current_app.logger.info(f"CLI scan-all-users 命令完成。添加了 {total_new_posts} 条，删除了 {total_deleted_posts} 条。")

# --- CLI 命令: 扫描指定用户 ---
@click.command("scan-user")
@click.argument('username') # 接收一个强制性的 username 参数
@click.option('--force-rescan', is_flag=True, help='强制对指定用户进行完整的重新扫描和重新填充，删除现有数据。')
@with_appcontext
def scan_user_command(username, force_rescan):
    """扫描指定的用户存档文件夹并填充/更新数据库。"""
    current_app.logger.info(f"CLI scan-user 命令已调用。用户: @{username}。强制重新扫描: {force_rescan}")
    root_data_folder = current_app.config['ROOT_DATA_FOLDER']
    user_folder_path = os.path.join(root_data_folder, username)

    if not os.path.isdir(user_folder_path):
        current_app.logger.error(f"扫描失败: 用户文件夹 '{user_folder_path}' 不存在或不是一个目录。")
        click.echo(f"错误: 用户文件夹 '{user_folder_path}' 不存在或不是一个目录。")
        return

    click.echo(f"正在处理用户 @{username}...")
    new_count, deleted_count = process_and_cache_user_posts(username, force_rescan=force_rescan)

    click.echo(f"\n--- 用户 @{username} 扫描完成 ---")
    click.echo(f"添加了 {new_count} 条帖子。")
    click.echo(f"删除了 {deleted_count} 条帖子。")
    current_app.logger.info(f"CLI scan-user 命令完成。用户 @{username}: 添加了 {new_count} 条，删除了 {deleted_count} 条。")
