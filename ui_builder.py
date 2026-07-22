import json
from datetime import datetime
from config import log_msg, BOARD_MAP, MAX_POSTS_TO_SYNC_COMMENTS
from storage import load_keywords_from_file, load_board_config

def generate_multiboard_html(all_keywords_data, output_file):
    log_msg("HTML 정적 대시보드 파일 템플릿 컴파일 빌드를 시작합니다.", "DEBUG")
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    tabs_html = ""
    boards_html = ""
    
    active_config = load_keywords_from_file()
    board_alert_config = load_board_config()
    
    flattened_keywords = []
    for board, keywords in active_config.items():
        for keyword in keywords:
            combined_key = f"{board}::{keyword}"
            board_data = all_keywords_data.get(combined_key, [])
            
            new_posts_count = sum(1 for post in board_data if post.get('is_new', False))
            
            latest_post_date = ""
            if board_data and len(board_data) > 0:
                latest_post_date = board_data[0].get('date', '')
            
            flattened_keywords.append({
                'board': board,
                'keyword': keyword,
                'combined_key': combined_key,
                'board_data': board_data,
                'new_posts_count': new_posts_count,
                'total_count': len(board_data),
                'latest_post_date': latest_post_date
            })
    
    flattened_keywords.sort(
        key=lambda x: (
            x['new_posts_count'] > 0, 
            x['latest_post_date'], 
            x['total_count']
        ), 
        reverse=True
    )
    
    js_tab_meta_json = {}
    
    for global_idx, item in enumerate(flattened_keywords):
        board = item['board']
        keyword = item['keyword']
        board_data = item['board_data']
        new_posts_count = item['new_posts_count']
        
        board_name = BOARD_MAP.get(board, board)
        active_class = "active" if global_idx == 0 else ""
        display_style = "block" if global_idx == 0 else "none"
        
        js_tab_meta_json[f"board-{global_idx}"] = [p['id'] for p in board_data if p.get('is_new', False)]
        
        new_tag_in_tab = f'<span class="new-dot" id="dot-board-{global_idx}">🔴 </span>' if new_posts_count > 0 else f'<span class="new-dot" id="dot-board-{global_idx}" style="display:none;">🔴 </span>'
        
        tab_clean_text = f"[{board_name}] {keyword} ({len(board_data)})"
        
        tabs_html += f"""
        <div class="tab-wrapper" data-board-id="board-{global_idx}">
            <button class="tab-btn {active_class}" data-tab-name="{tab_clean_text}" onclick="openTab(event, 'board-{global_idx}')">{new_tag_in_tab}{tab_clean_text}</button>
            <button class="tab-del-btn" onclick="manageKeyword('delete', '{keyword}', '{board}')">×</button>
        </div>
        """
        
        pagination_markup_up = f"""
            <div class="pagination-control" style="position: relative; display: flex; justify-content: center; align-items: center; gap: 8px; margin: 15px 0;">
                <button class="page-nav-btn btn-first" onclick="goToExtremePage('board-{global_idx}', 'first')" title="첫 페이지로">⏮️</button>
                <button class="page-nav-btn btn-prev" onclick="changePage('board-{global_idx}', -1)">◀</button>
                <span class="page-indicator" style="font-size: 14px; font-weight: bold; color: #4e5154; margin: 0 5px;">1 / 1</span>
                <button class="page-nav-btn btn-next" onclick="changePage('board-{global_idx}', 1)">▶</button>
                <button class="page-nav-btn btn-last" onclick="goToExtremePage('board-{global_idx}', 'last')" title="마지막 페이지로">⏭️</button>
                <div class="video-toggle-zone" style="position: absolute; right: 0; display: flex; align-items: center; gap: 6px;">
                    <span style="font-size: 12px; font-weight: bold; color: #4e5154; white-space: nowrap;">🎬</span>
                    <label class="switch" style="width: 38px; height: 22px; display: inline-block; position: relative; flex-shrink: 0;">
                        <input type="checkbox" class="video-only-checkbox" onchange="toggleVideoOnly('board-{global_idx}')">
                        <span class="slider round"></span>
                    </label>
                </div>
            </div>
        """

        pagination_markup_down = f"""
            <div class="pagination-control" style="position: relative; display: flex; justify-content: center; align-items: center; gap: 8px; margin: 15px 0;">
                <button class="page-nav-btn btn-first" onclick="goToExtremePage('board-{global_idx}', 'first')" title="첫 페이지로">⏮️</button>
                <button class="page-nav-btn btn-prev" onclick="changePage('board-{global_idx}', -1)">◀</button>
                <span class="page-indicator" style="font-size: 14px; font-weight: bold; color: #4e5154; margin: 0 5px;">1 / 1</span>
                <button class="page-nav-btn btn-next" onclick="changePage('board-{global_idx}', 1)">▶</button>
                <button class="page-nav-btn btn-last" onclick="goToExtremePage('board-{global_idx}', 'last')" title="마지막 페이지로">⏭️</button>
            </div>
        """

        board_content = f"""
        <div id="board-{global_idx}" class="tab-content" style="display: {display_style};" data-current-page="1" data-tab-name="{tab_clean_text}">
            <div class="update-info">🔄 업데이트: {now} | {board_name} 게시판 -> [{keyword}] 총 {len(board_data)}개 글</div>
            
            {pagination_markup_up}
            
            <div class="posts-container">
        """
        
        if not board_data:
            board_content += '<div class="post-card" style="text-align:center; color:#65676b;">수집된 게시글이 없습니다. 모니터링 중 새 글이 등록되면 수집을 시작합니다.</div>'
        else:
            for post_idx, post in enumerate(board_data):
                content_html = ""
                for block in post['content']:
                    if block == '':
                        content_html += "<div style='height:12px;'></div>"
                    elif block.startswith('<img') or block.startswith('<video') or block.startswith('<div') or block.startswith('<iframe'):
                        content_html += block  
                    else:
                        content_html += f"<p style='margin: 6px 0; line-height: 1.6;'>{block}</p>" 
                
                is_new = post.get('is_new', False)
                card_class = "post-card new-post" if is_new else "post-card"
                new_badge = '<span class="new-badge">NEW</span>' if is_new else ''
                sync_badge = '<span class="sync-badge">🔄 동기화중</span>' if post_idx < MAX_POSTS_TO_SYNC_COMMENTS else ""
                
                comments_html = ""
                if post['comments']:
                    comments_html += f'<div class="post-comments-section"><h3>💬 댓글 ({post["comment_count"]})</h3>'
                    for c in post['comments']:
                        c_content_html = "".join([f"<p style='margin: 3px 0;'>{t}</p>" if t else "<br>" for t in c['content']])
                        
                        is_reply = c.get('is_reply', False)
                        indent_class = "comment-reply" if is_reply else ""
                        reply_icon = '<span style="color:#adb5bd; margin-right:5px; font-weight:bold; display:inline-block !important;">└</span>' if is_reply else ''
                        
                        if c['author'] == post['author']:
                            bg_color = "#fff0f0"
                            author_display = f'{reply_icon}<strong style="color: #ff4747;">{c["author"]} <span style="background-color: #ff4747; color: white; padding: 2px 5px; border-radius: 4px; font-size: 10px; margin-left: 3px; vertical-align: text-bottom;">작성자</span></strong>'
                        else:
                            bg_color = "#f8f9fa"
                            author_display = f"{reply_icon}<strong>{c['author']}</strong>"
                        
                        comments_html += f"""
                        <div class="comment {indent_class}" style="background: {bg_color};">
                            <div class="comment-meta">
                                <div>{author_display} <span style="margin-left:6px; font-size:11px; color:#90949c;">{c['date']}</span></div>
                                <div style="color: #ff4747; font-weight: bold;">👍 {c['votes']}</div>
                            </div>
                            <div class="comment-body">{c_content_html}</div>
                        </div>
                        """
                    comments_html += '</div>'
                
                has_video_val = str(len(post.get('videos', [])) > 0).lower()
                board_content += f"""
                <div class="{card_class}" id="post-{post['id']}" data-is-new="{str(is_new).lower()}" data-has-video="{has_video_val}">
                    <div class="post-header">
                        <div class="post-title">{post['title']}{new_badge}{sync_badge}</div>
                        <div class="post-meta">
                            <span>✍️ {post['author']}</span>
                            <span>👁️ {post['views']}</span>
                            <span>👍 {post['votes']}</span>
                            <span>🕒 {post['date']}</span>
                        </div>
                    </div>
                    <div class="post-body">
                        <div class="post-content">{content_html}</div>
                        <div style="margin-top: 15px; display: flex; gap: 10px;">
                            <a href="{post['link']}" target="_blank" class="original-link-btn" onclick="event.stopPropagation();">🔗 에프엠코리아 원문</a>
                        </div>
                        {comments_html}
                    </div>
                </div>
                """
        
        board_content += f"""
            </div>
            {pagination_markup_down}
        </div>
        """
        boards_html += board_content

    board_options = "".join([f'<option value="{k}">{v}</option>' for k, v in BOARD_MAP.items()])

    alert_toggles_html = ""
    for b_key, b_val in BOARD_MAP.items():
        is_alert_on = board_alert_config.get(b_key, {}).get("alert", True)
        checked_attr = "checked" if is_alert_on else ""
        status_label = "🔔 알림 활성" if is_alert_on else "🔕 알림 꺼짐"
        status_class = "status-on" if is_alert_on else "status-off"
        
        alert_toggles_html += f"""
        <div class="toggle-item">
            <span class="toggle-label">🎯 {b_val}</span>
            <div style="display: flex; align-items: center; gap: 10px;">
                <span class="toggle-status {status_class}">{status_label}</span>
                <label class="switch">
                    <input type="checkbox" {checked_attr} onchange="toggleBoardAlert('{b_key}', this)">
                    <span class="slider round"></span>
                </label>
            </div>
        </div>
        """

    js_meta_string = json.dumps(js_tab_meta_json)

    html_content = f"""<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, minimum-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>통합 멀티 키워드 미니 게시판</title>
    <style>
        body {{ font-family: -apple-system, BlinkMacSystemFont, 'Malgun Gothic', sans-serif; background-color: #f0f2f5; margin: 0; padding: 10px; color: #1c1e21; box-sizing: border-box; }}
        .container {{ width: 100%; max-width: 800px; margin: 0 auto; display: flex; flex-direction: column; }}
        
        .panel-toggle-btn {{ background: #4e5154; color: white; border: none; width: 100%; padding: 10px; font-size: 13px; font-weight: bold; border-radius: 8px; cursor: pointer; margin-bottom: 8px; text-align: center; box-shadow: 0 1px 2px rgba(0,0,0,0.1); transition: background 0.2s; display: flex; align-items: center; justify-content: center; gap: 6px; }}
        .panel-toggle-btn:hover {{ background: #3c3f41; }}
        
        .admin-panel {{ background: #fff; padding: 12px; border-radius: 8px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); display: none; flex-direction: column; gap: 12px; transition: all 0.3s ease; }}
        .admin-title {{ font-size: 13px; font-weight: bold; color: #1c1e21; margin-bottom: 2px; border-bottom: 1px dashed #e4e6eb; padding-bottom: 6px; }}
        .admin-row {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; }}
        .admin-select {{ padding: 8px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; background: white; }}
        .admin-input {{ flex: 1; min-width: 120px; padding: 8px 12px; border: 1px solid #ccd0d5; border-radius: 6px; font-size: 13px; outline: none; }}
        .admin-btn {{ background: #1877f2; color: #fff; border: none; padding: 0 16px; font-size: 13px; font-weight: bold; border-radius: 6px; cursor: pointer; white-space: nowrap; height: 36px; }}

        .refresh-btn {{ display: none; }}

        .alert-management-zone {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr)); gap: 8px; padding-top: 4px; }}
        .toggle-item {{ display: flex; justify-content: space-between; align-items: center; background: #f8f9fa; padding: 6px 10px; border-radius: 6px; border: 1px solid #e4e6eb; }}
        .toggle-label {{ font-size: 13px; font-weight: bold; color: #4e5154; }}
        .toggle-status {{ font-size: 11px; font-weight: bold; padding: 2px 6px; border-radius: 4px; }}
        .toggle-status.status-on {{ background-color: #e2f9e9; color: #1e7e34; }}
        .toggle-status.status-off {{ background-color: #fff0f0; color: #dc3545; }}

        .switch {{ position: relative; display: inline-block; width: 38px; height: 22px; }}
        .switch input {{ opacity: 0; width: 0; height: 0; }}
        .slider {{ position: absolute; cursor: pointer; top: 0; left: 0; right: 0; bottom: 0; background-color: #ccc; transition: .3s; }}
        .slider:before {{ position: absolute; content: ""; height: 16px; width: 16px; left: 3px; bottom: 3px; background-color: white; transition: .3s; }}
        input:checked + .slider {{ background-color: #1877f2; }}
        input:focus + .slider {{ box-shadow: 0 0 1px #1877f2; }}
        input:checked + .slider:before {{ transform: translateX(16px); }}
        .slider.round {{ border-radius: 22px; }}
        .slider.round:before {{ border-radius: 50%; }}

        .tab-container {{ 
            display: flex; 
            gap: 6px; 
            margin-bottom: 15px; 
            border-bottom: 2px solid #e4e6eb; 
            padding-bottom: 10px; 
            overflow-x: auto; 
            white-space: nowrap;
            -webkit-overflow-scrolling: touch; 
            width: 100%;
            box-sizing: border-box;
            cursor: grab;
        }}
        .tab-container:active {{ cursor: grabbing; }}
        .tab-container::-webkit-scrollbar {{ display: none; }}
        
        .tab-wrapper {{ display: flex; align-items: center; background-color: #e4e6eb; border-radius: 20px; overflow: hidden; flex-shrink: 0; }}
        .tab-btn {{ background: none; border: none; padding: 8px 12px 8px 16px; font-size: 13px; font-weight: bold; cursor: pointer; color: #4e5154; outline: none; white-space: nowrap; }}
        .tab-wrapper:has(.tab-btn.active) {{ background-color: #1877f2; }}
        .tab-btn.active {{ color: white; }}
        .tab-del-btn {{ background: none; border: none; padding: 8px 12px 8px 4px; font-size: 14px; cursor: pointer; color: #8d949e; font-weight: bold; outline: none; }}
        .tab-wrapper:has(.tab-btn.active) .tab-del-btn {{ color: #e4e6eb; }}
        
        .post-card {{ background: white; border-radius: 8px; padding: 15px; margin-bottom: 15px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); word-break: break-all; transition: border 0.2s ease, background-color 1s ease; }}
        .post-card.new-post {{ border: 2px solid #1877f2; }}
        .new-badge {{ display: inline-block; background: #1877f2; color: white; font-size: 10px; padding: 2px 6px; border-radius: 10px; margin-left: 5px; }}
        .sync-badge {{ display: inline-block; background: #28a745; color: white; font-size: 10px; padding: 2px 6px; border-radius: 4px; margin-left: 5px; }}
        .post-header {{ border-bottom: 1px solid #e4e6eb; padding-bottom: 8px; margin-bottom: 12px; }}
        .post-title {{ font-size: 16px; font-weight: bold; margin-bottom: 8px; color: #1877f2; line-height: 1.4; }}
        .post-meta {{ font-size: 12px; color: #65676b; display: flex; flex-wrap: wrap; gap: 10px; }}
        .post-content {{ font-size: 14px; line-height: 1.6; color: #1c1e21; }}
        .post-content img {{ width: 100%; height: auto; border-radius: 6px; margin-top: 8px; display: block; }}
        .original-link-btn {{ display: inline-block; padding: 8px 14px; background: #e4e6eb; color: #333; text-decoration: none; border-radius: 6px; font-size: 13px; font-weight: bold; text-align: center; }}
        .update-info {{ text-align: center; color: #65676b; font-size: 12px; margin-bottom: 15px; padding: 8px; background: white; border-radius: 6px; }}
        .post-comments-section {{ margin-top: 15px; border-top: 2px solid #e4e6eb; padding-top: 12px; }}
        .comment {{ padding: 8px 12px; border-radius: 6px; margin-bottom: 8px; font-size: 13px; }}
        .comment-reply {{ margin-left: 12px; border-left: 2px solid #ccd0d5; }}
        .comment-meta {{ display: flex; justify-content: space-between; font-size: 12px; margin-bottom: 4px; }}
        
        .page-nav-btn {{
            background-color: #fff;
            border: 1px solid #ccd0d5;
            color: #1c1e21;
            padding: 6px 10px;
            font-size: 13px;
            font-weight: bold;
            border-radius: 6px;
            cursor: pointer;
            box-shadow: 0 1px 2px rgba(0,0,0,0.05);
            transition: all 0.2s ease;
        }}
        .page-nav-btn:hover {{ background-color: #f2f3f5; }}
        .page-nav-btn:disabled {{ background-color: #e4e6eb; color: #bcc0c4; cursor: not-allowed; border-color: #e4e6eb; }}

        .floating-actions {{
            position: fixed;
            bottom: 25px;
            left: calc(50% + 400px + 15px); 
            display: flex;
            flex-direction: column;
            gap: 12px;
            z-index: 9999;
        }}

        @media (max-width: 830px) {{
            .floating-actions {{
                left: auto;
                right: 25px;
            }}
        }}

        .scroll-top-btn, .floating-refresh-btn {{
            width: 48px;
            height: 48px;
            color: white;
            border: none;
            border-radius: 50%;
            font-size: 20px;
            font-weight: bold;
            cursor: pointer;
            box-shadow: 0 4px 10px rgba(0, 0, 0, 0.2);
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.2s ease;
        }}

        .floating-refresh-btn {{
            background-color: #28a745;
        }}
        .floating-refresh-btn:hover {{
            background-color: #218838;
            transform: translateY(-3px);
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3);
        }}

        .scroll-top-btn {{
            background-color: #1877f2;
            opacity: 0;
            visibility: hidden;
        }}
        .scroll-top-btn.visible {{ opacity: 1; visibility: visible; }}
        .scroll-top-btn:hover {{ background-color: #145dbf; transform: translateY(-3px); box-shadow: 0 6px 12px rgba(0, 0, 0, 0.3); }}
        
        .post-card video, 
        .post-card iframe, 
        .post-card embed, 
        .post-card object {{
            max-width: 100%;
            box-sizing: border-box;
        }}

        .video-wrapper {{
            position: relative;
            padding-bottom: 56.25%;
            padding-top: 25px;
            height: 0;
        }}
        .video-wrapper iframe {{
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
        }}
        
        .top-nav-banner {{
            position: sticky;
            top: 0;
            left: 0;
            width: 100%;
            max-width: 800px;
            background: linear-gradient(135deg, #1e293b, #0f172a);
            box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15);
            z-index: 9999;
            padding: 15px 0;
            margin: 0 auto;
            margin-bottom: 10px;
            border-radius: 8px;
        }}

        .nav-container {{
            position: relative;
            max-width: 1200px;
            margin: 0 auto;
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 15px;
            box-sizing: border-box;
        }}

        .nav-logo {{
            position: absolute; left: 50%; transform: translateX(-50%);
            font-size: 1.1rem;
            font-weight: 700;
            color: #f8fafc;
            text-decoration: none;
            display: flex;
            align-items: center;
            gap: 8px;
            transition: color 0.2s ease;
        }}

        .nav-logo:hover {{
            color: #38bdf8;
        }}

        @media (max-width: 768px) {{
            .nav-container {{
                padding: 0 15px;
            }}
            .nav-logo {{
                font-size: 1rem;
            }}
        }}

        .auto_media_wrapper, 
        .auto_media_wrapper.full.pc,
        .height_keep {{
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
            padding: 0 !important;
            padding-bottom: 0 !important;
            margin: 8px auto !important;
            display: block !important;
        }}

        .post-content img {{ max-width: 100%; height: auto; border-radius: 6px; margin: 6px 0; display: block; }}

        .post-content video {{
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
            max-height: 70vh !important;
            object-fit: contain;
            border-radius: 8px;
            margin: 8px 0;
            display: block;
        }}

        .post-content iframe, 
        .xe_content iframe {{
            width: 100% !important;
            max-width: 100% !important;
            aspect-ratio: 16 / 9 !important;
            border-radius: 8px;
            display: block;
        }}

        .mejs__container, .mejs__embed, .mejs__player {{
            width: 100% !important;
            max-width: 100% !important;
            height: auto !important;
        }}

        .tab-content.video-only-active .post-card:not(.has-video) {{
            display: none !important;
        }}
    </style>
    
    <script>
        (function() {{
            try {{
                let readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]');
                let tabMeta = {js_meta_string}; 
                let styleRules = "";

                if (readIds.length > 0) {{
                    readIds.forEach(id => {{
                        styleRules += `#post-${{id}} {{ border: none !important; }}\\n`;
                        styleRules += `#post-${{id}} .new-badge {{ display: none !important; }}\\n`;
                    }});
                }}

                for (let boardId in tabMeta) {{
                    let newIdsInTab = tabMeta[boardId];
                    if (newIdsInTab.length > 0) {{
                        let isAllRead = newIdsInTab.every(id => readIds.includes(String(id)));
                        if (isAllRead) {{
                            styleRules += `#dot-${{boardId}} {{ display: none !important; }}\\n`;
                        }}
                    }}
                }}

                if (styleRules) {{
                    const styleEl = document.createElement('style');
                    styleEl.innerHTML = styleRules;
                    document.head.appendChild(styleEl);
                }}
            }} catch(e) {{}}
        }}).call(this);
    </script>
    
    <script>
        const POSTS_PER_PAGE = 10;

        function toggleAdminPanel() {{
            const panel = document.getElementById('admin-panel-zone');
            const btn = document.getElementById('panel-toggle-trigger');
            if (panel.style.display === 'none' || panel.style.display === '') {{
                panel.style.display = 'flex';
                btn.innerHTML = '⚙️ 실시간 모니터링 관리 패널 접기 ▲';
                localStorage.setItem('admin_panel_open', 'true');
            }} else {{
                panel.style.display = 'none';
                btn.innerHTML = '⚙️ 실시간 모니터링 관리 패널 열기 ▼';
                localStorage.setItem('admin_panel_open', 'false');
            }}
        }}

        function refreshCurrentTab() {{
            const activeTabContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeTabContent) {{
                const currentBoardId = activeTabContent.id;
                const currentPage = activeTabContent.getAttribute('data-current-page') || '1';
                
                sessionStorage.setItem('last_active_board', currentBoardId);
                sessionStorage.setItem('last_active_page', currentPage);
                sessionStorage.setItem('is_refreshing', 'true');
            }}
            window.location.reload();
        }}

        function toggleVideoOnly(boardId, sourceCheckbox) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            const checkboxes = Array.from(boardEl.querySelectorAll('.video-only-checkbox'));
            
            let targetState = false;
            if (sourceCheckbox) {{
                targetState = sourceCheckbox.checked;
            }} else if (checkboxes.length > 0) {{
                targetState = checkboxes[0].checked;
            }}

            checkboxes.forEach(cb => {{
                cb.checked = targetState;
            }});
            
            boardEl.setAttribute('data-current-page', '1');
            updatePagination(boardId);
        }}

        function updatePagination(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            const postsContainer = boardEl.querySelector('.posts-container');
            if (!postsContainer) return;

            const posts = Array.from(postsContainer.querySelectorAll('.post-card:not(.empty-video-state)'));
            const controls = boardEl.querySelectorAll('.pagination-control');
            
            const allCheckboxes = boardEl.querySelectorAll('.video-only-checkbox');
            let isVideoOnly = false;
            allCheckboxes.forEach(cb => {{
                if (cb.checked) isVideoOnly = true;
            }});
            
            let targetPosts = posts;
            if (isVideoOnly) {{
                targetPosts = posts.filter(post => post.getAttribute('data-has-video') === 'true');
            }}
            
            posts.forEach(post => post.style.display = 'none');
            
            const existingEmpty = postsContainer.querySelector('.empty-video-state');
            if (existingEmpty) existingEmpty.remove();
            
            if (targetPosts.length === 0) {{
                controls.forEach(ctrl => {{
                    ctrl.style.display = 'flex';
                    const indicator = ctrl.querySelector('.page-indicator');
                    if (indicator) indicator.innerText = "0 / 0";
                    
                    const btns = ctrl.querySelectorAll('button');
                    btns.forEach(btn => btn.disabled = true);
                }});
                
                const emptyMsg = document.createElement('div');
                emptyMsg.className = 'post-card empty-video-state';
                emptyMsg.style.textAlign = 'center';
                emptyMsg.style.color = '#65676b';
                emptyMsg.style.padding = '30px 10px';
                emptyMsg.innerText = '🎥 동영물이 포함된 게시글이 없습니다.';
                postsContainer.appendChild(emptyMsg);
                return;
            }}
            
            controls.forEach(ctrl => ctrl.style.display = 'flex');
            
            let currentPage = parseInt(boardEl.getAttribute('data-current-page') || '1');
            const totalPages = Math.ceil(targetPosts.length / POSTS_PER_PAGE) || 1;
            
            if (currentPage > totalPages) currentPage = totalPages;
            if (currentPage < 1) currentPage = 1;
            boardEl.setAttribute('data-current-page', currentPage);
            
            const startIdx = (currentPage - 1) * POSTS_PER_PAGE;
            const endIdx = startIdx + POSTS_PER_PAGE;
            
            targetPosts.forEach((post, index) => {{
                if (index >= startIdx && index < endIdx) {{
                    post.style.display = 'block';
                }} else {{
                    post.style.display = 'none';
                }}
            }});
            
            controls.forEach(ctrl => {{
                const indicator = ctrl.querySelector('.page-indicator');
                if (indicator) indicator.innerText = currentPage + " / " + totalPages;
                
                const firstBtn = ctrl.querySelector('.btn-first');
                const prevBtn = ctrl.querySelector('.btn-prev');
                const nextBtn = ctrl.querySelector('.btn-next');
                const lastBtn = ctrl.querySelector('.btn-last');
                
                if (firstBtn) firstBtn.disabled = (currentPage === 1);
                if (prevBtn) prevBtn.disabled = (currentPage === 1);
                if (nextBtn) nextBtn.disabled = (currentPage === totalPages);
                if (lastBtn) lastBtn.disabled = (currentPage === totalPages);
            }});
        }}

        function changePage(boardId, direction) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            let currentPage = parseInt(boardEl.getAttribute('data-current-page') || '1');
            currentPage += direction;
            boardEl.setAttribute('data-current-page', currentPage);
            updatePagination(boardId);
            
            const containerOffset = document.querySelector('.tab-container').offsetTop + 50;
            window.scrollTo({{ top: containerOffset, behavior: 'smooth' }});
        }}

        function goToExtremePage(boardId, target) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;
            
            const posts = boardEl.querySelectorAll('.posts-container > .post-card');
            const totalPages = Math.ceil(posts.length / POSTS_PER_PAGE) || 1;
            
            let targetPage = (target === 'first') ? 1 : totalPages;
            boardEl.setAttribute('data-current-page', targetPage);
            updatePagination(boardId);
            
            const containerOffset = document.querySelector('.tab-container').offsetTop + 50;
            window.scrollTo({{ top: containerOffset, behavior: 'smooth' }});
        }}

        function savePostsToReadList(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            const allCards = boardEl.querySelectorAll('.posts-container > .post-card');
            if (allCards.length === 0) return;

            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            let hasNewRead = false;
            allCards.forEach(card => {{
                const idMatch = card.id.replace('post-', '');
                if (idMatch && !readIds.includes(idMatch)) {{
                    readIds.push(idMatch);
                    hasNewRead = true;
                }}
            }});

            if (hasNewRead) {{
                if (readIds.length > 1500) readIds = readIds.slice(readIds.length - 1500);
                localStorage.setItem('read_post_ids', JSON.stringify(readIds));
            }}
        }}

        function clearPostBadgesInDOM(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            const cards = boardEl.querySelectorAll('.posts-container > .post-card');
            cards.forEach(card => {{
                card.classList.remove('new-post');
                card.style.border = 'none';
                const badge = card.querySelector('.new-badge');
                if (badge) badge.remove();
            }});
        }}

        function syncTabDotState(boardId) {{
            const boardEl = document.getElementById(boardId);
            if (!boardEl) return;

            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            const allNewCards = boardEl.querySelectorAll('.posts-container > .post-card[data-is-new="true"]');
            let hasUnreadPost = false;

            for (let card of allNewCards) {{
                const id = card.id.replace('post-', '');
                if (!readIds.includes(id)) {{
                    hasUnreadPost = true;
                    break;
                }}
            }}

            const globalIdx = boardId.replace('board-', '');
            const targetDot = document.getElementById('dot-board-' + globalIdx);
            if (targetDot) {{
                targetDot.style.display = hasUnreadPost ? 'inline' : 'none';
            }}
        }}

        function openTab(evt, boardId) {{
            const previousActiveTab = document.querySelector('.tab-content[style*="display: block"]');
            if (previousActiveTab && previousActiveTab.id !== boardId) {{
                savePostsToReadList(previousActiveTab.id);
                clearPostBadgesInDOM(previousActiveTab.id);
            }}

            var i, tabcontent, tablinks;
            tabcontent = document.getElementsByClassName("tab-content");
            for (i = 0; i < tabcontent.length; i++) {{ tabcontent[i].style.display = "none"; }}
            tablinks = document.getElementsByClassName("tab-btn");
            for (i = 0; i < tablinks.length; i++) {{ tablinks[i].className = tablinks[i].className.replace(" active", ""); }}
            
            const targetBoard = document.getElementById(boardId);
            targetBoard.style.display = "block";
            if (evt) evt.currentTarget.className += " active";
            
            updatePagination(boardId);
            
            const globalIdx = boardId.replace('board-', '');
            const targetDot = document.getElementById('dot-board-' + globalIdx);
            if (targetDot) targetDot.style.display = 'none';
        }}

        function restoreAllTabsState() {{
            const allContents = document.querySelectorAll('.tab-content');
            
            let readIds = [];
            try {{ readIds = JSON.parse(localStorage.getItem('read_post_ids') || '[]'); }} catch(e) {{}}

            allContents.forEach(content => {{
                const boardId = content.id;
                
                const cards = content.querySelectorAll('.posts-container > .post-card');
                cards.forEach(card => {{
                    const id = card.id.replace('post-', '');
                    if (readIds.includes(id)) {{
                        card.classList.remove('new-post');
                        card.style.border = 'none';
                        const badge = card.querySelector('.new-badge');
                        if (badge) badge.remove();
                    }}
                }});

                syncTabDotState(boardId);
            }});
            
            const activeContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeContent) {{
                updatePagination(activeContent.id);
                
                if (sessionStorage.getItem('is_refreshing') === 'true') {{
                    savePostsToReadList(activeContent.id);
                    sessionStorage.removeItem('is_refreshing');
                    clearPostBadgesInDOM(activeContent.id);
                }} else {{
                    const globalIdx = activeContent.id.replace('board-', '');
                    const targetDot = document.getElementById('dot-board-' + globalIdx);
                    if (targetDot) targetDot.style.display = 'none';
                }}
            }}
        }}

        function scrollToTop() {{
            window.scrollTo({{ top: 0, behavior: 'smooth' }});
        }}

        function toggleBoardAlert(boardKey, checkboxElement) {{
            let pwd = document.getElementById('admin-pwd-input').value.trim();
            if (!pwd) {{ 
                alert('알림 설정을 변경하려면 패널 우측의 관리자 암호를 먼저 입력해 주세요.'); 
                checkboxElement.checked = !checkboxElement.checked;
                return; 
            }}
            
            const targetStatus = checkboxElement.checked;
            const apiUrl = '/api/toggle-alert?board=' + encodeURIComponent(boardKey) + 
                           '&enabled=' + targetStatus + 
                           '&password=' + encodeURIComponent(pwd);
            
            fetch(apiUrl, {{
                method: 'GET',
                headers: {{ 'Accept': 'application/json' }}
            }})
            .then(res => res.json())
            .then(data => {{
                alert(data.message);
                if (data.success) {{ 
                    location.reload(); 
                }} else {{
                    checkboxElement.checked = !targetStatus;
                }}
            }})
            .catch(err => {{
                alert('알림 상태 요청 중 오류가 발생했습니다.');
                checkboxElement.checked = !targetStatus;
            }});
        }}

        function handleTelegramAnchorLink() {{
            const hash = window.location.hash;
            if (hash && hash.startsWith('#post-')) {{
                const targetPost = document.getElementById(hash.replace('#', ''));
                if (targetPost) {{
                    const parentTab = targetPost.closest('.tab-content');
                    if (parentTab) {{
                        const boardId = parentTab.id;
                        
                        const videoOnlyCheckbox = parentTab.querySelector('.video-only-checkbox');
                        if (videoOnlyCheckbox && videoOnlyCheckbox.checked) {{
                            videoOnlyCheckbox.checked = false;
                        }}
                        
                        const allCardsInTab = Array.from(parentTab.querySelectorAll('.posts-container > .post-card'));
                        const postIndex = allCardsInTab.indexOf(targetPost);
                        
                        if (postIndex !== -1) {{
                            const targetPage = Math.ceil((postIndex + 1) / POSTS_PER_PAGE);
                            parentTab.setAttribute('data-current-page', targetPage);
                        }}
                        
                        const tabcontents = document.getElementsByClassName("tab-content");
                        for (let i = 0; i < tabcontents.length; i++) {{ tabcontents[i].style.display = "none"; }}
                        parentTab.style.display = "block";
                        
                        const tablinks = document.getElementsByClassName("tab-btn");
                        for (let i = 0; i < tablinks.length; i++) {{ tablinks[i].classList.remove("active"); }}
                        const matchWrapperBtn = document.querySelector(`.tab-wrapper[data-board-id="${{boardId}}"] .tab-btn`);
                        if (matchWrapperBtn) matchWrapperBtn.classList.add("active");
                        
                        updatePagination(boardId);
                        
                        setTimeout(() => {{
                            const elementPosition = targetPost.getBoundingClientRect().top + window.pageYOffset;
                            const offset = 60;
                            const offsetPosition = elementPosition - offset;

                            window.scrollTo({{
                                top: offsetPosition,
                                behavior: 'smooth'
                            }});

                            targetPost.style.backgroundColor = '#fff9c4'; 
                            setTimeout(() => {{ targetPost.style.backgroundColor = ''; }}, 2500);
                        }}, 400);
                    }}
                }} else {{
                    const postId = hash.replace('#post-', '');
                    if (postId) {{
                        window.location.replace('https://www.fmkorea.com/' + postId);
                    }}
                }}
            }}
        }}

        window.addEventListener('beforeunload', () => {{
            const activeContent = document.querySelector('.tab-content[style*="display: block"]');
            if (activeContent) {{
                savePostsToReadList(activeContent.id);
            }}
        }});

        window.addEventListener('DOMContentLoaded', () => {{
            const savedBoard = sessionStorage.getItem('last_active_board');
            const savedPage = sessionStorage.getItem('last_active_page');
            
            sessionStorage.removeItem('last_active_board');
            sessionStorage.removeItem('last_active_page');
            
            if (savedBoard && document.getElementById(savedBoard)) {{
                const tabcontents = document.getElementsByClassName("tab-content");
                for (let i = 0; i < tabcontents.length; i++) {{ tabcontents[i].style.display = "none"; }}
                const tablinks = document.getElementsByClassName("tab-btn");
                for (let i = 0; i < tablinks.length; i++) {{ tablinks[i].classList.remove("active"); }}
                
                const targetBoard = document.getElementById(savedBoard);
                targetBoard.style.display = "block";
                
                const matchWrapper = document.querySelector('.tab-wrapper[data-board-id="' + savedBoard + '"] .tab-btn');
                if (matchWrapper) matchWrapper.classList.add("active");
                
                if (savedPage) targetBoard.setAttribute('data-current-page', savedPage);
                updatePagination(savedBoard);
            }} else {{
                const activeTabContent = document.querySelector('.tab-content[style*="display: block"]');
                if (activeTabContent) {{
                    updatePagination(activeTabContent.id);
                }} else {{
                    const allTabs = document.querySelectorAll('.tab-content');
                    allTabs.forEach(t => updatePagination(t.id));
                }}
            }}
            
            restoreAllTabsState();

            handleTelegramAnchorLink();

            if (localStorage.getItem('admin_panel_open') === 'true') {{
                document.getElementById('admin-panel-zone').style.display = 'flex';
                document.getElementById('panel-toggle-trigger').innerHTML = '⚙️ 실시간 모니터링 관리 패널 접기 ▲';
            }}

            const topBtn = document.getElementById('floating-top-btn');
            window.addEventListener('scroll', () => {{
                if (window.scrollY > 300) {{
                    topBtn.classList.add('visible');
                }} else {{
                    topBtn.classList.remove('visible');
                }}
            }});
        }});

        window.addEventListener('hashchange', handleTelegramAnchorLink);

        function manageKeyword(action, targetKw, targetBoard) {{
            let kw = targetKw || document.getElementById('new-kw-input').value.trim();
            let pwd = document.getElementById('admin-pwd-input').value.trim();
            let board = targetBoard || document.getElementById('board-select').value;
            
            if (!kw) {{ alert('키워드를 입력해 주세요.'); return; }}
            if (!pwd) {{ alert('인증 관리자 비밀번호를 입력해야 합니다.'); return; }}
            
            if (action === 'delete') {{
                if (!confirm("'" + kw + "' 키워드를 정말 삭제하시겠습니까?")) return;
            }}
            
            const btn = window.event ? window.event.target : null;
            if (btn) btn.disabled = true;

            fetch('/api/keyword', {{
                method: 'POST',
                headers: {{ 'Content-Type': 'application/json' }},
                body: JSON.stringify({{ action: action, keyword: kw, board: board, password: pwd }})
            }})
            .then(res => res.json())
            .then(data => {{
                alert(data.message);
                if (data.success) {{ location.reload(); }}
            }})
            .catch(err => {{
                alert('요청 중 오류가 발생했습니다.');
            }})
            .finally(() => {{
                if (btn) btn.disabled = false;
            }});
        }}
    </script>
</head>
<body>
    <header class="top-nav-banner">
        <div class="nav-container">
            <a href="/" class="nav-logo">
                <span class="icon">🏠</span> 실시간 모니터링 대시보드
            </a>
        </div>
    </header>
    <div class="container">
        <button id="panel-toggle-trigger" class="panel-toggle-btn" onclick="toggleAdminPanel()">⚙️ 실시간 모니터링 관리 패널 열기 ▼</button>

        <div class="admin-panel" id="admin-panel-zone">
            <div class="admin-title">🛠️ 키워드 실시간 모니터링 관리 패널</div>
            <div class="admin-row">
                <select id="board-select" class="admin-select">
                    {board_options}
                </select>
                <input type="text" id="new-kw-input" class="admin-input" placeholder="추가할 키워드 입력">
                <input type="password" id="admin-pwd-input" class="admin-input" style="max-width:140px;" placeholder="관리자 암호">
                <button class="admin-btn" onclick="manageKeyword('add')">➕ 등록</button>
            </div>
            
            <div class="admin-title" style="margin-top: 4px;">🔔 게시판별 텔레그램 알림 토글 제어 (관리자 암호 필요)</div>
            <div class="alert-management-zone">
                {alert_toggles_html}
            </div>
        </div>

        <div class="tab-container" id="tab-scroll-container">
            {tabs_html}
        </div>

        {boards_html}
    </div>

    <div class="floating-actions">
        <button class="floating-refresh-btn" onclick="refreshCurrentTab()" title="현재 키워드 즉시 새로고침">🔄</button>
        <button id="floating-top-btn" class="scroll-top-btn" onclick="scrollToTop()" title="맨 위로 이동">▲</button>
    </div>

    <script>
        const slider = document.getElementById('tab-scroll-container');
        let isDown = false;
        let startX;
        let scrollLeft;

        slider.addEventListener('mousedown', (e) => {{
            isDown = true;
            slider.classList.add('active');
            startX = e.pageX - slider.offsetLeft;
            scrollLeft = slider.scrollLeft;
        }});
        slider.addEventListener('mouseleave', () => {{
            isDown = false;
            slider.classList.remove('active');
        }});
        slider.addEventListener('mouseup', () => {{
            isDown = false;
            slider.classList.remove('active');
        }});
        slider.addEventListener('mousemove', (e) => {{
            if(!isDown) return;
            e.preventDefault();
            const x = e.pageX - slider.offsetLeft;
            const walk = (x - startX) * 2;
            slider.scrollLeft = scrollLeft - walk;
        }});
    </script>
</body>
</html>
"""
    try:
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(html_content)
        log_msg(f"HTML 빌드 및 index.html 디스크 파일 출력 완료 (총 키워드 조합: {len(flattened_keywords)}개)", "INFO")
    except Exception as e:
        log_msg(f"⚠️ HTML 템플릿 물리 저장 중 오류 발생: {e}", "ERROR")
