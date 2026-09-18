#!/usr/bin/env python3
"""
Manim 教学视频渲染脚本
完整流程: 检查代码 -> 渲染视频

使用方法:
    python scripts/render.py [options]

选项:
    -f, --file      指定脚本文件 (默认: script.py)
    -s, --scene     指定场景类名 (默认: MathScene)
    -q, --quality   渲染质量: l(ow)/m(edium)/h(igh)/k(4k) (默认: high)
    -p, --preview   渲染后预览 (默认: 开启)
    --no-check      跳过代码检查 (不推荐)
"""

import subprocess
import sys
import argparse
from pathlib import Path


class RenderPipeline:
    """渲染流水线"""

    QUALITY_MAP = {
        'l': '480p15',
        'low': '480p15',
        'm': '720p30',
        'medium': '720p30',
        'h': '1080p60',
        'high': '1080p60',
        'k': '2160p60',
        '4k': '2160p60',
    }

    def __init__(self, script_file='script.py', scene_name='MathScene',
                 quality='high', preview=True, skip_check=False):
        self.script_file = Path(script_file)
        self.scene_name = scene_name
        self.quality = self.QUALITY_MAP.get(quality, '1080p60')
        self.preview = preview
        self.skip_check = skip_check

        self.script_dir = Path(__file__).parent.parent
        self.check_script = self.script_dir / 'scripts' / 'check.py'

    def run_check(self):
        """第一步: 运行代码检查"""
        if self.skip_check:
            print("⚠️  跳过代码检查 (不推荐)")
            return True

        print("🔍 步骤 1/2: 代码结构检查")
        print("=" * 50)

        if not self.check_script.exists():
            print(f"❌ 检查脚本不存在: {self.check_script}")
            return False

        try:
            result = subprocess.run(
                [sys.executable, str(self.check_script), str(self.script_file)],
                cwd=self.script_dir,
                capture_output=False
            )
            return result.returncode == 0
        except Exception as e:
            print(f"❌ 检查失败: {e}")
            return False

    def run_render(self):
        """第二步: 运行 Manim 渲染"""
        print("\n🎬 步骤 2/2: 渲染视频")
        print("=" * 50)

        if not self.script_file.exists():
            print(f"❌ 脚本文件不存在: {self.script_file}")
            return False

        cmd = ['manim']
        cmd.extend(['-q', self.quality[0]])

        if self.preview:
            cmd.append('-p')

        cmd.extend([str(self.script_file), self.scene_name])

        print(f"执行命令: {' '.join(cmd)}")
        print()

        try:
            result = subprocess.run(cmd, cwd=self.script_dir)
            return result.returncode == 0
        except FileNotFoundError:
            print("❌ 未找到 manim 命令，请确保已安装: pip install manim")
            return False
        except Exception as e:
            print(f"❌ 渲染失败: {e}")
            return False

    def copy_to_root(self):
        """第三步: 拷贝视频到根目录"""
        print("\n📁 拷贝视频到根目录")
        print("=" * 50)

        media_dir = self.script_dir / 'media' / 'videos' / self.script_file.stem

        if not media_dir.exists():
            print(f"⚠️  媒体目录不存在: {media_dir}")
            return

        possible_paths = [
            media_dir / '2160p60' / f'{self.scene_name}.mp4',
            media_dir / '1920p60' / f'{self.scene_name}.mp4',
            media_dir / '1080p60' / f'{self.scene_name}.mp4',
            media_dir / '720p30' / f'{self.scene_name}.mp4',
            media_dir / '480p15' / f'{self.scene_name}.mp4',
        ]

        video_src = None
        for path in possible_paths:
            if path.exists():
                video_src = path
                break

        if video_src:
            import shutil
            video_dst = self.script_dir / f'{self.scene_name}.mp4'
            try:
                shutil.copy2(video_src, video_dst)
                print(f"✅ 视频已拷贝: {video_dst}")
                print(f"   源文件: {video_src}")
            except Exception as e:
                print(f"⚠️  拷贝失败: {e}")
        else:
            print("⚠️  未找到生成的视频文件")

    def run(self):
        """运行完整流程"""
        print("\n" + "=" * 50)
        print("🎬 Manim 教学视频渲染流水线")
        print("=" * 50)
        print(f"脚本文件: {self.script_file}")
        print(f"场景类名: {self.scene_name}")
        print(f"渲染质量: {self.quality}")
        print("=" * 50 + "\n")

        if not self.run_check():
            print("\n⛔ 代码检查失败，终止渲染。")
            print("   请修复错误后重试，或使用 --no-check 跳过检查（不推荐）")
            return False

        if not self.run_render():
            print("\n⛔ 渲染失败。")
            return False

        self.copy_to_root()

        print("\n" + "=" * 50)
        print("✅ 渲染完成！")
        print("=" * 50)

        return True


def main():
    """主函数"""
    parser = argparse.ArgumentParser(
        description='Manim 教学视频渲染流水线',
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument('-f', '--file', default='script.py',
                        help='要渲染的脚本文件 (默认: script.py)')
    parser.add_argument('-s', '--scene', default='MathScene',
                        help='场景类名 (默认: MathScene)')
    parser.add_argument('-q', '--quality', default='high',
                        choices=['l', 'low', 'm', 'medium', 'h', 'high', 'k', '4k'],
                        help='渲染质量 (默认: high)')
    parser.add_argument('-p', '--preview', action='store_true', default=True,
                        help='渲染后预览 (默认: 开启)')
    parser.add_argument('--no-preview', action='store_true',
                        help='渲染后不预览')
    parser.add_argument('--no-check', action='store_true',
                        help='跳过代码检查 (不推荐)')

    args = parser.parse_args()

    preview = not args.no_preview

    pipeline = RenderPipeline(
        script_file=args.file,
        scene_name=args.scene,
        quality=args.quality,
        preview=preview,
        skip_check=args.no_check
    )

    success = pipeline.run()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
