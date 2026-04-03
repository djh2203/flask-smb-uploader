# file_validator.py
import os
import subprocess
import json
from flask import current_app

def load_rules(config_path='upload_rules.json'):
    with open(config_path, 'r', encoding='utf-8') as f:
        return json.load(f)

def validate_filename(filename, forbidden_chars):
    for ch in forbidden_chars:
        if ch in filename:
            return False, f"文件名不能包含字符: {ch}"
    return True, ""

def check_file_exists(remote_filename, nas_config, share_root='/'):
    # 使用 smbclient ls 检查文件是否存在
    cmd = [
        "smbclient", f"//{nas_config['ip']}/{nas_config['share']}",
        "-U", f"{nas_config['username']}%{nas_config['password']}",
        "-c", f'ls "{remote_filename}"'
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
    # 如果 ls 输出包含文件名且返回码为0，则认为存在
    return result.returncode == 0 and remote_filename in result.stdout

def validate_file_size(file_storage, max_size_mb):
    # 注意：file_storage.content_length 可能为 None（分块上传），可读取流
    file_storage.seek(0, os.SEEK_END)
    size = file_storage.tell()
    file_storage.seek(0)  # 重置指针
    max_bytes = max_size_mb * 1024 * 1024
    if size > max_bytes:
        return False, f"文件大小超过 {max_size_mb} MB"
    return True, ""

def validate_extension(filename, allowed_extensions):
    ext = os.path.splitext(filename)[1].lower()
    if ext not in allowed_extensions:
        return False, f"不支持的文件类型，允许的类型: {', '.join(allowed_extensions)}"
    return True, ""

def validate_upload(file, nas_config, rules=None):
    if rules is None:
        rules = load_rules()
    filename = file.filename
    if not filename:
        return False, "文件名为空"
    # 1. 非法字符
    ok, msg = validate_filename(filename, rules['forbidden_chars'])
    if not ok:
        return False, msg
    # 2. 扩展名
    ok, msg = validate_extension(filename, rules['allowed_extensions'])
    if not ok:
        return False, msg
    # 3. 文件大小
    ok, msg = validate_file_size(file, rules['max_size_mb'])
    if not ok:
        return False, msg
    # 4. 同名文件检查（需要网络，可能耗时）
    ok = check_file_exists(filename, nas_config)
    if ok:
        return False, f"文件 '{filename}' 已在 NAS 上存在，请重命名后上传"
    return True, "校验通过"