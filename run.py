
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
            # 打印访问地址：waitress 自己的 "Serving on" 提示走日志系统
            # （收进 logs/lingyan.log），控制台看不到，容易误以为卡住
            print(" * Running on http://127.0.0.1:5000  (Ctrl+C 退出)")
            serve(app, host="127.0.0.1", port=5000, threads=8)
        except ImportError:
            # waitress 是声明过的依赖，正常安装不会走到这里；
            # Werkzeug 必须开 threaded，否则任一 SSE 长连接会阻塞全站
            print(" * WARNING: waitress not installed, falling back to "
                  "Werkzeug dev server (threaded=True)")
            app.run(debug=False, host="127.0.0.1", port=5000, threaded=True)

