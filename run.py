"""本地启动入口。

开发期：python run.py
默认监听 127.0.0.1:5000，浏览器访问 http://127.0.0.1:5000/
"""

import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="127.0.0.1", port=int(os.environ.get("PORT", 5000)), debug=debug)
