"""文件上传处理 — 支持 TXT/DOCX/EPUB。"""
import os
import uuid
from flask import request, jsonify
from werkzeug.utils import secure_filename
from app.models import db, PlagiarizeTask
from app.routes.auth import login_required
from app.routes.plagiarize import plagiarize_bp

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
ALLOWED_EXTENSIONS = {"txt", "docx", "epub"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def _check_zip_safety(filepath, max_total=200 * 1024 * 1024, max_ratio=200):
    """DOCX/EPUB 本质是 zip:校验解压后总量与压缩比,防解压炸弹(P1-1)。"""
    import zipfile
    with zipfile.ZipFile(filepath) as zf:
        total = sum(i.file_size for i in zf.infolist())
        comp = sum(i.compress_size for i in zf.infolist()) or 1
    if total > max_total:
        raise ValueError(f"文件解压后过大（{total // 1024 // 1024}MB），已拒绝处理")
    if total / comp > max_ratio:
        raise ValueError("文件压缩比异常，疑似解压炸弹，已拒绝处理")


def extract_text_from_txt(filepath):
    """从 TXT 文件提取文本（BOM 检测优先，避免 UTF-16 被 latin-1 兜底读成乱码）。"""
    with open(filepath, "rb") as f:
        raw = f.read()
    # BOM 检测
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        return raw.decode("utf-16", errors="replace")
    for encoding in ["utf-8", "gbk", "gb2312"]:
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def extract_text_from_docx(filepath):
    """从 DOCX 文件提取文本"""
    try:
        from docx import Document
        doc = Document(filepath)
        return "\n\n".join(para.text for para in doc.paragraphs if para.text.strip())
    except Exception:
        return ""


def extract_text_from_epub(filepath):
    """从 EPUB 文件提取文本"""
    try:
        from ebooklib import epub
        from bs4 import BeautifulSoup
        book = epub.read_epub(filepath)
        texts = []
        for item in book.get_items():
            if item.get_type() == 9:  # ITEM_DOCUMENT
                soup = BeautifulSoup(item.get_content(), "html.parser")
                text = soup.get_text(separator="\n", strip=True)
                if text:
                    texts.append(text)
        return "\n\n".join(texts)
    except Exception:
        return ""


@plagiarize_bp.route("/upload", methods=["POST"])
@login_required
def upload_file():
    """上传文件并提取文本"""
    if "file" not in request.files:
        return jsonify({"error": "没有文件"}), 400

    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "未选择文件"}), 400

    # 先用原始名做扩展名校验（仅判断类型），存储名一律用 uuid + 扩展名：
    # 1) 纯中文文件名经 secure_filename 会退化成无扩展名的裸串，后续 rsplit 直接 IndexError
    # 2) 固定/可预测的存储名会互相覆盖并在异常时永久残留
    original_name = file.filename
    if not allowed_file(original_name):
        return jsonify({"error": "不支持的文件格式，请上传 TXT/DOCX/EPUB"}), 400

    ext = original_name.rsplit(".", 1)[1].lower()
    display_name = secure_filename(original_name) or f"upload.{ext}"
    stored_name = uuid.uuid4().hex + "." + ext

    os.makedirs(UPLOAD_DIR, exist_ok=True)
    filepath = os.path.join(UPLOAD_DIR, stored_name)

    try:
        file.save(filepath)
        if ext in ("docx", "epub"):
            try:
                _check_zip_safety(filepath)
            except ValueError as e:
                return jsonify({"error": str(e)}), 400
        if ext == "txt":
            text = extract_text_from_txt(filepath)
        elif ext == "docx":
            text = extract_text_from_docx(filepath)
        elif ext == "epub":
            text = extract_text_from_epub(filepath)
        else:
            text = ""
    finally:
        # 无论解析成败都清理临时文件
        try:
            os.remove(filepath)
        except OSError:
            pass

    if not text:
        return jsonify({"error": "无法提取文件内容"}), 400

    # 创建任务
    task_id = request.form.get("task_id", type=int)
    if task_id:
        task = db.session.get(PlagiarizeTask, task_id)
        if task:
            task.source_text = text
            task.source_filename = display_name
            task.source_type = "upload"
            # 换源后旧拆解产物全部失效，清空待重拆（条目保留由用户自行丢弃）
            task.chapters_summary_json = "[]"
            task.volumes_summary_json = "[]"
            task.elements_json = "[]"
            task.report_text = ""
            task.status = "pending"
            db.session.commit()
            return jsonify({"ok": True, "task_id": task.id, "length": len(text)})

    # 创建新任务
    task = PlagiarizeTask(
        mode="deconstruct",
        title=request.form.get("title", "").strip() or "未命名对标书",
        source_text=text,
        source_filename=display_name,
        source_type="upload",
        modifications_text=request.form.get("modifications_text", ""),  # 修复:上传不再丢弃微创新方向
        status="pending",
    )
    db.session.add(task)
    db.session.commit()

    return jsonify({"ok": True, "task_id": task.id, "length": len(text)})
