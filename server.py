#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import tempfile
import subprocess
import uuid
import time
import json
from flask import Flask, request, jsonify, send_file, after_this_request
from werkzeug.utils import secure_filename
from smb_list_parser import parse_smbclient_ls

# ---------- 加载配置 ----------
CONFIG_FILE = "config.json"

def load_config():
    if not os.path.exists(CONFIG_FILE):
        raise FileNotFoundError(f"配置文件 {CONFIG_FILE} 不存在，请创建它。")
    with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
        return json.load(f)

config = load_config()
NAS_CONFIG = config["nas"]
CACHE_TTL = config.get("cache_ttl", 10)   # 从配置文件读取缓存有效期

app = Flask(__name__)

# ---------- NAS 连通性检测缓存 ----------
_nas_status_cache = {
    "last_check": 0,
    "status": None,
    "message": None
}

def check_nas_connectivity():
    """
    检测 NAS Samba 共享是否可访问。
    使用 smbclient 执行 'ls' 命令，超时 5 秒。
    返回 (status, message)
    """
    cmd = [
        "smbclient", f"//{NAS_CONFIG['ip']}/{NAS_CONFIG['share']}",
        "-U", f"{NAS_CONFIG['username']}%{NAS_CONFIG['password']}",
        "-c", "ls"
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            stderr_lower = result.stderr.lower()
            if "nt_status" in stderr_lower or "error" in stderr_lower:
                return "error", f"NAS 响应异常: {result.stderr.strip()}"
            return "ok", "NAS 可访问"
        else:
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
    # 使用从配置文件读取的 CACHE_TTL
    if (now - _nas_status_cache["last_check"]) < CACHE_TTL:
        return jsonify({
            "status": _nas_status_cache["status"],
            "message": _nas_status_cache["message"]
        })
    # 否则重新检测
    status, message = check_nas_connectivity()
    _nas_status_cache = {
        "last_check": now,
        "status": status,
        "message": message
    }
    return jsonify({
        "status": status,
        "message": message
    })

# ---------- 首页 ----------
@app.route('/')
def index():
    with open('upload.html', 'r', encoding='utf-8') as f:
        return f.read()

# ---------- 文件列表 API ----------
@app.route('/api/list', methods=['GET'])
def list_nas_directory():
    req_path = request.args.get('path', '/')
    req_path = req_path.strip()
    if req_path == '/' or req_path == '':
        cd_path = '.'
    else:
        cd_path = req_path.lstrip('/')
    
    if '..' in cd_path or cd_path.startswith('/'):
        return jsonify({"status": "error", "message": "非法路径"}), 400
    
    cmd = [
        "smbclient", f"//{NAS_CONFIG['ip']}/{NAS_CONFIG['share']}",
        "-U", f"{NAS_CONFIG['username']}%{NAS_CONFIG['password']}",
        "-c", f'cd "{cd_path}"; ls'
    ]
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        if result.returncode != 0:
            return jsonify({
                "status": "error",
                "message": f"smbclient 错误 (code {result.returncode}): {result.stderr.strip()}"
            }), 500
        
        items = parse_smbclient_ls(result.stdout)
        return jsonify({
            "status": "ok",
            "path": f"/{req_path}" if req_path and req_path != '/' else "/",
            "items": items
        })
    except subprocess.TimeoutExpired:
        return jsonify({"status": "error", "message": "连接超时"}), 500
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500

# ---------- 上传文件 ----------
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
        
        cmd_put = [
            "smbclient", f"//{NAS_CONFIG['ip']}/{NAS_CONFIG['share']}",
            "-U", f"{NAS_CONFIG['username']}%{NAS_CONFIG['password']}",
            "-c", f"put {temp_path} {safe_filename}"
        ]
        result = subprocess.run(cmd_put, capture_output=True, text=True, timeout=60)
        
        if result.returncode != 0:
            return f"上传失败（smbclient 错误）：{result.stderr}"
        
        # 可选：快速检查文件是否存在
        cmd_check = [
            "smbclient", f"//{NAS_CONFIG['ip']}/{NAS_CONFIG['share']}",
            "-U", f"{NAS_CONFIG['username']}%{NAS_CONFIG['password']}",
            "-c", f'ls "{safe_filename}"'   # 添加双引号
        ]
        check_result = subprocess.run(cmd_check, capture_output=True, text=True, timeout=5)
        if check_result.returncode == 0 and safe_filename in check_result.stdout:
            return f"上传成功！文件：{safe_filename} 已保存到 NAS。"
        else:
            return f"上传命令执行成功，但无法确认文件是否存在，请手动检查 NAS 共享。文件：{safe_filename}"
    except Exception as e:
        return f"上传过程出错：{str(e)}"
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

@app.route('/download', methods=['GET'])
def download_file():
    file_path = request.args.get('path', '')
    if not file_path or '..' in file_path:
        return "非法路径", 400
    # 去除开头的 /
    remote_path = file_path.lstrip('/')
    fd, local_temp = tempfile.mkstemp()
    os.close(fd)
    cmd = [
        "smbclient", f"//{NAS_CONFIG['ip']}/{NAS_CONFIG['share']}",
        "-U", f"{NAS_CONFIG['username']}%{NAS_CONFIG['password']}",
        "-c", f'get "{remote_path}" "{local_temp}"'
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        if result.returncode != 0:
            os.unlink(local_temp)
            return f"下载失败：{result.stderr}", 500
        return send_file(local_temp, as_attachment=True, download_name=os.path.basename(remote_path))
    except Exception as e:
        return f"错误：{str(e)}", 500
    finally:
        @after_this_request
        def cleanup(response):
            try:
                os.unlink(local_temp)
            except:
                pass
            return response

# ---------- 启动服务 ----------
if __name__ == '__main__':
    if not os.path.exists('upload.html'):
        with open('upload.html', 'w', encoding='utf-8') as f:
            f.write('''<form action="/upload" method="post" enctype="multipart/form-data">
  <input type="file" name="file" required />
  <button type="submit">上传</button>
</form>''')
    app.run(host='0.0.0.0', port=5000, debug=False)