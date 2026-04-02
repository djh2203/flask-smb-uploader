#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
文件上传服务 + NAS 连通性检测
NAS: //192.168.0.7/xsh  用户名 xsh  密码 xsh88888888
"""

import os
import tempfile
import subprocess
import uuid
import time
from flask import Flask, request, jsonify
from werkzeug.utils import secure_filename

app = Flask(__name__)

# ---------- NAS 连通性检测缓存 ----------
_nas_status_cache = {
    "last_check": 0,      # 上次检测的时间戳（秒）
    "status": None,       # "ok" 或 "error"
    "message": None       # 详细信息
}
CACHE_TTL = 10            # 缓存有效期 10 秒




def check_nas_connectivity():
    """
    检测 NAS Samba 共享是否可访问。
    使用 smbclient 执行 'ls' 命令，超时 5 秒。
    返回 (status, message)
    """
    cmd = [
        "smbclient",
        "//192.168.0.7/xsh",
        "-U", "xsh%xsh88888888",
        "-c", "ls"          # 轻量级命令，仅列出根目录
    ]
    try:
        # 执行命令，设置超时 5 秒，捕获 stdout/stderr
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        # 检查返回码和错误信息
        if result.returncode == 0:
            # 进一步检查输出中是否包含 NT_STATUS_ 错误（某些情况返回码可能为0但实际有错误）
            stderr_lower = result.stderr.lower()
            if "nt_status" in stderr_lower or "error" in stderr_lower:
                return "error", f"NAS 响应异常: {result.stderr.strip()}"
            return "ok", "NAS 可访问"
        else:
            # 返回码非0，提取错误信息
            error_msg = result.stderr.strip() or result.stdout.strip() or "未知错误"
            return "error", f"连接失败: {error_msg}"
    except subprocess.TimeoutExpired:
        return "error", "连接超时（5秒）"
    except FileNotFoundError:
        return "error", "未安装 smbclient 命令，请先安装: pkg install smbclient (Termux) 或 apt install smbclient"
    except Exception as e:
        return "error", f"检测异常: {str(e)}"

@app.route('/check_nas', methods=['GET'])
def check_nas():
    """前端调用此接口获取 NAS 连通性状态（JSON 格式）"""
    global _nas_status_cache
    now = time.time()
    # 如果缓存未过期，直接返回缓存结果
    if (now - _nas_status_cache["last_check"]) < CACHE_TTL:
        return jsonify({
            "status": _nas_status_cache["status"],
            "message": _nas_status_cache["message"]
        })
    # 否则重新检测
    status, message = check_nas_connectivity()
    # 更新缓存
    _nas_status_cache = {
        "last_check": now,
        "status": status,
        "message": message
    }
    return jsonify({
        "status": status,
        "message": message
    })

# ---------- 原有上传功能 ----------
# 注意：upload.html 文件需要放在同级目录下
@app.route('/')
def index():
    # 假设 upload.html 已存在，且内容不变
    with open('upload.html', 'r', encoding='utf-8') as f:
        return f.read()


@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return "没有文件"
    file = request.files['file']
    if not file.filename:
        return "文件名为空"
    
    safe_filename = secure_filename(file.filename)
    unique_id = uuid.uuid4().hex[:8]
    temp_filename = f"{unique_id}_{safe_filename}"
    temp_path = os.path.join(tempfile.gettempdir(), temp_filename)
    
    try:
        file.save(temp_path)
        
        # 上传到 NAS
        cmd_put = [
            "smbclient", "//192.168.0.7/xsh",
            "-U", "xsh%xsh88888888",
            "-c", f"put {temp_path} {safe_filename}"
        ]
        result = subprocess.run(cmd_put, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            return f"上传失败（smbclient 错误）：{result.stderr}"
        
        # 可选：快速检查文件是否存在（不检查大小）
        cmd_check = [
            "smbclient", "//192.168.0.7/xsh",
            "-U", "xsh%xsh88888888",
            "-c", f"ls {safe_filename}"
        ]
        check_result = subprocess.run(cmd_check, capture_output=True, text=True, timeout=5)
        if check_result.returncode == 0 and safe_filename in check_result.stdout:
            return f"上传成功！文件：{safe_filename} 已保存到 NAS。"
        else:
            # 虽然 put 返回成功，但 ls 找不到文件（极少发生），提示用户手动确认
            return f"上传命令执行成功，但无法确认文件是否存在，请手动检查 NAS 共享。文件：{safe_filename}"
            
    except Exception as e:
        return f"上传过程出错：{str(e)}"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
if __name__ == '__main__':
    # 确保 upload.html 存在，如果不存在则创建默认内容（可选）
    if not os.path.exists('upload.html'):
        with open('upload.html', 'w', encoding='utf-8') as f:
            f.write('''<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="file" name="file" required />
  <button type="submit">上传</button>
</form>''')
    app.run(host='0.0.0.0', port=5000, debug=False)