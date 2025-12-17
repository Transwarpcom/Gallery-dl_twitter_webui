import os
import re
import json
import logging
from datetime import datetime
from typing import List, Optional

logger = logging.getLogger(__name__)

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
                        logger.debug(f"JSON 文件 '{json_file_name}' 的 'date' 字段 '{date_str}' 对于帖子 {post_id} 不是 YYYY-MM-DD HH:MM:%S 格式。")
                        pass
        except json.JSONDecodeError as e:
            logger.warning(f"解析 JSON 文件 '{json_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
        except Exception as e:
            logger.warning(f"读取 JSON 文件 '{json_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
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
                    logger.debug(f"TXT 文件 '{txt_file}' 第一行 '{first_line}' 对于帖子 {post_id} 不是 YYYY-MM-DD HH:MM:%S 格式。")
                    pass
        except Exception as e:
            logger.warning(f"读取或解析 TXT 文件 '{txt_path}' 以获取时间戳 (帖子 {post_id}) 失败: {e}")
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
                logger.debug(f"文件名 '{filename}' 包含无效的 Unix 时间戳 '{ts_str}' (帖子 {post_id}): {e}")
                pass

    # 优先级 4: 文件系统修改时间
    if files_for_post:
        first_file_path = os.path.join(user_folder_path, files_for_post[0])
        try:
            mod_time = os.path.getmtime(first_file_path)
            timestamp = datetime.fromtimestamp(mod_time)
            return timestamp
        except OSError as e:
            logger.warning(f"无法获取文件 '{first_file_path}' 的修改时间 (帖子 {post_id}): {e}")
            pass

    logger.debug(f"未能从任何来源为帖子 {post_id} 确定时间戳。")
    return None
