
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug 模式默认关闭（Werkzeug 调试台存在代码执行风险），需要时显式开启：
    #   set LINGYAN_DEBUG=1
    # 生产形态优先 waitress（Windows 友好的生产级 WSGI,多线程）
    debug = os.getenv("LINGYAN_DEBUG", "").strip() == "1"
    if debug:
        app.run(debug=True, use_reloader=True, host="127.0.0.1", port=5000)
    else:
        try:
            from waitress import serve
            serve(app, host="127.0.0.1", port=5000, threads=8)
        except ImportError:
            app.run(debug=False, host="127.0.0.1", port=5000)

