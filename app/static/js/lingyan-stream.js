/* 灵砚 · 共享流式读取工具 (lingyan-stream.js)
 *
 * 统一两种线格式，供各写作页复用：
 *  - raw 纯文本流：短篇链路（/short/{id}/generate 等），响应体就是逐段正文
 *  - SSE 分帧流：长篇链路（/api/generate-stream 等），data: {json}\n\n 事件
 *
 * 页面只需传少量回调（字数刷新 / 草稿键 / 节点标记），管道与错误处理集中在此。
 */
(function () {
    'use strict';

    function openStream(url, body, signal) {
        return fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
            body: body || '',
            signal: signal,
        }).then(function (resp) {
            if (!resp.ok) {
                return resp.text().then(function (t) {
                    throw new Error(t || ('HTTP ' + resp.status));
                });
            }
            return resp;
        });
    }

    var LingyanStream = {

        /* ===== raw 流 → 渲染到元素（含 ===NODE:id:title=== 标记处理）=====
         * 返回 AbortController（页面用其 abort() 实现「暂停生成」）。
         * opts:
         *   initial   —— 起始已有文本（默认空）
         *   onCount(t) —— 每帧刷新字数统计
         *   draftKey   —— 完成后清除的本地草稿键（可选）
         *   onNode(id, title, cleanLen) —— 遇到节点标记时回调
         *   onAbort(t) / onError(err) —— 用户暂停 / 网络失败
         */
        toElement: function (url, body, targetEl, onDone, opts) {
            opts = opts || {};
            var controller = new AbortController();
            var NODE_RE = /===NODE:(\d+):(.*?)===/g;

            var initialText = opts.initial || '';
            targetEl.style.display = 'block';
            targetEl.innerHTML = '';
            // textNode + 光标分离渲染，避免整块 innerHTML 重绘
            var textNode = document.createTextNode(initialText);
            var cursor = document.createElement('span');
            cursor.className = 'typing-cursor';
            cursor.textContent = '|';
            targetEl.appendChild(textNode);
            targetEl.appendChild(cursor);

            var rawText = initialText;      // 含节点标记的原文
            var displayText = initialText;  // 剔除节点标记后展示

            function handleNodeMarkers() {
                NODE_RE.lastIndex = 0;
                var m;
                while ((m = NODE_RE.exec(rawText)) !== null) {
                    var cleanBefore = rawText.slice(0, m.index)
                        .replace(/===NODE:\d+:.*?===/g, '');
                    if (opts.onNode) opts.onNode(parseInt(m[1], 10), m[2].trim(), cleanBefore.length);
                }
                displayText = rawText.replace(/===NODE:\d+:.*?===/g, '');
            }

            openStream(url, body, controller.signal).then(function (resp) {
                var reader = resp.body.getReader();
                var decoder = new TextDecoder();

                function read() {
                    reader.read().then(function (r) {
                        if (r.done) {
                            cursor.remove();
                            textNode.textContent = displayText;
                            if (onDone) onDone(displayText);
                            if (opts.draftKey) localStorage.removeItem(opts.draftKey);
                            return;
                        }
                        rawText += decoder.decode(r.value, { stream: true });
                        handleNodeMarkers();
                        textNode.textContent = displayText;
                        if (opts.onCount) opts.onCount(displayText);
                        targetEl.scrollTop = targetEl.scrollHeight;
                        read();
                    }).catch(function (err) {
                        cursor.remove();
                        if (err.name === 'AbortError') {
                            // 用户暂停：保留已生成文本
                            textNode.textContent = displayText;
                            if (opts.onAbort) opts.onAbort(displayText);
                        } else {
                            var p = document.createElement('p');
                            p.style.color = 'var(--danger)';
                            p.textContent = '失败: ' + err.message;
                            targetEl.appendChild(p);
                            if (opts.onError) opts.onError(err);
                        }
                    });
                }
                read();
            }).catch(function (err) {
                if (err.name === 'AbortError') {
                    if (opts.onAbort) opts.onAbort(displayText);
                    return;
                }
                targetEl.innerHTML = '';
                var p = document.createElement('p');
                p.style.color = 'var(--danger)';
                p.textContent = '失败: ' + err.message;
                targetEl.appendChild(p);
                if (opts.onError) opts.onError(err);
            });

            return controller;
        },

        /* ===== raw 流 → 追加到 textarea（续写用）===== 返回 AbortController */
        toEditor: function (url, body, editor, onDone, opts) {
            opts = opts || {};
            var controller = new AbortController();
            var startLen = editor.value.length;

            openStream(url, body, controller.signal).then(function (resp) {
                var reader = resp.body.getReader();
                var decoder = new TextDecoder();
                var acc = '';
                (function read() {
                    reader.read().then(function (r) {
                        if (r.done) { if (onDone) onDone(acc); return; }
                        acc += decoder.decode(r.value, { stream: true });
                        editor.value = editor.value.slice(0, startLen) + acc;
                        editor.scrollTop = editor.scrollHeight;
                        if (opts.onCount) opts.onCount(editor.value);
                        read();
                    }).catch(function (err) {
                        if (err.name !== 'AbortError') {
                            editor.value += '\n[失败: ' + err.message + ']';
                        }
                    });
                })();
            }).catch(function (err) {
                if (err.name !== 'AbortError') {
                    editor.value += '\n[失败: ' + err.message + ']';
                }
            });

            return controller;
        },

        /* ===== raw 流 → 收集到变量（扩写/局部重写，完成后整体替换选区）===== 返回 AbortController */
        collect: function (url, body, onToken, onDone, onErr) {
            var controller = new AbortController();

            openStream(url, body, controller.signal).then(function (resp) {
                var reader = resp.body.getReader();
                var decoder = new TextDecoder();
                var acc = '';
                (function read() {
                    reader.read().then(function (r) {
                        if (r.done) { if (onDone) onDone(acc); return; }
                        acc += decoder.decode(r.value, { stream: true });
                        if (onToken) onToken(acc);
                        read();
                    }).catch(function (err) {
                        if (err.name === 'AbortError') return;
                        if (onErr) onErr(err.message);
                    });
                })();
            }).catch(function (err) {
                if (err.name !== 'AbortError' && onErr) onErr(err.message);
            });

            return controller;
        },

        /* ===== SSE 分帧流（长篇链路专用）=====
         * handlers:
         *   onToken(token)     —— 正文 token
         *   onApiError(msg)    —— 服务端业务错误（计入最终 throw）
         *   signal             —— 可选 AbortSignal（暂停用）
         *
         * 服务端事件形如 data: {"token":"..."}\n\n；按行解析，
         * 未收完整的一帧留在 buffer 等下一个 chunk 拼齐。
         * 任意服务端 error 事件后：循环走完抛出该错误。
         * （历史事故：主题换装提交曾把 '\n' 吃成字面 n，导致长篇流式静默全灭）
         */
        sse: function (url, formData, handlers) {
            handlers = handlers || {};

            return (async function () {
                var resp = await fetch(url, { method: 'POST', body: formData, signal: handlers.signal });
                if (!resp.ok) throw new Error('HTTP ' + resp.status);
                var reader = resp.body.getReader();
                var decoder = new TextDecoder();
                var buffer = '';
                var errorMsg = '';
                while (true) {
                    var r = await reader.read();
                    if (r.done) break;
                    buffer += decoder.decode(r.value, { stream: true });
                    var lines = buffer.split('\n');
                    buffer = lines.pop() || '';
                    for (var i = 0; i < lines.length; i++) {
                        var line = lines[i];
                        if (!line.startsWith('data: ')) continue;
                        try {
                            var data = JSON.parse(line.slice(6));
                            if (data.token && handlers.onToken) handlers.onToken(data.token);
                            if (data.error) {
                                errorMsg = data.error;
                                if (handlers.onApiError) handlers.onApiError(data.error);
                            }
                            if (data.done) return;
                        } catch (e) { /* 跨 chunk 半帧，忽略 */ }
                    }
                }
                if (errorMsg) throw new Error(errorMsg);
            })();
        }
    };

    window.LingyanStream = LingyanStream;
})();
