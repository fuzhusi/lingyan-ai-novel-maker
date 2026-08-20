"""文件上传处理 — 支持 TXT/DOCX/EPUB。"""
import os
from flask import request, jsonify
from werkzeug.utils import secure_filename
from app.models import db, PlagiarizeTask
from app.routes.plagiarize import plagiarize_bp

UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "uploads")
ALLOWED_EXTENSIONS = {"txt", "docx", "epub"}


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text_from_txt(filepath):
    """从 TXT 文件提取文本"""
    encodings = ["utf-8", "gbk", "gb2312", "latin-1"]
    for encoding in encodings:
        try:
            with open(filepath, "r", encoding=encoding) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    return ""


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
def upload_file():
    """上传文件并提取文本"""
    if "file" not in request.files:
        return jsonify({"error": "没有文件"}), 400
    
    file = request.files["file"]
    if file.filename == "":
        return jsonify({"error": "未选择文件"}), 400
    
    if not allowed_file(file.filename):
        return jsonify({"error": "不支持的文件格式，请上传 TXT/DOCX/EPUB"}), 400
    
    # 确保上传目录存在
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    
    filename = secure_filename(file.filename)
    filepath = os.path.join(UPLOAD_DIR, filename)
    file.save(filepath)
    
    # 提取文本
    ext = filename.rsplit(".", 1)[1].lower()
    if ext == "txt":
        text = extract_text_from_txt(filepath)
    elif ext == "docx":
        text = extract_text_from_docx(filepath)
    elif ext == "epub":
        text = extract_text_from_epub(filepath)
    else:
        text = ""
    
    # 清理临时文件
    try:
        os.remove(filepath)
    except Exception:
        pass
    
    if not text:
        return jsonify({"error": "无法提取文件内容"}), 400
    
    # 创建任务
    task_id = request.form.get("task_id")
    if task_id:
        task = PlagiarizeTask.query.get(task_id)
        if task:
            task.source_text = text
            task.source_filename = filename
            db.session.commit()
            return jsonify({"ok": True, "task_id": task.id, "length": len(text)})
    
    # 创建新任务
    task = PlagiarizeTask(
        mode=request.form.get("mode", "rewrite"),
        source_text=text,
        source_filename=filename,
        status="pending",
    )
    db.session.add(task)
    db.session.commit()
    
    return jsonify({"ok": True, "task_id": task.id, "length": len(text)})
