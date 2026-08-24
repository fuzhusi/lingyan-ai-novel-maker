
import os
from app import create_app

app = create_app()

if __name__ == "__main__":
    # debug 模式默认关闭（Werkzeug 调试台存在代码执行风险），需要时显式开启：
    #   set LINGYAN_DEBUG=1
    debug = os.getenv("LINGYAN_DEBUG", "").strip() == "1"
    app.run(debug=True, host="127.0.0.1", port=5000)

