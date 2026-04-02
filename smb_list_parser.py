#!/usr/bin/env python3
import sys
import re
import json

def parse_smbclient_ls(text):
    items = []
    # 匹配格式：行首空白 + 文件名 + 两个以上空白 + 属性字母 + 空白 + 大小 + 空白 + 时间字符串
    pattern = re.compile(r'^\s*(.+?)\s{2,}([DARNHS])\s+(\d+)\s+(.+)$')
    for line in text.splitlines():
        line = line.rstrip('\n')
        # 跳过空行、统计信息行
        if not line or 'blocks of size' in line:
            continue
        m = pattern.match(line)
        if m:
            name = m.group(1).strip()
            attr = m.group(2)
            size_str = m.group(3)
            time_str = m.group(4).strip()
            if name in ('.', '..'):
                continue
            is_dir = (attr == 'D')
            size = int(size_str) if not is_dir else 0
            items.append({
                'name': name,
                'is_dir': is_dir,
                'size': size,
                'mtime': time_str
            })
        else:
            # 如果正则匹配失败，打印到 stderr 便于调试
            sys.stderr.write(f"未匹配行: {line}\n")
    return items

if __name__ == '__main__':
    data = sys.stdin.read()
    result = parse_smbclient_ls(data)
    print(json.dumps(result, indent=2, ensure_ascii=False))