"""
openremote CLI 入口
安装后通过命令行输入 `ocr` 启动服务
"""

import argparse
import os
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="ocr",
        description="Opencode Remote - 启动 Opencode API Gateway 服务",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="绑定的主机地址 (默认: 0.0.0.0)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="绑定的端口 (默认: 8000)",
    )
    parser.add_argument(
        "--reload",
        action="store_true",
        help="启用热重载（开发模式）",
    )

    args = parser.parse_args()

    print(f"Opencode API Gateway 启动中...")
    print(f"地址: http://{args.host}:{args.port}")
    print(f"文档: http://{args.host}:{args.port}/docs")
    print()

    import uvicorn
    from .api import app

    uvicorn.run(app, host=args.host, port=args.port, reload=args.reload)


if __name__ == "__main__":
    main()
