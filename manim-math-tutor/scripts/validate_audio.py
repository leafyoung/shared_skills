#!/usr/bin/env python3
"""
音频验证脚本

功能：
1. 读取分镜脚本的音频清单部分
2. 验证音频文件存在且时长正常
3. 生成/更新时长信息到JSON
4. 更新分镜脚本的时长列
5. 如果缺少长度或长度异常，报错提醒

使用：
    python validate_audio.py 分镜.md ./audio
"""

import sys
import os
import re
import json
from pathlib import Path


def parse_storyboard(storyboard_path):
    """解析分镜脚本，提取音频清单部分"""
    with open(storyboard_path, 'r', encoding='utf-8') as f:
        content = f.read()

    pattern = r'##\s*音频生成清单.*?(?=##|$)'
    match = re.search(pattern, content, re.DOTALL)

    if not match:
        print("Warning: 未找到音频生成清单部分")
        return [], content

    section = match.group(0)
    lines = section.split('\n')

    audio_list = []
    for line in lines:
        line = line.strip()
        if line.startswith('|') and not line.startswith('|---'):
            parts = [p.strip() for p in line.split('|') if p.strip()]
            if len(parts) >= 2 and parts[0].isdigit():
                scene_num = int(parts[0])
                filename = parts[1] if len(parts) > 1 else ""
                text = parts[2] if len(parts) > 2 else ""
                duration_str = parts[3] if len(parts) > 3 else ""
                speaker = parts[4] if len(parts) > 4 else "xiaoxiao"
                emotion = parts[5] if len(parts) > 5 else "平和"

                duration = None
                if duration_str:
                    try:
                        duration = float(duration_str.replace('s', '').replace('秒', ''))
                    except ValueError:
                        duration = None

                audio_list.append({
                    'scene': scene_num,
                    'file': filename,
                    'text': text,
                    'duration': duration,
                    'speaker': speaker,
                    'emotion': emotion
                })

    return audio_list, content


def get_audio_duration(audio_path):
    """获取音频文件时长（秒）"""
    try:
        from mutagen.mp3 import MP3
        audio = MP3(audio_path)
        return audio.info.length
    except:
        pass

    try:
        from mutagen.wave import WAVE
        audio = WAVE(audio_path)
        return audio.info.length
    except:
        pass

    try:
        import wave
        with wave.open(audio_path, 'rb') as wf:
            frames = wf.getnframes()
            rate = wf.getframerate()
            return frames / float(rate)
    except:
        pass

    try:
        import subprocess
        result = subprocess.run(
            ['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
             '-of', 'default=noprint_wrappers=1:nokey=1', audio_path],
            capture_output=True, text=True
        )
        if result.returncode == 0:
            return float(result.stdout.strip())
    except:
        pass

    return None


def validate_audio_files(audio_list, audio_dir):
    """验证音频文件"""
    errors = []
    updated_list = []
    valid = True

    for item in audio_list:
        scene_num = item['scene']
        filename = item['file']
        audio_path = os.path.join(audio_dir, filename)

        if not os.path.exists(audio_path):
            errors.append(f"❌ 错误：第{scene_num}幕音频文件不存在: {filename}")
            valid = False
            updated_list.append(item)
            continue

        actual_duration = get_audio_duration(audio_path)

        if actual_duration is None:
            errors.append(f"❌ 错误：第{scene_num}幕音频时长获取失败: {filename}")
            valid = False
            updated_list.append(item)
            continue

        if actual_duration <= 0:
            errors.append(f"❌ 错误：第{scene_num}幕音频时长异常({actual_duration:.2f}s): {filename}")
            valid = False
            updated_list.append(item)
            continue

        if actual_duration < 1.0:
            errors.append(f"⚠️ 警告：第{scene_num}幕音频时长过短({actual_duration:.2f}s): {filename}")

        updated_item = item.copy()
        updated_item['duration'] = round(actual_duration, 2)
        updated_list.append(updated_item)

        print(f"✓ 第{scene_num}幕: {filename} - {actual_duration:.2f}s")

    return valid, errors, updated_list


def generate_audio_info_json(updated_list, audio_dir):
    """生成 audio_info.json 文件"""
    output = {
        'files': updated_list,
        'total_duration': sum(item.get('duration', 0) or 0 for item in updated_list),
        'count': len(updated_list)
    }

    output_path = os.path.join(audio_dir, 'audio_info.json')
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n已生成: {output_path}")
    return output_path


def update_storyboard(storyboard_path, original_content, updated_list):
    """更新分镜脚本的时长列"""
    lines = original_content.split('\n')
    new_lines = []

    audio_idx = 0
    in_audio_section = False

    for line in lines:
        if '音频生成清单' in line:
            in_audio_section = True

        if in_audio_section and line.startswith('|') and not line.startswith('|---'):
            parts = [p.strip() for p in line.split('|')]
            parts = [p for p in parts if p]

            if len(parts) >= 2 and parts[0].isdigit() and audio_idx < len(updated_list):
                scene_num = int(parts[0])
                if scene_num == updated_list[audio_idx]['scene']:
                    duration = updated_list[audio_idx].get('duration')
                    if duration is not None:
                        new_parts = parts[:3]
                        new_parts.append(f"{duration:.1f}")
                        if len(parts) > 4:
                            new_parts.append(parts[4])
                        if len(parts) > 5:
                            new_parts.append(parts[5])

                        line = '| ' + ' | '.join(new_parts) + ' |'
                    audio_idx += 1

        new_lines.append(line)

    with open(storyboard_path, 'w', encoding='utf-8') as f:
        f.write('\n'.join(new_lines))

    print(f"已更新: {storyboard_path}")


def main():
    if len(sys.argv) < 2:
        print("Usage: python validate_audio.py <分镜.md> [audio_dir]")
        print("Example: python validate_audio.py 分镜.md ./audio")
        sys.exit(1)

    storyboard_path = sys.argv[1]
    audio_dir = sys.argv[2] if len(sys.argv) > 2 else "./audio"

    if not os.path.exists(storyboard_path):
        print(f"Error: 分镜文件不存在: {storyboard_path}")
        sys.exit(1)

    if not os.path.exists(audio_dir):
        print(f"Error: 音频目录不存在: {audio_dir}")
        sys.exit(1)

    print(f"解析分镜: {storyboard_path}")
    print(f"音频目录: {audio_dir}\n")

    audio_list, original_content = parse_storyboard(storyboard_path)

    if not audio_list:
        print("未找到音频清单，请检查分镜脚本格式")
        sys.exit(1)

    print(f"找到 {len(audio_list)} 个音频条目\n")

    valid, errors, updated_list = validate_audio_files(audio_list, audio_dir)

    if errors:
        print("\n" + "="*50)
        print("验证问题：")
        for error in errors:
            print(error)
        print("="*50)

    if updated_list:
        generate_audio_info_json(updated_list, audio_dir)

    if any(item.get('duration') is not None for item in updated_list):
        update_storyboard(storyboard_path, original_content, updated_list)

    print("\n" + "="*50)
    if valid:
        print("✅ 验证通过！所有音频文件正常。")
        total_duration = sum(item.get('duration', 0) or 0 for item in updated_list)
        print(f"总时长: {total_duration:.1f}秒 ({total_duration/60:.1f}分钟)")
        sys.exit(0)
    else:
        print("❌ 验证失败！请检查上述错误。")
        sys.exit(1)


if __name__ == '__main__':
    main()
